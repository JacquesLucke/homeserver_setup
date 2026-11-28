# Inspects and restores the restic repository on sirius.
# Use as:
#   uv run scripts/restore-tools.py status
#   uv run scripts/restore-tools.py restore <target-dir>

import getpass
import os
import subprocess
from datetime import date, datetime
from pathlib import Path

import typer
import yaml
from pydantic import BaseModel, ConfigDict, TypeAdapter

REPO_DIR = Path(__file__).resolve().parent.parent


class Model(BaseModel):
    # The files contain many more keys, only the ones used here are declared.
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)


class PolarisVars(Model):
    backup_repository: str


class PolarisVault(Model):
    vault_restic_sirius_password: str


class SharedVault(Model):
    vault_sirius_rest_server_polaris_login: str


class Snapshot(Model):
    id: str
    time: datetime
    paths: list[str]
    tags: list[str] = []


class Stats(Model):
    total_size: int


app = typer.Typer(no_args_is_help=True)


@app.command()
def status() -> None:
    """Show when the latest snapshot of each tag was made and how the repository grew."""
    env = restic_env()
    snapshots = load_snapshots(env)
    print("Latest snapshots:")
    for tag, snapshot in sorted(latest_by_tag(snapshots).items()):
        print(f"  {tag:<20} {snapshot.time:%Y-%m-%d %H:%M}")

    # Size of the deduplicated data referenced by all snapshots up to the end of each day.
    # Data of snapshots that have been removed already is not included.
    print("Repository size:")
    days: dict[date, list[str]] = {}
    ids: list[str] = []
    for snapshot in snapshots:
        ids.append(snapshot.id)
        days[snapshot.time.date()] = list(ids)
    previous_size = 0
    for day, day_ids in days.items():
        result = subprocess.run(
            ["restic", "stats", "--mode", "raw-data", "--json", *day_ids],
            env=env,
            stdout=subprocess.PIPE,
            text=True,
            check=True,
        )
        size = Stats.model_validate_json(result.stdout).total_size
        growth = format_size(size - previous_size)
        print(f"  {day}  {format_size(size):>10}  (+{growth})", flush=True)
        previous_size = size


@app.command()
def restore(target: Path) -> None:
    """Restore the latest snapshot of each tag into the target directory."""
    env = restic_env()
    snapshots = load_snapshots(env)
    for tag, snapshot in sorted(latest_by_tag(snapshots).items()):
        print(f"Restoring {tag} from {snapshot.time}", flush=True)
        # Restores the content of the backed up directory without its full path.
        source = f"{snapshot.id}:{snapshot.paths[0]}"
        subprocess.run(
            ["restic", "restore", source, "--target", target / tag, "--verify"],
            env=env,
            check=True,
        )


def restic_env() -> dict[str, str]:
    password = getpass.getpass("Vault password: ")
    polaris_vars = PolarisVars.model_validate(
        yaml.safe_load((REPO_DIR / "host_vars/polaris/vars.yml").read_text())
    )
    polaris_vault = PolarisVault.model_validate(
        read_vault(REPO_DIR / "host_vars/polaris/vault.yml", password)
    )
    shared_vault = SharedVault.model_validate(
        read_vault(REPO_DIR / "group_vars/all/vault.yml", password)
    )
    return dict(os.environ) | {
        "RESTIC_REPOSITORY": polaris_vars.backup_repository,
        "RESTIC_REST_USERNAME": "polaris",
        "RESTIC_REST_PASSWORD": shared_vault.vault_sirius_rest_server_polaris_login,
        "RESTIC_PASSWORD": polaris_vault.vault_restic_sirius_password,
    }


def load_snapshots(env: dict[str, str]) -> list[Snapshot]:
    # Sorted by time, oldest first.
    result = subprocess.run(
        ["restic", "snapshots", "--json"], env=env, stdout=subprocess.PIPE, text=True, check=True
    )
    snapshots = TypeAdapter(list[Snapshot]).validate_json(result.stdout)
    return sorted(snapshots, key=lambda s: s.time)


def latest_by_tag(snapshots: list[Snapshot]) -> dict[str, Snapshot]:
    # Expects snapshots sorted by time, later snapshots replace earlier ones with the same tag.
    latest: dict[str, Snapshot] = {}
    for snapshot in snapshots:
        for tag in snapshot.tags:
            latest[tag] = snapshot
    return latest


def format_size(size: int) -> str:
    value = float(size)
    for unit in ["B", "KiB", "MiB", "GiB"]:
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def read_vault(path: Path, password: str) -> object:
    result = subprocess.run(
        ["ansible-vault", "view", "--vault-password-file", "/dev/stdin", path],
        input=password,
        stdout=subprocess.PIPE,
        text=True,
        check=True,
    )
    return yaml.safe_load(result.stdout)


if __name__ == "__main__":
    app()
