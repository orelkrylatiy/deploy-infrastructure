# Architecture

## Design model

The manager separates two independent dimensions:

1. **Application type**
   - `static`: Nginx serves files; no application process is restarted.
   - `service`: systemd manages a long-running process.
2. **Delivery mode**
   - `artifact`: CI builds/packages the release and uploads the ready-to-run files.
   - `source`: CI uploads source; the VPS runs the configured build commands.

This produces four supported combinations: Static + Artifact, Static + Source, Service + Artifact and Service + Source. They share the same release engine.

## Request flow

1. A GitHub Actions workflow checks out the repository.
2. It either prepares an artifact or selects the source tree.
3. It opens SSH using a pinned/verified known-hosts entry.
4. rsync uploads the files to a unique incoming path under `/var/lib/deploy-manager/incoming/<project>/<release-id>/`.
5. The workflow calls `deploy-manager deploy <project> --release-id <release-id>`.
6. The manager takes a per-project advisory lock, validates the input, prepares a release in a hidden staging directory and applies configured shared paths.
7. The prepared directory is renamed into `releases/<release-id>`.
8. The manager atomically replaces the `current` symlink.
9. For services it restarts the configured systemd unit. It then performs local and optional HTTP health checks.
10. If a post-switch check fails, the previous symlink is restored and a service is restarted on the old release.
11. On success, metadata is recorded, old releases are pruned and the incoming upload is removed.

## Filesystem layout

```text
/var/www/projects/<project>/
├── releases/
│   ├── <release-a>/
│   └── <release-b>/
├── shared/
│   ├── .env
│   └── uploads/
├── current -> releases/<active-release>
└── .deploy/
    ├── lock
    └── metadata/
        └── <release-id>.json

/var/lib/deploy-manager/incoming/<project>/<release-id>/
├── payload/     # artifact mode
└── source/      # source mode
```

The manager creates the project directories on `init` and also ensures the layout during deploy. The project root is fixed to `/var/www/projects/<slug>` in this first version to keep filesystem operations constrained.

## Shared data

A release is immutable after publication. A path listed in `shared_files` or `shared_dirs` is moved out of the first uploaded release into the project's `shared/` directory, then replaced with a relative symlink in each release.

- Shared files are created with mode 0600 when they do not exist.
- Shared directories are created with mode 0755.
- If shared data already exists, an incoming copy at that path is discarded; existing shared data wins.
- Do not list generated build output or ordinary versioned website assets as shared.
- Back up shared data separately. Shared is persistence, not backup.

## Security boundaries

- Project names and release IDs are validated before they are used in paths.
- Project roots and incoming paths are constrained to fixed roots.
- Uploaded symlinks are rejected unless they are internal symlinks in a service artifact/runtime tree.
- Build commands are argv arrays, not shell strings; they run as the unprivileged deploy user.
- The manager uses per-project `flock` locking.
- The installer keeps manager code root-owned and project data deploy-owned.
- Service restarts use non-interactive sudo. Grant only the exact configured systemd actions for each service unit.
- GitHub Actions must use a verified `DEPLOY_KNOWN_HOSTS` secret and a dedicated deploy key.

## Deliberate non-goals

No daemon, web UI, Docker, reverse-proxy configuration generator, certificate manager, database migration framework, secrets manager or backup scheduler is included. Nginx, DNS, TLS and service unit files remain explicit server configuration.
