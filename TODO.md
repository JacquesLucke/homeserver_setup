# TODO

* [ ] Backup app data to storage.
* [ ] Setup snapraid.
* [ ] Pin container versions.
* [ ] If Ente export fails, there is no info.
* [ ] Extract common variables like `homeserver_user`, `storage_path`.
* [ ] Have separate samba for full storage, media, and internal ssd.
* [ ] Remove one-off migrations like recursive `chown` if possible.
* [ ] Every apt task has update_cache: true. Use cache_valid_time: 3600, or refresh once at the start, to make runs faster.
* [ ] Give ente and audiobookshelf users specific UIDs/GIDs.
