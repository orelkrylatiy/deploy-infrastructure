#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/deploy-manager"
if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi
if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  echo "Deployment Manager is not installed at $INSTALL_DIR" >&2
  exit 1
fi

git -C "$INSTALL_DIR" fetch origin
git -C "$INSTALL_DIR" checkout main
git -C "$INSTALL_DIR" pull --ff-only origin main
python3 -m compileall -q "$INSTALL_DIR/deploy_manager"
echo "Deployment Manager updated."
