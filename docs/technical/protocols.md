# Device protocols

## Amplifier profile

The worker opens the configured port with a 1-second timeout. It reads UTF-8 lines
and recognizes a measurement frame of the form:

```text
#M:key:value;key:value;...*
```

Example:

```text
#M:PiA:-12.3;PoA:2.7;PiB:-12.1;PoB:2.8;T:34.2;seq_nr:1234*
```

Supported database fields are listed in the [schema description](database.md).
Alias `T` becomes `temperature`, numbers are converted to `float`, and sentinel
value `-999` is omitted. Ordinary responses outside a measurement frame use
`key=value;key=value`. Text remains text. A line is stored as a sample only when
the processed result contains at least one supported numeric field.

The gain setpoint is validated and sent as
`SET_GAIN=<value with two decimal places>\n`, for example `SET_GAIN=15.25`. After
confirmation, it is persisted in state and `setpoint_events`. Changing the format
requires testing against the target firmware.

Raw amplifier aliases are defined only in
`app/protocols/amplifier.py::RAW_FIELD_ALIASES`. For example, `T`, `Temp`, and
`Temperature` all become canonical `temperature`. Add a new firmware spelling to
that mapping rather than changing database or API fields.

## FTS-LS profile

The connection uses 8N1, no flow control, and 115200 bit/s by default. Sequence:

1. synchronize by sending an empty line;
2. answer `login:`/`username:` and `password:` prompts;
3. periodically issue `show status`;
4. request `show laser`, `show ul`, `show port1`…`show port7`, `show tec`,
   `show synth`, and `show power`;
5. request `show network settings`, `show time settings`, `show snmp settings`,
   `show syslog settings`, `show hardware`, `show version`, and `show hostname`;
6. execute queued commands in `exec` mode, followed by `back`.

A prompt terminates a response. If data has started, 0.6 seconds without new data
also terminates it. Ordinary commands have about 8 seconds to respond; reboot and
power reset use longer timeouts. Transport errors close the session and trigger a
retry after approximately 2 seconds.

### Stable status contract

Every snapshot contains `profile`, `laser`, `uplink`, `ports`, `synth`, `tec`,
`power`, `system`, and `last_command`. `ports` always contains exactly seven
positions, P1–P7. A missing module does not shift later slots. Values containing
units are normalized, while the display representation may be preserved
separately.

### Command generation

Command text never comes directly from HTTP. `build_command` uses an allowlist of
actions, targets, enums, and ranges. Supported operations are listed in the
[FTS-LS manual](../manual/fts-ls.md). Module descriptions are validated before a
command is built, preventing insertion of another console line.

Section-specific aliases are defined in
`app/protocols/fts_ls.py::SECTION_FIELD_ALIASES`. Poll commands and console timing
rules live in the same adapter. The service owns the serial connection, queue,
warnings, and persistence but contains no firmware field mapping.

### Integrating real hardware

For every firmware version, capture representative text responses for `show
status`, all detailed `show` sections, login prompts, successful commands, rejected
commands, and reset confirmation. Add the captures as test fixtures before
changing aliases. Unknown detailed keys are retained for diagnostics, while known
aliases must be converted to canonical keys before the snapshot leaves the
adapter.

## Simulator

`tools/arduino/fts_ls_uno_simulator/fts_ls_uno_simulator.ino` implements a basic
console for laboratory testing. It helps test the parser and UI, but does not
replace integration testing against the firmware version deployed on the station.
