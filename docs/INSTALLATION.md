# Installation

## Requirements

- Linux VPS with systemd.
- Python 3.11 or newer (uses the standard-library `tomllib` module).
- Git and rsync.
- SSH access for the dedicated `deploy` user.
- Node.js/npm on the VPS only for source-mode Node builds.

## Install the manager

```bash
git clone https://github.com/orelkrylatiy/deploy-infrastructure.git
cd deploy-infrastructure
sudo bash scripts/install.sh
```

The installer:
- checks Python, Git and rsync;
- creates the `deploy` system account if absent;
- clones/updates the manager into `/opt/deploy-manager`;
- installs the `deploy-manager` command;
- creates the standard project, incoming, config and log directories.

It does **not** create SSH keys, open firewall ports, configure Nginx, issue TLS certificates or create application-specific systemd units.

## Configure SSH for GitHub Actions

Create a dedicated key pair outside the repository. Add the public key to:

```text
/home/deploy/.ssh/authorized_keys
```

Ensure ownership and permissions:

```bash
sudo install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

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

The update script fast-forwards the manager's Git checkout and compiles the Python package. It does not alter project releases or project configuration.

## Uninstall

There is intentionally no automatic destructive uninstall script in this initial version. Remove the command and installation directory manually only after reviewing what is still in use. Project releases, shared data, configs and logs are kept separately.
