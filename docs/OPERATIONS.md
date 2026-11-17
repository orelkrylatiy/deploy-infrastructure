# Operations checklist

## Before the first deployment

- [ ] Run `sudo bash scripts/preflight.sh` and resolve all blocking checks.
- [ ] Install the manager on the VPS.
- [ ] Confirm Python 3.11+, Git and rsync are installed.
- [ ] Add the dedicated deploy user's SSH public key with the OpenSSH `restrict` option and verify file ownership/modes.
- [ ] Verify the SSH host key and store it in GitHub Actions secrets.
- [ ] Add a root-owned TOML config for the project.
- [ ] Run `deploy-manager init <project>`.
- [ ] Configure Nginx or the systemd unit independently.
- [ ] For services, grant only the configured unit's restart/is-active/stop commands through sudoers.
- [ ] Configure a real health-check URL if possible.
- [ ] Confirm shared data and backups are planned.

## After deployment

```bash
deploy-manager status <project>
deploy-manager releases <project>
deploy-manager logs <project> --lines 200
```

Confirm the active release and test the site from outside the VPS. For services, confirm systemd reports active and the health endpoint returns success.

## Recovery

If a deployment fails after the symlink switch, the manager attempts an automatic rollback. Inspect GitHub Actions logs and the server-side log before retrying.

For a manual rollback:

```bash
deploy-manager rollback <project>
```

If rollback itself fails, inspect the current symlink, the systemd journal and Nginx/application logs before making further changes. Do not delete release directories manually while a deployment is running.

## Backups

Back up `/etc/deploy-manager/` and each project's `shared/` directory. Release directories can generally be recreated from source/artifacts, but databases and uploads cannot. Use database-aware backup methods for live databases.
