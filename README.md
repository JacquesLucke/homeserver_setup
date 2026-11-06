```sh
# Run on the machine controlling the server (not the server itself).
uv run ansible-playbook setup.yml
```

```sh
# The following commands are run on the server.

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
