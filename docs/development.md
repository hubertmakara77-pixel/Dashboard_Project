# Development environment and tests

## Local setup

The project requires Python 3.11+. Create an environment and install dependencies:

```console
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
npm install
```

On Linux, the virtual-environment scripts are under `.venv/bin`. Importing the
application requires settings for the chosen profile, particularly amplifier gain
bounds or FTS-LS credentials. Isolated tests provide their own configuration.

## Python checks

```console
ruff format --check .
ruff check .
mypy
python -m unittest discover -s tests -v
```

`mypy` currently covers the modules with stabilized typed contracts listed in
`pyproject.toml`; it does not imply full-backend type coverage. Apply formatting
with `ruff format .`.

## Frontend checks

```console
npm run check
```

This runs ESLint for `static/js` and the Prettier check. Apply formatting with
`npm run format`. The frontend has no bundler, so also verify script order in
`templates/index.html` and run a Node syntax check when changing the file split.

## Documentation

```console
mkdocs serve
mkdocs build --strict
```

The first command starts a preview. The second validates configuration and links.
Generated output is written to the ignored `site/` directory.

## Running the application

Example FTS-LS profile in PowerShell:

```powershell
$env:DEVICE_PROFILE = 'fts-ls'
$env:SERIAL_PORT = 'COM3'
$env:FTS_LS_USERNAME = 'appadmin'
$env:FTS_LS_PASSWORD = 'secret'
python -m uvicorn app.main:app --reload
```

The production package validator accepts Linux `/dev/...` paths; a direct local
application import can use a platform-appropriate port. Never use real secrets in
files committed to Git.

## Change checklist

1. Preserve boundaries between API, core, and services.
2. Add tests for changed behavior and an invalid case.
3. Update HTTP, protocol, or configuration contracts when they change.
4. Run Ruff, mypy, tests, ESLint, Prettier, and `mkdocs build --strict`.
5. Verify both profile-specific UI paths or explicitly document the change scope.
6. For a device command, test with the simulator and target firmware.

## Adapting a firmware revision

Do not propagate raw hardware names through the application. Update only the
relevant module under `app/protocols`, then add or update an adapter test using a
verbatim device response. Canonical fields in `app/core/device_schema.py` should
change only for an intentional database/API contract migration, not for a spelling
change in firmware.
