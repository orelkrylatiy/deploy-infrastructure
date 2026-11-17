# Releases and rollback

## Commands

```bash
deploy-manager status <project>
deploy-manager releases <project>
deploy-manager rollback <project>
deploy-manager logs <project> --lines 200
```

## Release lifecycle

A deploy creates a unique hidden staging directory under `releases/`. It validates the incoming tree, prepares the artifact/source, applies shared links, and renames the prepared payload to `releases/<release-id>`.

The stable `current` symlink is replaced using a temporary symlink plus `os.replace`, on the same filesystem. The old release is not overwritten.

After switching:
- static deployments validate the release's root `index.html`;
- service deployments restart systemd and check its active state;
- if configured, both types perform an HTTP(S) health check with retries.

If a post-switch check fails, the manager attempts to restore the previous symlink. For a service, it also attempts to restart the previous version. If the first-ever deployment fails, the new `current` link is removed (and the service is stopped).

## Retention

The manager retains the newest configured number of successful releases (default 10) and always retains the current release. Failed releases are not eligible for rollback and may be removed during later cleanup.

## Limits

Rollback changes application code only. It does not revert:
- database schema changes;
- messages already sent;
- external API changes;
- uploaded/shared data;
- DNS, Nginx, TLS or systemd configuration.
