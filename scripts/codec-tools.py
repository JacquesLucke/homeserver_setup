# Inspects and cleans up the codecs of all movie files in a folder.
# Use as:
#   uv run scripts/codec-tools.py status <folder>
#   uv run scripts/codec-tools.py clean --dry <folder>
#   uv run scripts/codec-tools.py clean <folder>
#   uv run scripts/codec-tools.py delete-originals --dry <folder>
#   uv run scripts/codec-tools.py delete-originals <folder>
#   uv run scripts/codec-tools.py status smb://polaris/storage/media/Shorts
# URLs like smb:// are accessed through the local gvfs mount, which is created if necessary.

import signal
import subprocess
import tempfile
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from types import FrameType
from typing import Annotated

import typer
from pydantic import BaseModel, ConfigDict

MOVIE_EXTENSIONS = {
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ts",
    ".vob",
    ".webm",
    ".wmv",
}

# Files following these rules can be played directly by most clients. Other files are converted
# by the clean command. Only the streams that break a rule are re-encoded, others are copied.
ALLOWED_EXTENSIONS = {".mkv", ".mp4"}
# AV1 and VP9 can't be played directly by all clients, but the server's Intel N150 decodes them in
# hardware, so transcoding them is cheap. Re-encoding them as HEVC would make them larger.
ALLOWED_VIDEO_CODECS = {"h264", "hevc", "av1", "vp9"}
ALLOWED_AUDIO_CODECS = {"aac", "ac3", "eac3", "mp3"}
TARGET_EXTENSION = ".mkv"
VIDEO_ENCODER = "libx265"
VIDEO_PRESET = "medium"
VIDEO_CRF = 22
VIDEO_PIXEL_FORMAT = "yuv420p10le"
# Keyframes are closed GOPs at most this far apart, so that seeking doesn't show artifacts.
# Scene cuts can still add keyframes in between.
KEYFRAME_INTERVAL_SECONDS = 5
# Used if ffprobe doesn't know the frame rate.
FALLBACK_FRAME_RATE = 24
# Stereo is encoded as AAC, which plays everywhere. Surround is encoded as E-AC3, which TVs can
# pass through to receivers. ffmpeg's E-AC3 encoder supports at most 5.1, so 7.1 is downmixed.
STEREO_AUDIO_ENCODER = "aac"
STEREO_AUDIO_BITRATE_PER_CHANNEL_KBPS = 96
SURROUND_AUDIO_ENCODER = "eac3"
SURROUND_AUDIO_BITRATE_KBPS = 640
SURROUND_AUDIO_MAX_CHANNELS = 6

# Not in /tmp, because that is often in memory and too small for movies.
TEMP_DIR = Path.home() / ".cache" / "codec-tools"
# Appended to the name of the original file, which is kept as a backup. Jellyfin ignores the file
# because it doesn't have a video extension anymore.
BACKUP_SUFFIX = ".codec-tools-original"
# Maximum difference between the durations of the original and the cleaned file.
MAX_DURATION_DIFFERENCE_SECONDS = 1.0


class Model(BaseModel):
    # ffprobe outputs many more keys, only the ones used here are declared.
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)


class Disposition(Model):
    # Set for cover art, which is embedded as a video stream.
    attached_pic: int = 0


class Stream(Model):
    codec_type: str
    # Missing for streams that ffprobe can't decode.
    codec_name: str = "unknown"
    # Only set for audio streams.
    channels: int = 2
    channel_layout: str | None = None
    # Only meaningful for video streams, e.g. "24000/1001". "0/0" if unknown.
    avg_frame_rate: str = "0/0"
    disposition: Disposition = Disposition()


class Format(Model):
    # In seconds, e.g. "123.456000". Missing for some broken files.
    duration: str | None = None


class ProbeResult(Model):
    streams: list[Stream]
    format: Format


@dataclass(frozen=True)
class MovieFile:
    path: Path
    # Path relative to the scanned folder, used for display.
    name: Path
    progress: str
    # None if ffprobe failed.
    streams: list[Stream] | None
    error: str | None
    # In seconds, None if unknown.
    duration: float | None = None


@dataclass(frozen=True)
class CleanPlan:
    reasons: list[str]
    # Encoder arguments for the streams that have to be re-encoded, all other streams are copied.
    codec_args: list[str]
    target: Path


class CleanError(Exception):
    pass


app = typer.Typer(no_args_is_help=True)


@app.command()
def status(location: str) -> None:
    """Print the video and audio codecs of every movie file in the folder or URL."""
    video_counts: Counter[str] = Counter()
    audio_counts: Counter[str] = Counter()
    extension_counts: Counter[str] = Counter()
    total = 0
    failed = 0
    for movie in scan(local_path(location)):
        total += 1
        print(f"{movie.progress} {movie.name}")
        if movie.streams is None:
            failed += 1
            print(f"    error: {movie.error}", flush=True)
            continue
        video = codecs_of_type(movie.streams, "video")
        audio = codecs_of_type(movie.streams, "audio")
        print(f"    video: {', '.join(video) or '-'}")
        print(f"    audio: {', '.join(audio) or '-'}", flush=True)
        # Count every codec once per file, so the summary shows how many files use it.
        video_counts.update(set(video))
        audio_counts.update(set(audio))
        extension_counts[movie.path.suffix.lower()] += 1

    print()
    print("Summary:")
    print(f"  Files: {total}" + (f" ({failed} could not be read)" if failed else ""))
    print_counts("Containers", extension_counts)
    print_counts("Video codecs", video_counts)
    print_counts("Audio codecs", audio_counts)


@app.command()
def clean(
    location: str,
    dry: Annotated[bool, typer.Option(help="Only show what would be done.")] = False,
) -> None:
    """Re-encode files that break the codec rules. The originals are kept as backups."""
    folder = local_path(location)
    total = 0
    failed = 0
    planned = 0
    cleaned = 0
    size_before = 0
    size_after = 0
    for movie in scan(folder):
        total += 1
        if movie.streams is None:
            failed += 1
            print(f"{movie.progress} {movie.name}\n    error: {movie.error}", flush=True)
            continue
        plan = make_clean_plan(movie.path, movie.streams)
        if plan is None:
            print(f"{movie.progress} {movie.name}: ok", flush=True)
            continue
        planned += 1
        print(f"{movie.progress} {movie.name}")
        for reason in plan.reasons:
            print(f"    {reason}")
        if dry:
            print_clean_steps(movie.path, plan)
            continue
        original_size = movie.path.stat().st_size
        try:
            run_clean(movie.path, plan, movie.duration, video_frame_rate(movie.streams))
        except (CleanError, OSError, subprocess.CalledProcessError) as error:
            failed += 1
            print(f"    error: {error}", flush=True)
            continue
        cleaned += 1
        new_size = plan.target.stat().st_size
        size_before += original_size
        size_after += new_size
        print(f"    done: {format_size(original_size)} -> {format_size(new_size)}", flush=True)

    print()
    print("Summary:")
    print(f"  Files: {total}" + (f" ({failed} failed)" if failed else ""))
    if dry:
        print(f"  Would be cleaned: {planned}")
        print("  Dry run, nothing was changed.")
    else:
        print(f"  Cleaned: {cleaned} ({format_size(size_before)} -> {format_size(size_after)})")
        print(f"  Backups of the originals end with {BACKUP_SUFFIX}.")


@app.command()
def delete_originals(
    location: str,
    dry: Annotated[bool, typer.Option(help="Only show what would be deleted.")] = False,
) -> None:
    """Delete the backups of the original files that the clean command kept."""
    folder = local_path(location)
    print(f"Searching for backups in {folder}...", flush=True)
    backups = sorted(path for path in folder.rglob(f"*{BACKUP_SUFFIX}") if path.is_file())
    print(f"Found {len(backups)} backups.", flush=True)

    deleted = 0
    skipped = 0
    freed = 0
    for backup in backups:
        name = backup.relative_to(folder)
        # Don't delete the only copy, e.g. if the cleaned file was deleted to restore the backup.
        if not has_cleaned_file(backup):
            skipped += 1
            print(f"  skipped, cleaned file is missing: {name}", flush=True)
            continue
        size = backup.stat().st_size
        if not dry:
            backup.unlink()
        deleted += 1
        freed += size
        print(f"  {'would delete' if dry else 'deleted'}: {name} ({format_size(size)})", flush=True)

    print()
    print("Summary:")
    print(f"  {'Would be deleted' if dry else 'Deleted'}: {deleted} ({format_size(freed)})")
    if skipped:
        print(f"  Skipped: {skipped}")
    if dry:
        print("  Dry run, nothing was changed.")


def has_cleaned_file(backup: Path) -> bool:
    original = backup.with_name(backup.name.removesuffix(BACKUP_SUFFIX))
    return original.exists() or original.with_suffix(TARGET_EXTENSION).exists()


def scan(folder: Path) -> Iterator[MovieFile]:
    print(f"Searching for movie files in {folder}...", flush=True)
    paths = sorted(
        path
        for path in folder.rglob("*")
        if path.suffix.lower() in MOVIE_EXTENSIONS and path.is_file()
    )
    print(f"Found {len(paths)} movie files.", flush=True)

    width = len(str(len(paths)))
    for index, path in enumerate(paths, start=1):
        progress = f"[{index:>{width}}/{len(paths)}]"
        name = path.relative_to(folder)
        try:
            result = probe(path)
            duration = parse_float(result.format.duration)
            yield MovieFile(path, name, progress, result.streams, None, duration)
        except subprocess.CalledProcessError as error:
            yield MovieFile(path, name, progress, None, error.stderr.strip())


def make_clean_plan(path: Path, streams: list[Stream]) -> CleanPlan | None:
    reasons: list[str] = []
    codec_args: list[str] = []
    # Keep the original spelling of allowed extensions. Changing only the case would make the
    # final delete remove the new file on case-insensitive file systems like SMB shares.
    extension = path.suffix
    if extension.lower() not in ALLOWED_EXTENSIONS:
        reasons.append(f"container {extension} -> {TARGET_EXTENSION}")
        extension = TARGET_EXTENSION

    # ffmpeg addresses streams by their index among the streams of the same type.
    type_indices: Counter[str] = Counter()
    for stream in streams:
        type_index = type_indices[stream.codec_type]
        type_indices[stream.codec_type] += 1
        if stream.disposition.attached_pic:
            continue
        if stream.codec_type == "video" and stream.codec_name not in ALLOWED_VIDEO_CODECS:
            reasons.append(f"video stream {type_index}: {stream.codec_name} -> {VIDEO_ENCODER}")
            codec_args += video_encoding_args(stream, type_index, extension)
        elif stream.codec_type == "audio" and stream.codec_name not in ALLOWED_AUDIO_CODECS:
            target, args = audio_encoding(stream, type_index)
            source = f"{stream.codec_name} {layout_name(stream)}"
            reasons.append(f"audio stream {type_index}: {source} -> {target}")
            codec_args += args

    if not reasons:
        return None
    return CleanPlan(reasons, codec_args, path.with_suffix(extension))


def video_encoding_args(stream: Stream, type_index: int, extension: str) -> list[str]:
    keyint = round((frame_rate(stream) or FALLBACK_FRAME_RATE) * KEYFRAME_INTERVAL_SECONDS)
    args = [
        f"-c:v:{type_index}",
        VIDEO_ENCODER,
        f"-preset:v:{type_index}",
        VIDEO_PRESET,
        f"-crf:v:{type_index}",
        str(VIDEO_CRF),
        f"-pix_fmt:v:{type_index}",
        VIDEO_PIXEL_FORMAT,
        f"-x265-params:v:{type_index}",
        f"open-gop=0:keyint={keyint}",
    ]
    if extension.lower() == ".mp4":
        # Apple devices only recognize HEVC in mp4 files with this tag.
        args += [f"-tag:v:{type_index}", "hvc1"]
    return args


def frame_rate(stream: Stream) -> Fraction | None:
    try:
        return Fraction(stream.avg_frame_rate) or None
    except ZeroDivisionError:
        return None


def video_frame_rate(streams: list[Stream]) -> Fraction | None:
    for stream in streams:
        if stream.codec_type == "video" and not stream.disposition.attached_pic:
            return frame_rate(stream)
    return None


def audio_encoding(stream: Stream, type_index: int) -> tuple[str, list[str]]:
    """Returns a description of the target encoding and the ffmpeg arguments for it."""
    if stream.channels <= 2:
        bitrate = stream.channels * STEREO_AUDIO_BITRATE_PER_CHANNEL_KBPS
        target = f"{STEREO_AUDIO_ENCODER} {layout_name(stream)} {bitrate}k"
        return target, [
            f"-c:a:{type_index}",
            STEREO_AUDIO_ENCODER,
            f"-b:a:{type_index}",
            f"{bitrate}k",
        ]
    args = [
        f"-c:a:{type_index}",
        SURROUND_AUDIO_ENCODER,
        f"-b:a:{type_index}",
        f"{SURROUND_AUDIO_BITRATE_KBPS}k",
    ]
    layout = layout_name(stream)
    if stream.channels > SURROUND_AUDIO_MAX_CHANNELS:
        # Downmix explicitly, otherwise the encoder silently drops channels.
        args += [f"-ac:a:{type_index}", str(SURROUND_AUDIO_MAX_CHANNELS)]
        layout = "5.1 (downmixed)"
    return f"{SURROUND_AUDIO_ENCODER} {layout} {SURROUND_AUDIO_BITRATE_KBPS}k", args


def layout_name(stream: Stream) -> str:
    return stream.channel_layout or f"{stream.channels}ch"


def print_clean_steps(path: Path, plan: CleanPlan) -> None:
    temp_dir = TEMP_DIR / "<temp>"
    temp_input = temp_dir / f"input{path.suffix}"
    temp_output = temp_dir / f"output{plan.target.suffix}"
    command = ffmpeg_command(temp_input, temp_output, plan.codec_args)
    print("    would:")
    print(f"      copy {path} -> {temp_input}")
    print(f"      run {' '.join(command)}")
    print("      check that the duration and number of streams are unchanged")
    print(f"      copy {temp_output} -> {partial_path(plan.target)}")
    print(f"      rename {path} -> {backup_path(path)}")
    print(f"      rename {partial_path(plan.target)} -> {plan.target}")


def run_clean(
    path: Path, plan: CleanPlan, duration: float | None, frame_rate: Fraction | None
) -> None:
    backup = backup_path(path)
    partial = partial_path(plan.target)
    if backup.exists():
        raise CleanError(f"backup {backup} exists already")
    if plan.target != path and plan.target.exists():
        raise CleanError(f"{plan.target} exists already")

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TEMP_DIR) as temp_dir:
        temp_input = Path(temp_dir) / f"input{path.suffix}"
        temp_output = Path(temp_dir) / f"output{plan.target.suffix}"
        try:
            copy_with_progress(path, temp_input, "copying to temp folder")
            command = ffmpeg_command(temp_input, temp_output, plan.codec_args)
            if not run_ffmpeg(command, duration, frame_rate):
                raise CleanError("ffmpeg failed")
            check_output(temp_input, temp_output)
            # Copied next to the target first, so that the final rename is fast and can't leave a
            # partially written file behind.
            copy_with_progress(temp_output, partial, "copying back")
            # Interruptions are delayed until both renames are done, so that the original or the
            # cleaned file is always in place.
            old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
            try:
                path.rename(backup)
                try:
                    partial.rename(plan.target)
                except OSError:
                    backup.rename(path)
                    raise
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)
        finally:
            partial.unlink(missing_ok=True)


def run_ffmpeg(command: list[str], duration: float | None, frame_rate: Fraction | None) -> bool:
    """Runs ffmpeg and keeps a progress line updated. Returns whether it succeeded."""
    # ffmpeg writes blocks of key=value lines to stdout, each ending with a "progress" key.
    start = time.monotonic()
    with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as process:
        assert process.stdout is not None
        values: dict[str, str] = {}
        try:
            for line in process.stdout:
                key, _, value = line.strip().partition("=")
                values[key] = value
                if key == "progress":
                    line = format_progress(values, time.monotonic() - start, duration, frame_rate)
                    # Overwrite the previous progress line.
                    print(f"\r    encoding: {line}\033[K", end="", flush=True)
        except BaseException:
            # ffmpeg only receives Ctrl+C itself, not a SIGTERM sent to this script.
            process.terminate()
            raise
        finally:
            print()
    return process.returncode == 0


def format_progress(
    values: dict[str, str], elapsed: float, duration: float | None, frame_rate: Fraction | None
) -> str:
    parts: list[str] = []
    frame = parse_float(values.get("frame")) or 0
    total_frames = round(duration * frame_rate) if duration and frame_rate else None
    # Based on frames instead of ffmpeg's output time, because the audio can be encoded far ahead
    # of the video.
    done = min(frame / total_frames, 1) if total_frames else None
    if done is not None:
        parts.append(f"{done:.1%}")
    parts.append(f"frame {round(frame)}" + (f"/{total_frames}" if total_frames else ""))
    fps = parse_float(values.get("fps"))
    if fps:
        parts.append(f"{fps:.1f} fps")
    if done:
        parts.append(f"{format_duration(elapsed * (1 - done) / done)} left")
    return ", ".join(parts)


def copy_with_progress(source: Path, target: Path, label: str) -> None:
    print(f"    {label}:", flush=True)
    subprocess.run(["gio", "copy", "--progress", source, target], check=True)
    print()


def format_duration(seconds: float) -> str:
    minutes, seconds = divmod(round(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02}m" if hours else f"{minutes}m{seconds:02}s"


def parse_float(value: str | None) -> float | None:
    # ffmpeg uses "N/A" for unknown values.
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def check_output(original: Path, output: Path) -> None:
    original_result = probe(original)
    output_result = probe(output)
    if len(original_result.streams) != len(output_result.streams):
        raise CleanError(
            f"stream count changed from {len(original_result.streams)} "
            f"to {len(output_result.streams)}"
        )
    original_duration = original_result.format.duration
    output_duration = output_result.format.duration
    if original_duration is None or output_duration is None:
        return
    if abs(float(original_duration) - float(output_duration)) > MAX_DURATION_DIFFERENCE_SECONDS:
        raise CleanError(f"duration changed from {original_duration}s to {output_duration}s")


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def partial_path(target: Path) -> Path:
    return target.with_name(f".{target.name}.partial")


def format_size(size: int) -> str:
    if size < 1024**3:
        return f"{size / 1024**2:.1f} MiB"
    return f"{size / 1024**3:.2f} GiB"


def ffmpeg_command(input: Path, output: Path, codec_args: list[str]) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        # Only errors are printed, the progress is parsed from stdout.
        "-v",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-i",
        str(input),
        "-map",
        "0",
        "-c",
        "copy",
        *codec_args,
        str(output),
    ]


def print_counts(title: str, counts: Counter[str]) -> None:
    print(f"  {title}:")
    # Sorted by name instead of count, so that the output of different runs can be diffed.
    for name, count in sorted(counts.items()):
        print(f"    {name:<12} {count:>6}")


def local_path(location: str) -> Path:
    if "://" not in location:
        return Path(location)
    path = gvfs_local_path(location)
    if path is None:
        # Asks for credentials in the terminal if the server needs them.
        subprocess.run(["gio", "mount", location], check=True)
        path = gvfs_local_path(location)
    if path is None:
        raise SystemExit(f"Could not find a local path for {location}")
    return path


def gvfs_local_path(url: str) -> Path | None:
    result = subprocess.run(["gio", "info", url], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("local path: "):
            return Path(line.removeprefix("local path: "))
    return None


def probe(path: Path) -> ProbeResult:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return ProbeResult.model_validate_json(result.stdout)


def codecs_of_type(streams: list[Stream], codec_type: str) -> list[str]:
    return [
        stream.codec_name
        for stream in streams
        if stream.codec_type == codec_type and not stream.disposition.attached_pic
    ]


def raise_keyboard_interrupt(signum: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    # Clean up after `kill` the same way as after Ctrl+C.
    signal.signal(signal.SIGTERM, raise_keyboard_interrupt)

    app()
