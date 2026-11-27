# Restores the latest snapshot of each tag from the restic repository on sirius.
# Use as: uv run scripts/restore-from-sirius.py <target-dir>

import getpass
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

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


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: uv run scripts/restore-from-sirius.py <target-dir>")
    target = Path(sys.argv[1])

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

    env = os.environ | {
        "RESTIC_REPOSITORY": polaris_vars.backup_repository,
        "RESTIC_REST_USERNAME": "polaris",
        "RESTIC_REST_PASSWORD": shared_vault.vault_sirius_rest_server_polaris_login,
        "RESTIC_PASSWORD": polaris_vault.vault_restic_sirius_password,
    }

    result = subprocess.run(
        ["restic", "snapshots", "--json"], env=env, stdout=subprocess.PIPE, text=True, check=True
    )
    snapshots = TypeAdapter(list[Snapshot]).validate_json(result.stdout)
    # Later snapshots replace earlier ones with the same tag.
    latest: dict[str, Snapshot] = {}
    for snapshot in sorted(snapshots, key=lambda s: s.time):
        for tag in snapshot.tags:
            latest[tag] = snapshot

    for tag, snapshot in sorted(latest.items()):
        print(f"Restoring {tag} from {snapshot.time}", flush=True)
        # Restores the content of the backed up directory without its full path.
        source = f"{snapshot.id}:{snapshot.paths[0]}"
        subprocess.run(
            ["restic", "restore", source, "--target", target / tag, "--verify"],
            env=env,
            check=True,
        )


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
    main()
