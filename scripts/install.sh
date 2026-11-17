#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/orelkrylatiy/deploy-infrastructure.git"
INSTALL_DIR="/opt/deploy-manager"
DEPLOY_USER="deploy"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

for command in git python3 rsync; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command not found: $command" >&2
    exit 1
  }
done

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || {
  echo "Python 3.11 or newer is required." >&2
  exit 1
}

if ! getent passwd "$DEPLOY_USER" >/dev/null; then
  useradd --system --create-home --home-dir "/home/$DEPLOY_USER" --shell /bin/bash "$DEPLOY_USER"
  echo "Created system user: $DEPLOY_USER"
fi

if [[ -L "$INSTALL_DIR" ]]; then
  echo "Refusing to use a symlink as the installation directory: $INSTALL_DIR" >&2
  exit 1
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  if [[ -n "$(git -C "$INSTALL_DIR" status --porcelain)" ]]; then
    echo "Refusing to update a manager checkout with local changes: $INSTALL_DIR" >&2
    exit 1
  fi
  git -C "$INSTALL_DIR" fetch origin
  git -C "$INSTALL_DIR" checkout main
  git -C "$INSTALL_DIR" pull --ff-only origin main
else
  if [[ -e "$INSTALL_DIR" ]]; then
    echo "Refusing to overwrite existing non-Git path: $INSTALL_DIR" >&2
    exit 1
  fi
  git clone --branch main "$REPO_URL" "$INSTALL_DIR"
fi

python3 -m compileall -q "$INSTALL_DIR/deploy_manager" "$INSTALL_DIR/tests"
(
  cd "$INSTALL_DIR"
  python3 -m unittest discover -s tests -v
)

chown -R root:root "$INSTALL_DIR"
find "$INSTALL_DIR" -type d -exec chmod 755 {} +
find "$INSTALL_DIR" -type f -exec chmod 644 {} +
chmod 755 "$INSTALL_DIR/bin/deploy-manager"

MANAGER_LINK="/usr/local/bin/deploy-manager"
if [[ -e "$MANAGER_LINK" && ! -L "$MANAGER_LINK" ]]; then
  echo "Refusing to replace an existing non-symlink command: $MANAGER_LINK" >&2
  exit 1
fi
if [[ -L "$MANAGER_LINK" && "$(readlink -f "$MANAGER_LINK")" != "$INSTALL_DIR/bin/deploy-manager" ]]; then
  echo "Refusing to replace an existing command symlink: $MANAGER_LINK" >&2
  exit 1
fi
ln -sfn "$INSTALL_DIR/bin/deploy-manager" "$MANAGER_LINK"

DEPLOY_HOME="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"
DEPLOY_GROUP="$(id -gn "$DEPLOY_USER")"
if [[ -z "$DEPLOY_HOME" || "$DEPLOY_HOME" != /* ]]; then
  echo "Could not determine a valid home directory for $DEPLOY_USER" >&2
  exit 1
fi
install -d -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" -m 0700 "$DEPLOY_HOME/.ssh"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" -m 0755 /var/www/projects
install -d -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" -m 0755 /var/lib/deploy-manager/incoming
install -d -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" -m 0755 /var/log/deploy-manager
install -d -o root -g "$DEPLOY_GROUP" -m 0750 /etc/deploy-manager
install -d -o root -g "$DEPLOY_GROUP" -m 0750 /etc/deploy-manager/projects

echo
echo "Deployment Manager installed."
echo "Binary: /usr/local/bin/deploy-manager"
echo "Project configs: /etc/deploy-manager/projects/"
echo "SSH user: $DEPLOY_USER"
echo
echo "Next: add your GitHub Actions public key to $DEPLOY_HOME/.ssh/authorized_keys,"
echo "create a project TOML config, and grant narrowly-scoped systemctl sudo rights for services."
