# Git-installable Dash fork

This branch includes generated runtime files so Python package managers can
install the fork directly from Git without Node.js or a local Dash checkout.

- Feature branch: `feat/latest-callback-execution`
- Source commit: `b9716c2191b989a3be4d56d2eff1349182785a05`
- Runtime branch: `build/latest-callback-execution`

Only the feature branch is intended as the basis for a future upstream change.
The runtime branch adds built DCC, HTML, Table, React dependencies and renderer
bundles. It excludes Python caches and Node dependencies.

The files were built with Node.js 24 using Dash's component build process and
renderer webpack build. The source passed 50 callback unit tests and nine browser
tests, with four intentional unit-test skips. FLARE's thermal annotation tests
also passed against the local source build.

The unchanged JupyterLab extension archive comes from the published Dash
4.5.0rc2 wheel (SHA256
`1fc955394492490d6ae17f22b25753eacb6e8a4c67e38da2352da9c89bbf4a78`).
Its source in `@plotly/dash-jupyterlab` is identical to the upstream 4.5.0rc2 tag.

Consumers should pin the runtime commit SHA, rather than a moving branch, for
repeatable installations. Rebuild and publish a new runtime commit when the
feature source changes. The bundled files must not be copied into the upstream
feature commit.
