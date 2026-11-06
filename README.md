```sh
# Run on the machine controlling the server (not the server itself).
uv run ansible-playbook setup.yml
```

```sh
# The following commands are run on the server.

# Log-in to Tailscale.
sudo tailscale up

# Log-in to ente to enable backups.
sudo -u ente ente-cli-wrapper account login --account personal --app photos
```

## Services

| Service        | Port   |
| -------------- | ------ |
| Jellyfin       | 8096   |
| Audiobookshelf | 13378  |
| Beszel         | 8090   |
| Samba          | -      |
| Ente Backup    | -      |

## Private Data

Some private keys are stored in `group_vars/homeserver/vault.yml`:
* `vault_samba_password`: My password to access the storage through samba.
* `vault_beszel_agent_key`, `vault_beszel_agent_token`: Used to connect the Beszel agent to the hub. This has to be retrieved from the Beszel hub once it is running.
