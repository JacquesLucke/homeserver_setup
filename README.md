# Server Setup

Ansible setup for some servers.

## Homeserver

### Preparation

This requires an Ubuntu system with a user that is allowed to run sudo. Also see `inventory.ini` for connection info.

```sh
# Run on the machine controlling the server (not the server itself).

uv run ansible-playbook homeserver/setup.yml --ask-vault-pass
```

```sh
# The following commands are run on the server.

# Log-in to Tailscale.
sudo tailscale up

# Log-in to ente to enable backups.
sudo -u ente ente-cli-wrapper account login --account personal --app photos

# Create the initial SnapRAID parity in the background. Takes a few hours,
# later syncs run nightly.
sudo systemctl start --no-block snapraid-maintenance.service
journalctl -fu snapraid-maintenance.service
```

### Services

| Service        | Port   |
| -------------- | ------ |
| Landing page   | 80     |
| Copyparty      | 3923   |
| Seerr          | 5055   |
| iperf3         | 5201   |
| Paperless      | 8000   |
| Control Panel  | 8070   |
| Beszel         | 8090   |
| LedFx          | 8888   |
| Jellyfin       | 8096   |
| Home Assistant | 8123   |
| Cockpit        | 9090   |
| Audiobookshelf | 13378  |

### Internal Features

* Samba, Ente Backup, SnapRAID, mergefs, health checks, email notifications, tailscale, bluetooth speaker.

### Vault

Some private data is stored in `host_vars/homeserver/vault.yml`.

```sh
# Edit the vault data (requires the right vault password).
uv run ansible-vault edit host_vars/homeserver/vault.yml
```

See `host_vars/homeserver/vault_schema.yml` for the data stored in the vault.

### Update Steps

1. Update Ubuntu packages and reboot if needed.
    ```sh
    sudo apt update
    sudo apt full-upgrade
    sudo apt autoremove
    # Reboot if necessary.
    [ -f /var/run/reboot-required ] && sudo reboot
    ```
2. Update container images and ente cli.


## Remote Homeserver

This requires a Raspberry Pi 5 with Raspberry Pi OS.

```sh
# Run on the machine controlling the server (not the server itself).

uv run ansible-playbook remote-homeserver/setup.yml --ask-vault-pass
```

### Services

| Service        | Port   |
| -------------- | ------ |
| Landing page   | 80     |
| Home Assistant | 8123   |

### Vault

Some private data is stored in `host_vars/remote-homeserver/vault.yml`.

```sh
# Edit the vault data (requires the right vault password).
uv run ansible-vault edit host_vars/remote-homeserver/vault.yml
```

See `host_vars/remote-homeserver/vault_schema.yml` for the data stored in the vault.
