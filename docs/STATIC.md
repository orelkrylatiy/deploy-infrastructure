# Static deployments

Static projects are served directly by Nginx. The manager never restarts Nginx during a deploy.

## Artifact mode

Use `examples/github-actions/static-artifact.yml`. GitHub Actions runs the build and uploads the contents of `BUILD_DIR` (default `dist`) to the release incoming directory. The directory must contain `index.html` at its root.

This is the recommended mode for ordinary Vite/React/Vue/HTML landing pages. The VPS does not need Node.js.

## Source mode

Use `examples/github-actions/static-source.yml`. It uploads the repository source. The VPS runs `project.build_commands` and publishes `project.build_output` (default examples use `dist`).

Install the relevant runtime/build tools on the VPS first. Commands run as the deploy user, without a shell, in the temporary release workspace. Source mode uses more VPS CPU, memory and disk than artifact mode.

## Nginx

Configure Nginx's document root once to the stable symlink:

```nginx
root /var/www/projects/<slug>/current;
index index.html;
```

The symlink changes atomically; Nginx does not need a reload for each release. Keep DNS and TLS configuration outside this tool.

## SPA routing

For a client-side router, use a fallback such as:

```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

For a conventional multi-page site, use the appropriate `try_files` behavior instead.
