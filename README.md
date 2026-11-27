# Server Setup

Ansible setup for some servers. Each server is named after a star.

Connection info is in [inventory.ini](inventory.ini).

## Commands

```sh
# Run on the machine controlling the server (not the server itself).

# Updates can be deployed to each machine separately.
uv run ansible-playbook polaris/setup.yml --ask-vault-pass
uv run ansible-playbook sirius/setup.yml --ask-vault-pass

# Edit vault commands.
uv run ansible-vault edit host_vars/polaris/vault.yml
uv run ansible-vault edit host_vars/sirius/vault.yml
uv run ansible-vault edit group_vars/all/vault.yml
```

## Polaris

* System: Ubuntu Server
* Variables: [vars.yml](host_vars/polaris/vars.yml)
* Vault: [vault.yml](host_vars/polaris/vault.yml) and [vault_schema.yml](host_vars/polaris/vault_schema.yml)

## Sirius

* System: Raspberry Pi 5 with Raspberry Pi OS
* Variables: [vars.yml](host_vars/sirius/vars.yml)
* Vault: [vault.yml](host_vars/sirius/vault.yml) and [vault_schema.yml](host_vars/sirius/vault_schema.yml)

## Initial Setup

Besides running the playbook, some services require additional manual setup.

### Tailscale

Run the following command on the server which triggers a tailscale login.
This is necessary before being able to connect to the server with tailscale.

```sh
sudo tailscale up
```

### Ente

One has to log into Ente to be able to use the CLI to e.g. do backups.

```sh
sudo -u ente ente-cli-wrapper account login --account personal --app photos
```

### Beszel

Each machine needs to connect its beszel agent to the hub. For that one has to
create an access key and token in the beszel hub UI and store it in the vault.
Then run the playbook again.

### Snapraid

Running snapraid the first time can take a long time, so better do it manually.

```sh
sudo systemctl start --no-block snapraid-maintenance.service
# See progress.
journalctl -fu snapraid-maintenance.service
```

## Updates

1. Update packages and reboot if needed..
    ```sh
    sudo apt update
    sudo apt full-upgrade
    sudo apt autoremove
    # Reboot if necessary.
    [ -f /var/run/reboot-required ] && sudo reboot
    ```
2. Update container images.
