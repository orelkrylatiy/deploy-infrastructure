#!/usr/bin/env bash
# Read-only checks to run before installing Deploy Infrastructure on a VPS.
set -uo pipefail

INSTALL_DIR="/opt/deploy-manager"
MANAGER_LINK="/usr/local/bin/deploy-manager"
DEPLOY_USER="deploy"
failures=0
warnings=0

ok()   { printf '  [OK]   %s\n' "$1"; }
warn() { printf '  [WARN] %s\n' "$1"; warnings=$((warnings + 1)); }
fail() { printf '  [FAIL] %s\n' "$1" >&2; failures=$((failures + 1)); }

printf 'Deploy Infrastructure VPS preflight (read-only)\n'
printf 'Host: %s\n\n' "$(hostname 2>/dev/null || printf unknown)"

if [[ "${EUID}" -eq 0 ]]; then
  ok "Running as root"
else
  fail "Run with sudo: sudo bash scripts/preflight.sh"
fi

if [[ "$(uname -s)" == "Linux" ]]; then
  ok "Linux operating system"
else
  fail "A Linux VPS is required"
fi

for command in git python3 rsync; do
  if command -v "$command" >/dev/null 2>&1; then
    ok "$command is installed"
  else
    fail "$command is missing"
  fi
done

if command -v python3 >/dev/null 2>&1; then
  python_version="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null || true)"
  if python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
    ok "Python $python_version (3.11+)"
  else
    fail "Python 3.11+ is required (found ${python_version:-unknown})"
  fi
fi

if command -v systemctl >/dev/null 2>&1 && systemctl --version >/dev/null 2>&1; then
  if [[ -d /run/systemd/system ]]; then
    ok "systemd is installed and running"
  else
    fail "systemd runtime is not active; this manager requires a systemd VPS"
  fi
else
  fail "systemctl is missing; this manager requires systemd"
fi

if command -v sshd >/dev/null 2>&1; then
  if sshd -t >/dev/null 2>&1; then
    ok "OpenSSH server configuration passes sshd -t"
  else
    fail "OpenSSH server configuration is invalid (sshd -t failed)"
  fi
else
  fail "OpenSSH server (sshd) is missing; GitHub Actions needs SSH access"
fi

if command -v sudo >/dev/null 2>&1; then
  ok "sudo is installed"
else
  warn "sudo is missing; service deployments need non-interactive sudo for their one configured systemd unit"
fi

if getent passwd "$DEPLOY_USER" >/dev/null 2>&1; then
  passwd_entry="$(getent passwd "$DEPLOY_USER")"
  IFS=: read -r _ _ deploy_uid _ _ deploy_home deploy_shell <<< "$passwd_entry"
  if [[ "$deploy_home" == /* && -d "$deploy_home" ]]; then
    ok "Existing $DEPLOY_USER account has a valid home directory"
  else
    fail "Existing $DEPLOY_USER account has a missing or non-absolute home directory"
  fi
  case "$deploy_shell" in
    */nologin|*/false)
      fail "Existing $DEPLOY_USER account has a non-interactive shell; SSH remote commands will not work"
      ;;
    *)
      ok "Existing $DEPLOY_USER account permits SSH command execution"
      ;;
  esac
  if [[ -n "${deploy_uid:-}" && -e "$deploy_home/.ssh/authorized_keys" ]]; then
    ssh_dir_owner="$(stat -c '%u' "$deploy_home/.ssh" 2>/dev/null || printf unknown)"
    ssh_dir_mode="$(stat -c '%a' "$deploy_home/.ssh" 2>/dev/null || printf unknown)"
    key_owner="$(stat -c '%u' "$deploy_home/.ssh/authorized_keys" 2>/dev/null || printf unknown)"
    key_mode="$(stat -c '%a' "$deploy_home/.ssh/authorized_keys" 2>/dev/null || printf unknown)"
    if [[ "$ssh_dir_owner" == "$deploy_uid" && "$ssh_dir_mode" == "700" && "$key_owner" == "$deploy_uid" && "$key_mode" == "600" ]]; then
      ok "Existing .ssh directory and authorized_keys ownership/permissions are correct"
    else
      warn "Set .ssh to deploy-owned mode 700 and authorized_keys to deploy-owned mode 600"
    fi
  else
    warn "No authorized_keys file found for $DEPLOY_USER yet; add the dedicated GitHub Actions public key after installation"
  fi
else
  ok "The installer will create the $DEPLOY_USER system account"
fi

for path in \
  "$INSTALL_DIR" \
  "$MANAGER_LINK" \
  /var/www/projects \
  /var/lib/deploy-manager \
  /var/lib/deploy-manager/incoming \
  /var/log/deploy-manager \
  /etc/deploy-manager \
  /etc/deploy-manager/projects; do
  if [[ -L "$path" ]]; then
    fail "Managed path must not be a symlink: $path"
  fi
done

if [[ -e "$INSTALL_DIR" ]]; then
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    if [[ -n "$(git -C "$INSTALL_DIR" status --porcelain 2>/dev/null)" ]]; then
      fail "Existing manager checkout has local changes: $INSTALL_DIR"
    else
      ok "Existing manager checkout is clean"
      current_branch="$(git -C "$INSTALL_DIR" branch --show-current 2>/dev/null || true)"
      if [[ "$current_branch" != "main" ]]; then
        warn "Installer will switch the clean manager checkout from ${current_branch:-detached HEAD} to main"
      fi
    fi
  else
    fail "$INSTALL_DIR exists but is not a Git checkout; installer will refuse to overwrite it"
  fi
fi

if [[ -e "$MANAGER_LINK" || -L "$MANAGER_LINK" ]]; then
  if [[ -L "$MANAGER_LINK" ]]; then
    link_target="$(readlink -f "$MANAGER_LINK" 2>/dev/null || true)"
    if [[ "$link_target" == "$INSTALL_DIR/bin/deploy-manager" ]]; then
      ok "Existing deploy-manager command points to the managed installation"
    else
      fail "Existing $MANAGER_LINK points somewhere unexpected: ${link_target:-unresolved}"
    fi
  else
    fail "$MANAGER_LINK exists and is not a symlink; installer will not replace it"
  fi
fi

for mount in /opt /var; do
  if [[ -d "$mount" ]] && command -v df >/dev/null 2>&1; then
    available_kb="$(df -Pk "$mount" 2>/dev/null | awk 'NR == 2 {print $4}')"
    if [[ "$available_kb" =~ ^[0-9]+$ ]] && (( available_kb < 524288 )); then
      warn "Less than 512 MiB is free on the filesystem containing $mount"
    fi
  fi
done

printf '\n'
if (( failures > 0 )); then
  printf 'Preflight FAILED: %d blocking issue(s), %d warning(s). No changes were made.\n' "$failures" "$warnings" >&2
  exit 1
fi

if (( warnings > 0 )); then
  printf 'Preflight passed with %d warning(s). Review them before installation. No changes were made.\n' "$warnings"
else
  printf 'Preflight passed. No changes were made.\n'
fi
