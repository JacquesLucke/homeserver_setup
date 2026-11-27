#!/usr/bin/python3
# Extracts the newest backup of each app into a staging directory and backs it up
# to sirius with restic. Extracting lets restic deduplicate between the backups.
# Each app gets its own snapshot, tagged with its name, so that a problem with one
# app doesn't block the others and the snapshots can be kept for different times.

import glob
import gzip
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
import zipfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

CONFIG_PATH = Path("/etc/backup/config.json")

# Fail when an app stopped creating backups.
MAX_AGE_DAYS = 2


class Model(BaseModel):
    # Reject unknown keys and values of the wrong type instead of converting them.
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Archive(Model):
    name: str
    # The newest file matching this glob pattern is extracted. It's a string because
    # Path.glob doesn't support absolute patterns.
    pattern: str


class Config(Model):
    staging_dir: Path
    archives: list[Archive]


class BackupError(Exception):
    pass


def main() -> None:
    config = load_config(CONFIG_PATH)

    # Start fresh so that only the newest backups end up in the snapshots.
    shutil.rmtree(config.staging_dir, ignore_errors=True)
    config.staging_dir.mkdir(mode=0o700)

    failed: list[str] = []
    for archive in config.archives:
        print(f"Backing up {archive.name}", flush=True)
        try:
            back_up_archive(archive, config.staging_dir)
        except BackupError as e:
            print(f"Backup of {archive.name} failed: {e}", file=sys.stderr, flush=True)
            failed.append(archive.name)
        except Exception:  # noqa: BLE001 - one app must not stop the others.
            print(f"Backup of {archive.name} failed:", file=sys.stderr, flush=True)
            traceback.print_exc()
            failed.append(archive.name)

    if failed:
        sys.exit(f"Backup failed for {', '.join(failed)}")


def load_config(path: Path) -> Config:
    try:
        return Config.model_validate_json(path.read_text())
    except ValidationError as e:
        sys.exit(f"Invalid config {path}: {e}")


def back_up_archive(archive: Archive, staging_dir: Path) -> None:
    newest = find_newest(archive)
    dest = staging_dir / archive.name
    data_dir = dest / "data"
    extract(newest, data_dir)

    # Home Assistant backups contain compressed archives. Encrypted ones are kept as they are.
    for inner in data_dir.glob("*.tar.gz"):
        if is_gzip(inner):
            extract(inner, inner.with_name(inner.name.removesuffix(".tar.gz")))
            inner.unlink()

    # Remember the original file name, which is needed to restore some backups.
    (dest / "source.txt").write_text(f"{newest}\n")

    result = subprocess.run(["restic-sirius", "backup", "--tag", archive.name, dest], check=False)
    if result.returncode != 0:
        raise BackupError(f"restic failed for {archive.name} with exit code {result.returncode}")


def find_newest(archive: Archive) -> Path:
    candidates = [Path(p) for p in glob.glob(archive.pattern)]
    if not candidates:
        raise BackupError(f"No backup found for {archive.name}")
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    if time.time() - newest.stat().st_mtime > MAX_AGE_DAYS * 24 * 60 * 60:
        raise BackupError(
            f"Newest backup for {archive.name} is older than {MAX_AGE_DAYS} days: {newest}"
        )
    return newest


def extract(archive: Path, dest: Path) -> None:
    if archive.name.endswith((".zip", ".audiobookshelf")):
        with zipfile.ZipFile(archive) as f:
            f.extractall(dest)
    elif archive.name.endswith((".tar", ".tar.gz")):
        with tarfile.open(archive) as f:
            f.extractall(dest, filter="data")
    else:
        raise BackupError(f"Unknown archive type: {archive}")


def is_gzip(path: Path) -> bool:
    try:
        with gzip.open(path) as f:
            f.read(1)
        return True
    except gzip.BadGzipFile:
        return False


if __name__ == "__main__":
    main()
