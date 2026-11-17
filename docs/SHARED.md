# Shared files and directories

Releases are intended to be disposable code snapshots. Data that must survive deployments belongs in the project's `shared/` directory.

Configure paths in TOML:

```toml
[project]
shared_files = [".env"]
shared_dirs = ["storage", "uploads"]
```

For each release, the manager creates a symlink at the same relative path pointing to the project's shared copy.

On the first deployment:
- If the incoming release contains the configured path, it is moved into `shared/`.
- If a shared file is absent from both places, an empty file is created with mode 0600.
- If a shared directory is absent from both places, an empty directory is created.

On later deployments, existing shared data wins. An incoming file/directory at the same configured path is not allowed to overwrite persistent data.

Use Shared for environment files, user uploads, SQLite files and other runtime state only when the application actually needs them. Ordinary website assets that are versioned with the frontend should stay in the release.

Shared is not a backup mechanism. Back up databases and user data independently. For SQLite, stop or quiesce writers or use SQLite's backup facilities before copying a live database.
