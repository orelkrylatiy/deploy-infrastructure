# Project configuration

Each project has one root-owned TOML file:

```text
/etc/deploy-manager/projects/<project-slug>.toml
```

The filename is the project slug. The corresponding project root is always:

```text
/var/www/projects/<project-slug>
```

## Static + Artifact

```toml
[project]
type = "static"
delivery = "artifact"
keep_releases = 10
healthcheck_url = "https://www.example.com"
shared_files = []
shared_dirs = []
```

The incoming `payload/` directory must contain `index.html` at its root.

## Static + Source

```toml
[project]
type = "static"
delivery = "source"
keep_releases = 10
healthcheck_url = "https://www.example.com"
build_commands = [["npm", "ci"], ["npm", "run", "build"]]
build_output = "dist"
build_timeout_seconds = 1800
shared_files = []
shared_dirs = []
```

The incoming `source/` directory is copied to a staging workspace. Commands run in order without a shell. The configured build output directory is then published as the release root and must contain `index.html`.

## Service + Artifact

```toml
[project]
type = "service"
delivery = "artifact"
keep_releases = 10
healthcheck_url = "http://127.0.0.1:3000/health"
shared_files = [".env"]
shared_dirs = ["storage", "uploads"]

[service]
unit = "example-app.service"
```

The uploaded `payload/` is the application runtime directory. The configured systemd unit must start the application from the project's `current` path.

## Service + Source

```toml
[project]
type = "service"
delivery = "source"
keep_releases = 10
healthcheck_url = "http://127.0.0.1:3000/health"
build_commands = [["npm", "ci"], ["npm", "run", "build"]]
build_timeout_seconds = 1800
shared_files = [".env"]
shared_dirs = ["storage", "uploads"]

[service]
unit = "example-app.service"
```

The source is copied into a staging workspace, commands are executed there, and the whole workspace becomes the release.

## Fields

- `type`: `static` or `service`.
- `delivery`: `artifact` or `source`.
- `keep_releases`: 2–100; defaults to 10.
- `healthcheck_url`: optional HTTP(S) URL checked after switching.
- `build_commands`: array of argv arrays; never a shell string.
- `build_output`: relative output directory for Static + Source; defaults to `dist`.
- `build_timeout_seconds`: per-command timeout, 30–7200; defaults to 1800.
- `shared_files`, `shared_dirs`: optional relative paths to persist between releases. Static projects cannot configure `shared_files` because they live under a public web root; use static shared directories only for intentionally public content.
- `service.unit`: required for Service projects; must end in `.service`.

Project names must be lowercase slugs. Shared paths must be relative, must not contain `.` or `..` segments, and must not overlap.
