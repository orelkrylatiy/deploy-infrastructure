# Service deployments

A service is an application that must run as a process (for example a Node.js SSR server or API). The manager switches `current`, restarts the configured systemd unit, checks that it is active and optionally calls an HTTP health endpoint.

## systemd unit

A service unit should run as the unprivileged `deploy` user and use the stable `current` path. Example: `examples/systemd/example-app.service`.

Install/edit the unit as root, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now example-app.service
```

Do not make the service run as root unless there is a specific, reviewed requirement.

## Narrow sudo permissions

The deploy user needs permission to restart/check/stop only the configured unit. Create a sudoers drop-in with `visudo` and replace the sample unit name:

```sudoers
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart example-app.service, /usr/bin/systemctl is-active example-app.service, /usr/bin/systemctl stop example-app.service
```

Confirm the actual `systemctl` path with `command -v systemctl`. Do not grant unrestricted `sudo` to the deploy user.

The manager invokes `sudo -n`, so it fails rather than prompting for a password.

## Artifact mode

The uploaded `payload/` must be a complete runtime tree. The example Node workflow builds the app, copies runtime files and installs production dependencies into the artifact. Adjust packaging for the actual framework. For Next.js standalone output, for example, package the standalone server and the required static/public assets exactly as required by the app's runtime layout.

## Source mode

The VPS runs the configured `build_commands` as the deploy user. Install the required language runtime/package manager on the VPS. Keep production secrets out of source control and out of build logs.

## Health checks and rollback

Prefer a local health endpoint such as `http://127.0.0.1:3000/health`. It is checked after systemd restart. If restart or health check fails, the manager restores the previous `current` symlink and attempts to restart the previous version.

A code rollback does not undo database migrations or external side effects. Use backward-compatible database migrations and independent backups.
