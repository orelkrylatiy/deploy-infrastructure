# Deploy Infrastructure

A small, self-hosted deployment manager for static websites and long-running services.

It uses Python 3.11+, SSH, rsync, release directories, an atomic `current` symlink, optional shared data, HTTP health checks and rollback. It has no daemon, web panel, Docker or third-party Python runtime dependencies.

## Deployment matrix

Two independent choices create four deployment modes:

| Application | Delivery | Where build happens | Typical use |
|---|---|---|---|
| Static | Artifact | CI runner | Vite/React/Vue/HTML build uploaded as `dist/` |
| Static | Source | VPS | Source uploaded; configured build commands create `dist/` |
| Service | Artifact | CI runner | Prepared Node.js/Python/etc. runtime bundle |
| Service | Source | VPS | Source uploaded; configured build commands run on VPS |

The manager itself is one program. The selected mode is defined by each project's TOML file on the VPS.

## Install on a VPS

Requirements: Linux with systemd, Python 3.11+, Git and rsync. For source deployments, install the project's build tools (for example Node.js/npm) on the VPS.

```bash
git clone https://github.com/orelkrylatiy/deploy-infrastructure.git
cd deploy-infrastructure
sudo bash scripts/install.sh
```

The installer creates (if needed) the restricted `deploy` system account and standard directories. It does not configure SSH keys, Nginx, DNS, TLS or application-specific systemd units.

Add the GitHub Actions public key to `/home/deploy/.ssh/authorized_keys` and set its owner/mode to `deploy:deploy` / `0700` for `.ssh` and `0600` for `authorized_keys`.

## Configure a project

Copy one of the examples from `examples/project-config/` to:

```text
/etc/deploy-manager/projects/<project-slug>.toml
```

Use a lowercase slug for the filename and GitHub variable `DEPLOY_PROJECT`. The project root is created automatically at `/var/www/projects/<project-slug>`.

Example:

```toml
[project]
type = "static"
delivery = "artifact"
keep_releases = 10
healthcheck_url = "https://www.example.com"
shared_files = []
shared_dirs = []
```

Set ownership and permissions, then initialize:

```bash
sudo chown root:deploy /etc/deploy-manager/projects/<project-slug>.toml
sudo chmod 640 /etc/deploy-manager/projects/<project-slug>.toml
sudo -u deploy deploy-manager init <project-slug>
```

## Connect a GitHub repository

Copy the appropriate workflow from `examples/github-actions/` into the site's repository as:

```text
.github/workflows/deploy.yml
```

Configure repository Actions secrets:

- `DEPLOY_HOST` — VPS hostname or IP.
- `DEPLOY_USER` — normally `deploy`.
- `DEPLOY_SSH_KEY` — private key matching the public key installed for the deploy user.
- `DEPLOY_KNOWN_HOSTS` — verified SSH host-key line(s); do not blindly trust an unverified `ssh-keyscan` result.

Configure repository Actions variables:

- `DEPLOY_PROJECT` — the project slug matching the VPS TOML filename.
- `BUILD_DIR` — optional; defaults to `dist` for static artifact.
- `NODE_VERSION` — optional; defaults to `22` in the Node examples.

The workflow builds a unique release ID from the short commit SHA, GitHub run ID and run-attempt number (so rerunning a failed Actions job gets a fresh release), uploads into a unique incoming directory and then runs:

```bash
deploy-manager deploy <project-slug> --release-id <unique-release-id>
```

## Useful commands

Run these as the `deploy` user (or with appropriate privileges):

```bash
deploy-manager --help
deploy-manager init <project>
deploy-manager status <project>
deploy-manager releases <project>
deploy-manager rollback <project>
deploy-manager logs <project> --lines 200
```

## Important operational notes

- Static Nginx document root should point to `/var/www/projects/<project>/current`.
- Service systemd units should use `/var/www/projects/<project>/current` as their working directory.
- Service deployments require narrowly scoped passwordless sudo permissions for the configured systemd unit. See `docs/SERVICE.md`.
- `shared_files` and `shared_dirs` are optional. They persist across releases; they are not a database backup system.
- The manager validates uploaded trees and rejects untrusted external/absolute symlinks. Service source builds may use the manager-created links into that project's `shared/` directory; no uploaded symlink receives this exception.
- Source build commands execute as the deploy user. Only deploy trusted repositories and do not put production secrets in the build environment.
- A rollback restores the previous code release; it does not reverse database schema migrations or external side effects.
- This is an early 0.x tool. Test it on a disposable VPS/project before using it for production traffic.

See [docs/INSTALLATION.md](docs/INSTALLATION.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the other guides in `docs/`.
