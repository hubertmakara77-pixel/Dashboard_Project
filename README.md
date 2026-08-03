# Amp Panel

Amp Panel is a local web dashboard for monitoring and controlling one of two
device profiles:

- `amplifier` — an optical amplifier with line-oriented telemetry;
- `fts-ls` — a Frequency Transfer System laser station controlled through an
  authenticated serial console.

User, administrator, and developer documentation is available in the
[`docs`](docs/index.md) directory. Key entry points:

- [quick start](docs/manual/quick-start.md),
- [operator manual](docs/manual/operator.md),
- [administrator manual](docs/manual/administrator.md),
- [Debian package installation](docs/operations/installation.md),
- [troubleshooting](docs/operations/troubleshooting.md),
- [architecture](docs/technical/architecture.md),
- [HTTP API reference](docs/technical/http-api.md).

## Previewing the documentation locally

```console
python -m pip install -r requirements-dev.txt
mkdocs serve
```

The site will be available at `http://127.0.0.1:8000`. Check the configuration
and documentation links with:

```console
mkdocs build --strict
```
