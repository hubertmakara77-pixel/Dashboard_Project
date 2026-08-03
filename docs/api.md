# Python API reference

The following sections are generated from docstrings of selected public
functions. They describe the programming interface, not the HTTP contract.

## FTS-LS protocol adapter

::: app.protocols.fts_ls
    options:
      members:
        - build_command
        - parse_key_values
        - parse_show_status
        - apply_detailed_output

## FTS-LS runtime service

::: app.services.fts_ls
    options:
      members:
        - submit_action

## Amplifier protocol adapter

::: app.protocols.amplifier
    options:
      members:
        - parse_line
        - build_gain_command

## Database service

::: app.services.database
    options:
      members:
        - init_database
        - write_measurement
        - write_device_snapshot
        - query_history
        - query_device_snapshots
        - query_statistics
        - stream_raw_history
