# Optical equipment control panel

The optical equipment control panel is a local web dashboard for monitoring and controlling one of two
device profiles:

- `amplifier` — an optical amplifier with line-oriented telemetry;
- `fts-ls` — a Frequency Transfer System laser station controlled through an
  authenticated serial console.

## Building the Debian package

Install the build tools once on a clean Debian system:

```console
sudo apt update
sudo apt install build-essential debhelper git python3 python3-pip
```

When already logged in as `root`, omit `sudo` from these commands.

The `debhelper` package provides the required `debhelper-compat (= 13)` build
dependency. Build the package from the project root:

```console
./packaging/build_deb.sh
```

The script checks the Debian build dependencies before starting and prints the
required installation command when one is missing. The resulting `.deb` file is
written to the parent directory of the project.

## Documentation

The complete operating, administration, and maintenance manual is maintained in
LaTeX:

- source: [`docs/AMP_PANEL_MANUAL.tex`](docs/AMP_PANEL_MANUAL.tex);
- printable output: `docs/AMP_PANEL_MANUAL.pdf`.

Compile it twice so the table of contents and references are updated:

```console
cd docs
pdflatex -interaction=nonstopmode -halt-on-error AMP_PANEL_MANUAL.tex
pdflatex -interaction=nonstopmode -halt-on-error AMP_PANEL_MANUAL.tex
```

The program-operation diagram is generated from code rather than captured from
the interface:

```console
python tools/generate_program_flow_diagram.py
```
