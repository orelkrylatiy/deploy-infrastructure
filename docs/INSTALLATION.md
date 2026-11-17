# Installation

## Requirements

- Linux VPS with systemd.
- Python 3.11 or newer (uses the standard-library `tomllib` module).
- Git and rsync.
- SSH access for the dedicated `deploy` user.
- Node.js 22+ and npm on the VPS for Node.js service applications in artifact or source mode.

## Install the manager

```bash
git clone https://github.com/orelkrylatiy/deploy-infrastructure.git
cd deploy-infrastructure
sudo bash scripts/preflight.sh --node-runtime  # read-only; checks Node.js 22+ and linux-x64
sudo bash scripts/install.sh
```

The preflight script is read-only: it checks Linux/systemd, Python, Git, rsync, OpenSSH, the deploy account, existing managed paths and available disk space. With `--node-runtime`, it also requires Node.js 22+, npm and the current `linux-x64` target architecture used by the Node runtime artifacts. It does not install packages or change server state.

The installer:
- checks Python, Git and rsync;
- runs the package compile check and unit tests before completing installation;
- creates the `deploy` system account if absent;
- clones/updates the manager into `/opt/deploy-manager`;
- installs the `deploy-manager` command;
- creates the standard project, incoming, config and log directories.

It does **not** create SSH keys, open firewall ports, configure Nginx, issue TLS certificates or create application-specific systemd units.

## Configure SSH for GitHub Actions

Create a dedicated Ed25519 key pair outside the repository. The installer creates the deploy user's `.ssh/` directory. Determine the deploy user's home (the default is `/home/deploy`) and append the public key to `authorized_keys`; do not overwrite other keys. Prefix the key with OpenSSH's `restrict` option:

```text
restrict ssh-ed25519 AAAA... github-actions-deploy
```

`restrict` disables port forwarding, agent forwarding, X11 forwarding and PTY allocation, but still permits the non-interactive remote commands required by the deployment workflow. Ensure `.ssh` is mode `0700` and `authorized_keys` is owned by `deploy` with mode `0600`.

Store the private key in the site's GitHub Actions secret `DEPLOY_SSH_KEY`. Store the VPS host key in `DEPLOY_KNOWN_HOSTS`; obtain and verify the host-key fingerprint through a trusted channel before adding it. Do not trust an unverified scan result.

## Add a project configuration

Copy one of the four TOML examples to `/etc/deploy-manager/projects/<slug>.toml`. Replace the sample health-check URL and, for services, the systemd unit name.

```bash
sudo chown root:deploy /etc/deploy-manager/projects/<slug>.toml
sudo chmod 640 /etc/deploy-manager/projects/<slug>.toml
sudo -u deploy deploy-manager init <slug>
```

The project directory is created automatically at `/var/www/projects/<slug>`. The manager also creates missing release/shared/metadata directories during a deployment.

## Configure Nginx for a static site

Set the Nginx document root to:

```nginx
root /var/www/projects/<slug>/current;
index index.html;
location / {
    try_files $uri $uri/ /index.html;
}
```

Adapt `try_files` for non-SPA websites. Validate and reload Nginx after editing its server block.

## Configure GitHub Actions

Copy one of the example workflows to the site's `.github/workflows/deploy.yml`. Configure these repository Actions secrets:

- `DEPLOY_HOST`
- `DEPLOY_USER` (normally `deploy`)
- `DEPLOY_SSH_KEY`
- `DEPLOY_KNOWN_HOSTS`

And this repository Actions variable:

- `DEPLOY_PROJECT` (must match the TOML filename)

Static artifact may additionally use `BUILD_DIR` and `NODE_VERSION`.

## Updating the manager

```bash
sudo bash /opt/deploy-manager/scripts/update.sh
```

The update script refuses to overwrite local changes, fast-forwards the manager's Git checkout, compiles the package and runs the unit tests. If validation fails, it restores the previous manager commit. It does not alter project releases or project configuration.

## Uninstall

There is intentionally no automatic destructive uninstall script in this initial version. Remove the command and installation directory manually only after reviewing what is still in use. Project releases, shared data, configs and logs are kept separately.
