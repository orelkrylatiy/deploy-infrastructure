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

if [[ -d "$INSTALL_DIR/.git" ]]; then
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

chown -R root:root "$INSTALL_DIR"
find "$INSTALL_DIR" -type d -exec chmod 755 {} +
find "$INSTALL_DIR" -type f -exec chmod 644 {} +
chmod 755 "$INSTALL_DIR/bin/deploy-manager"

ln -sfn "$INSTALL_DIR/bin/deploy-manager" /usr/local/bin/deploy-manager

install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0755 /var/www/projects
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0755 /var/lib/deploy-manager/incoming
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" -m 0755 /var/log/deploy-manager
install -d -o root -g "$DEPLOY_USER" -m 0750 /etc/deploy-manager
install -d -o root -g "$DEPLOY_USER" -m 0750 /etc/deploy-manager/projects

echo
echo "Deployment Manager installed."
echo "Binary: /usr/local/bin/deploy-manager"
echo "Project configs: /etc/deploy-manager/projects/"
echo "SSH user: $DEPLOY_USER"
echo
echo "Next: add your GitHub Actions public key to /home/$DEPLOY_USER/.ssh/authorized_keys,"
echo "create a project TOML config, and grant narrowly-scoped systemctl sudo rights for services."
