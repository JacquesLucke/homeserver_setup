# Homeserver Setup

Ansible setup for my homeserver.

## Preparation

This requires an Ubuntu system with a user that is allowed to run sudo. Also see `inventory.ini` for the expected IP address and username.

```sh
# Run on the machine controlling the server (not the server itself).

uv run ansible-playbook setup.yml --ask-vault-pass
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

## Services

| Service        | Port   |
| -------------- | ------ |
| Jellyfin       | 8096   |
| Audiobookshelf | 13378  |
| Copyparty      | 3923   |
| Beszel         | 8090   |
| Samba          | -      |
| Ente Backup    | -      |
| SnapRAID       | -      |

## Private Data

Some private data is stored in `group_vars/homeserver/vault.yml`.

```sh
# Edit the vault data (requires the right vault password).
uv run ansible-vault edit group_vars/homeserver/vault.yml
```

Data stored in the vault:
* `vault_become_password`: The sudo password of the user on the server.
* `vault_samba_password`: My password to access the storage through samba.
* `vault_copyparty_media_accounts`: List of copyparty accounts with access to the media folder, each with a `name` and a `password_hash`. See below for how to create the hash.
* `vault_smtp_host`, `vault_smtp_user`, `vault_smtp_password`: SMTP server (with implicit TLS on port 465) and login used to send notification emails.
* `vault_notify_email`: The address that notification emails are sent to.
* `vault_beszel_agent_key`, `vault_beszel_agent_token`: Used to connect the Beszel agent to the hub. This has to be retrieved from the Beszel hub once it is running.

```sh
# Prints the hash (starting with "+") for the "name:password" typed on stdin.
# Take the <salt> from roles/copyparty/templates/copyparty.conf.j2.
docker run --rm -i copyparty/ac:1.20.26 --usernames --ah-alg argon2 --ah-salt <salt> --ah-gen -
```
