# Server Setup

Ansible setup for some servers.

Connection info is in [inventory.ini](inventory.ini).

## Commands

```sh
# Run on the machine controlling the server (not the server itself).

# Updates can be deployed to each machine separately.
uv run ansible-playbook homeserver/setup.yml --ask-vault-pass
uv run ansible-playbook remote-homeserver/setup.yml --ask-vault-pass

# Edit vault commands.
uv run ansible-vault edit host_vars/homeserver/vault.yml
uv run ansible-vault edit host_vars/remote-homeserver/vault.yml
```

## Homeserver

* System: Ubuntu Server
* Variables: [vars.yml](host_vars/homeserver/vars.yml)
* Vault: [vault.yml](host_vars/homeserver/vault.yml) and [vault_schema.yml](host_vars/homeserver/vault_schema.yml)

### Initial Setup Commands

```sh
# Log-in to Tailscale.
sudo tailscale up

# Log-in to ente to enable backups.
sudo -u ente ente-cli-wrapper account login --account personal --app photos

# Create the initial SnapRAID parity in the background. Takes a few hours,
# later syncs run nightly.
sudo systemctl start --no-block snapraid-maintenance.service
journalctl -fu snapraid-maintenance.service
```

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

* System: Raspberry Pi 5 with Raspberry Pi OS
* Variables: [vars.yml](host_vars/remote-homeserver/vars.yml)
* Vault: [vault.yml](host_vars/remote-homeserver/vault.yml) and [vault_schema.yml](host_vars/remote-homeserver/vault_schema.yml)

### Initial Setup Commands

```sh
# Log-in to Tailscale.
sudo tailscale up
```

Afterwards, add the system in the Beszel hub on the homeserver, store its key and token in the vault and run the playbook again.

### Update Steps

1. Update packages and reboot if needed. Unattended upgrades don't cover packages from the Raspberry Pi repository (kernel, firmware, ...).
    ```sh
    sudo apt update
    sudo apt full-upgrade
    sudo apt autoremove
    # Reboot if necessary.
    [ -f /var/run/reboot-required ] && sudo reboot
    ```
2. Update container images.
