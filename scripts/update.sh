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

if [[ -n "$(git -C "$INSTALL_DIR" status --porcelain)" ]]; then
  echo "Refusing to update a manager checkout with local changes: $INSTALL_DIR" >&2
  exit 1
fi

PREVIOUS_COMMIT="$(git -C "$INSTALL_DIR" rev-parse HEAD)"
git -C "$INSTALL_DIR" fetch origin
git -C "$INSTALL_DIR" checkout main
git -C "$INSTALL_DIR" pull --ff-only origin main

if ! python3 -m compileall -q "$INSTALL_DIR/deploy_manager" "$INSTALL_DIR/tests" || ! (
  cd "$INSTALL_DIR"
  python3 -m unittest discover -s tests -v
); then
  echo "Validation failed; restoring previous manager version $PREVIOUS_COMMIT" >&2
  git -C "$INSTALL_DIR" reset --hard "$PREVIOUS_COMMIT"
  exit 1
fi

echo "Deployment Manager updated and validated."
