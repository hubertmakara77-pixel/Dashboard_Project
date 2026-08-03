# Backup and data migration

## What to copy

A minimal recoverable backup includes:

- `/etc/amp-panel/amp-panel.env` — configuration and secrets;
- `<data-dir>/measurements.db` — measurements and snapshots;
- `<data-dir>/persisted_state.json` — dashboard settings and access list;
- optionally `/var/log/amp-panel/amp-panel.log*` — alarm and audit history.

Store backups containing secrets in encrypted storage with restricted access.
After restoration, preserve mode `0600` for the configuration and state files.

## Consistent offline backup

The simplest safe procedure is:

```console
sudo amp-panel stop
sudo sqlite3 /var/lib/amp-panel/measurements.db 'PRAGMA wal_checkpoint(TRUNCATE); PRAGMA integrity_check;'
sudo cp -a /etc/amp-panel/amp-panel.env /secure/destination/
sudo cp -a /var/lib/amp-panel/measurements.db /secure/destination/
sudo cp -a /var/lib/amp-panel/persisted_state.json /secure/destination/
sudo amp-panel start
sudo amp-panel doctor
```

`PRAGMA integrity_check` must return `ok`. If `persisted_state.json` does not yet
exist, the application creates it on the first persistent setting change.

## Data-directory migration

```console
sudo amp-panel data-dir migrate /mnt/amp-panel-data
```

The tool:

1. validates the path and checks the destination for conflicting files;
2. stops the application;
3. checkpoints WAL and verifies source integrity;
4. copies the database and state through temporary files;
5. verifies the copied database;
6. updates configuration and starts services.

The old copy remains at the source and is not deleted automatically. Remove it
only after verifying the new location and creating an independent backup.

`data-dir use PATH` does not copy data; it only switches the application to an
existing directory. Use it only when the destination already contains the
correct, verified copy.

## Restoration

1. Install a compatible package version and stop the service.
2. Restore configuration and data to their target paths.
3. Set data ownership to the `amp-panel` service user/group and restore package
   file permissions.
4. Run `sqlite3 ... 'PRAGMA integrity_check;'`.
5. Start the service, run `amp-panel doctor`, and log in as an Administrator.
6. Verify the profile, serial port, RADIUS, last setpoint, and new history records.

Do not restore a `measurements.db-wal` from a different point in time than the
main database. For an online backup, treat `db`, `db-wal`, and `db-shm` as one set
or use SQLite's backup mechanism.
