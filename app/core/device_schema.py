"""Canonical device fields shared by persistence, APIs, alarms and integrations.

Names in this module are application contracts. Protocol adapters translate raw
firmware labels into these names so a firmware spelling change does not propagate
through the database, HTTP API, SNMP and frontend.
"""

from dataclasses import dataclass

from app.core.fts_types import FtsStatus


@dataclass(frozen=True)
class FieldSpec:
    """Metadata for one canonical amplifier field."""

    key: str
    label: str
    unit: str | None = None


AMPLIFIER_FIELDS = (
    FieldSpec("M", "M"),
    FieldSpec("PiA", "PiA", "dBm"),
    FieldSpec("PoA", "PoA", "dBm"),
    FieldSpec("PiB", "PiB", "dBm"),
    FieldSpec("PoB", "PoB", "dBm"),
    FieldSpec("G", "G", "dB"),
    FieldSpec("SG", "SG", "dB"),
    FieldSpec("PP", "PP"),
    FieldSpec("SPP", "SPP"),
    FieldSpec("gain_set", "Gain setpoint", "dB"),
    FieldSpec("gain_actual", "Gain actual", "dB"),
    FieldSpec("gain_delta", "Gain delta", "dB"),
    FieldSpec("temperature", "Temperature", "°C"),
    FieldSpec("seq_nr", "Sequence number"),
)

AMPLIFIER_HISTORY_FIELDS = tuple(field.key for field in AMPLIFIER_FIELDS)
AMPLIFIER_CSV_FIELDS = (
    "time",
    "M",
    "PiA",
    "PiB",
    "PoA",
    "PoB",
    "G",
    "SG",
    "PP",
    "SPP",
    "gain_set",
    "gain_actual",
    "gain_delta",
    "temperature",
    "seq_nr",
)
AMPLIFIER_MEASUREMENT_FIELDS = frozenset({"PiA", "PoA", "PiB", "PoB"})
AMPLIFIER_WARNING_FIELDS = ("PiA", "PoA", "PiB", "PoB", "temperature")
AMPLIFIER_FIELD_LABELS = {field.key: field.label for field in AMPLIFIER_FIELDS}

# Stable OID suffixes are an integration contract. The values reference canonical
# field keys and therefore do not depend on the spelling used by device firmware.
AMPLIFIER_SNMP_FIELDS = (
    ("2.1.0", "PiA"),
    ("2.2.0", "PoA"),
    ("2.3.0", "PiB"),
    ("2.4.0", "PoB"),
    ("2.5.0", "gain_actual"),
    ("2.6.0", "gain_set"),
    ("2.7.0", "gain_delta"),
    ("2.8.0", "temperature"),
    ("2.9.0", "seq_nr"),
)


def empty_fts_ls_status() -> FtsStatus:
    """Return a complete canonical FTS-LS snapshot before the first poll."""

    return {
        "profile": "fts-ls",
        "laser": {},
        "uplink": {
            "name": "UL",
            "type": "Uplink",
            "state": "UNKNOWN",
            "connectors": ["O", "BN", "BNA"],
        },
        "ports": [
            {
                "name": f"P{number}",
                "type": "Unknown",
                "state": "UNKNOWN",
                "connectors": ["O", "BN", "TR"],
            }
            for number in range(1, 8)
        ],
        "synth": {},
        "tec": {},
        "power": {"power_a": None, "power_b": None},
        "system": {},
        "last_command": None,
    }
