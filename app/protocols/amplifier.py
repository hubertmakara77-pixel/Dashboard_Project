"""Adapter between amplifier firmware lines and canonical application fields."""

MEASUREMENT_PREFIX = "#M:"
MEASUREMENT_SUFFIX = "*"
MISSING_NUMERIC_VALUE = -999.0

# This is the intended firmware-change boundary. Add alternate raw labels here;
# consumers continue to receive the canonical value on the right-hand side.
RAW_FIELD_ALIASES = {
    "T": "temperature",
    "Temp": "temperature",
    "Temperature": "temperature",
}


def _parse_value(value: str) -> float | str | None:
    value = value.strip()
    try:
        numeric_value = float(value)
    except ValueError:
        return value
    if numeric_value == MISSING_NUMERIC_VALUE:
        return None
    return numeric_value


def _parse_parts(payload: str, separator: str) -> dict[str, float | str]:
    data: dict[str, float | str] = {}
    for part in payload.split(";"):
        if separator not in part:
            continue
        raw_key, value = part.split(separator, 1)
        raw_key = raw_key.strip()
        key = RAW_FIELD_ALIASES.get(raw_key, raw_key)
        parsed_value = _parse_value(value)
        if parsed_value is not None:
            data[key] = parsed_value
    return data


def parse_line(line: str) -> dict[str, float | str]:
    """Parse one measurement frame or command response into canonical fields."""

    line = line.strip()
    if line.startswith(MEASUREMENT_PREFIX) and line.endswith(MEASUREMENT_SUFFIX):
        payload = line[len(MEASUREMENT_PREFIX) : -len(MEASUREMENT_SUFFIX)]
        return _parse_parts(payload, ":")
    return _parse_parts(line, "=")


def build_gain_command(gain_set: float) -> bytes:
    """Encode one firmware gain command after service-level range validation."""

    return f"SET_GAIN={gain_set:.2f}\n".encode("utf-8")
