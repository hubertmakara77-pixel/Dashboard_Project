"""Pure FTS-LS console command and response adapter.

Raw firmware labels and command spellings are isolated here. The service owns the
serial session and concurrency, while this module produces the stable FTS status
contract used by every other layer.
"""

import copy
import ipaddress
import math
import re
from typing import Any, cast

from app.core import config, device_schema
from app.core.fts_types import FtsModule, FtsStatus

PORT_PATTERN = re.compile(r"^(?:port|p)([1-7])$", re.IGNORECASE)
SAFE_DESCRIPTION = re.compile(r"^[^\r\n]{0,120}$")
PROMPT_PATTERN = re.compile(r"(?:^|\n)[^\n]{0,80}[>#]\s*$")

STATUS_COMMAND = "show status"
DETAIL_SECTIONS = (
    "laser",
    "ul",
    "port1",
    "port2",
    "port3",
    "port4",
    "port5",
    "port6",
    "port7",
    "tec",
    "synth",
    "power",
)
SYSTEM_COMMANDS = (
    ("network", "show network settings"),
    ("time", "show time settings"),
    ("snmp", "show snmp settings"),
    ("syslog", "show syslog settings"),
    ("hardware", "show hardware"),
    ("version", "show version"),
    ("hostname", "show hostname"),
)
CONSOLE_CONFIRMATION_COMMANDS = frozenset({"power reset", "reboot", "set factory default"})
LONG_RESPONSE_COMMANDS = frozenset({"power reset", "reboot"})

# Raw keys are normalized after the section is known. New firmware labels should
# be added here rather than to API, database, SNMP or frontend code.
COMMON_FIELD_ALIASES = {
    "status": "state",
}
SECTION_FIELD_ALIASES = {
    "laser": {
        "frequency": "optical_frequency",
        "current_frequency": "optical_frequency",
        "wavelength": "optical_wavelength",
        "central_frequency": "central_frequency_set",
        "frequency_span": "scanning_frequency_span_set",
    },
    "tec": {
        "temperature_set": "temperature_set_c",
        "temperature_read": "temperature_read_c",
        "power_usage": "power_usage_percent",
    },
    "synth": {
        "reference_source": "10_mhz_reference_source",
        "reference": "10_mhz_reference_source",
        "external_frequency": "external_10_mhz",
        "external_10_mhz_allowed": "external_frequency_allowed",
    },
    "power": {
        "a": "power_a",
        "b": "power_b",
    },
    "module": {
        "estimated_optical_power": "optical_power_display",
        "noise_low_frequency": "noise_lf",
        "low_frequency_noise": "noise_lf",
        "noise_high_frequency": "noise_hf",
        "high_frequency_noise": "noise_hf",
        "equivalent_distance": "distance_km",
        "additional_gain_set": "additional_gain_db",
    },
}
NUMERIC_FIELDS = frozenset(
    {
        "optical_frequency",
        "optical_wavelength",
        "central_frequency_set",
        "scanning_frequency_span_set",
        "temperature_set_c",
        "temperature_read_c",
        "power_usage_percent",
        "noise_lf",
        "noise_hf",
        "jitter",
        "distance_km",
        "additional_gain_db",
    }
)


def _finite_number(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite.")
    return parsed


def _choice(value: Any, allowed: set[str], label: str) -> str:
    normalized = str(value).strip().lower().replace("_", "-")
    if normalized not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{label} must be one of: {choices}.")
    return normalized


def _target(value: Any, *, allow_uplink: bool = False) -> str:
    normalized = str(value).strip().lower()
    if allow_uplink and normalized in {"ul", "uplink"}:
        return "ul"
    match = PORT_PATTERN.fullmatch(normalized)
    if not match:
        raise ValueError("Target must be port1-port7" + (" or ul." if allow_uplink else "."))
    return f"port{match.group(1)}"


def build_command(action: str, parameters: dict[str, Any]) -> str:
    """Build one documented FTS-LS EXEC command from validated values."""

    action = action.strip().lower().replace("-", "_")
    enabled = parameters.get("enabled")
    if action == "reboot":
        return "reboot"
    if action == "power_reset":
        return "power reset"
    if action == "factory_default":
        return "set factory default"
    if action == "laser_power":
        return f"set laser {'on' if bool(enabled) else 'off'}"
    if action == "laser_central_frequency":
        value = _finite_number(parameters.get("value"), "Laser central frequency")
        if not config.FTS_LS_FREQUENCY_MIN_GHZ <= value <= config.FTS_LS_FREQUENCY_MAX_GHZ:
            raise ValueError(
                "Laser central frequency must be between "
                f"{config.FTS_LS_FREQUENCY_MIN_GHZ} and "
                f"{config.FTS_LS_FREQUENCY_MAX_GHZ} GHz."
            )
        formatted = f"{value:.4f}".rstrip("0").rstrip(".")
        return f"set laser central frequency {formatted}"
    if action == "laser_mode":
        mode = _choice(parameters.get("value"), {"normal", "central-frequency"}, "Laser mode")
        return f"set laser mode {mode.replace('-', '_')}"
    if action == "laser_frequency_span":
        value = _finite_number(parameters.get("value"), "Laser frequency span")
        if not 100 <= value <= 10_000:
            raise ValueError("Laser frequency span must be between 100 and 10000 MHz.")
        return f"set laser frequency span {value:g}"
    if action == "laser_force_relock":
        return "set laser force re-lock"
    if action == "tec_power":
        return f"set tec {'on' if bool(enabled) else 'off'}"
    if action == "tec_temperature":
        value = _finite_number(parameters.get("value"), "TEC temperature setpoint")
        if not 0 <= value <= 100:
            raise ValueError("TEC temperature setpoint must be between 0 and 100 °C.")
        return f"set tec temp setpoint {value:g}"
    if action == "external_reference":
        return f"set rlss external frequency {'allowed' if bool(enabled) else 'not allowed'}"
    if action == "description":
        target = _target(parameters.get("target"), allow_uplink=True)
        description = str(parameters.get("value", "")).strip()
        if not SAFE_DESCRIPTION.fullmatch(description):
            raise ValueError("Description must contain at most 120 characters and no newlines.")
        return f"set {target} description {description}"
    if action == "optical_power":
        target = _target(parameters.get("target"))
        return f"set {target} optical power {'on' if bool(enabled) else 'off'}"
    if action == "downlink_distance":
        target = _target(parameters.get("target"))
        value = _finite_number(parameters.get("value"), "Equivalent distance")
        if not 10 <= value <= 2000:
            raise ValueError("Equivalent distance must be between 10 and 2000 km.")
        return f"set {target} downlink distance {value:g}"
    if action == "downlink_gain":
        target = _target(parameters.get("target"))
        value = int(_finite_number(parameters.get("value"), "Additional NC gain"))
        if value not in {0, 12, 24}:
            raise ValueError("Additional NC gain must be 0, 12 or 24 dB.")
        return f"set {target} additional nc gain {value}"
    if action == "polarization_control":
        target = _target(parameters.get("target"), allow_uplink=True)
        return f"set {target} polarization control {'on' if bool(enabled) else 'off'}"
    if action == "polarization_speed":
        target = _target(parameters.get("target"), allow_uplink=True)
        speed = _choice(parameters.get("value"), {"fast", "slow"}, "Polarization controller speed")
        return f"set {target} polarization controller speed {speed}"
    if action == "polarization_mode":
        target = _target(parameters.get("target"), allow_uplink=True)
        mode = _choice(
            parameters.get("value"), {"continuous", "triggered"}, "Polarization controller mode"
        )
        return f"set {target} polarization controller mode {mode}"
    if action == "ping":
        host = str(parameters.get("value", "")).strip()
        if len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9._:-]+", host):
            raise ValueError("Ping target must be a valid IP address or DNS name.")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
                raise ValueError("Ping target must be a valid IP address or DNS name.") from None
        return f"ping {host}"
    raise ValueError("Unsupported FTS-LS action.")


def _number(text: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
    return float(match.group(0).replace(",", ".")) if match else None


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def parse_key_values(output: str) -> dict[str, Any]:
    """Parse colon-separated firmware output into normalized raw keys."""

    parsed: dict[str, Any] = {}
    for raw_line in output.replace("\r", "").splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        label, raw_value = line.split(":", 1)
        key = _key(label)
        value = raw_value.strip()
        if not key:
            continue
        lowered = value.lower()
        if lowered in {"on", "allowed", "present"}:
            parsed[key] = True
        elif lowered in {"off", "not allowed", "absent"}:
            parsed[key] = False
        else:
            parsed[key] = value
    return parsed


def _connectors(module_type: str) -> list[str]:
    lowered = module_type.lower()
    if "unequipped" in lowered:
        return []
    if "uplink" in lowered:
        return ["O", "BN", "BNA"]
    return ["O", "BN", "TR"]


def _canonical_values(section: str, values: dict[str, Any]) -> dict[str, Any]:
    aliases = {**COMMON_FIELD_ALIASES, **SECTION_FIELD_ALIASES.get(section, {})}
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in values.items():
        key = aliases.get(raw_key, raw_key)
        value = raw_value
        if key in NUMERIC_FIELDS:
            numeric = _number(str(raw_value))
            value = numeric if numeric is not None else raw_value
        if key == "state":
            value = (
                "ON"
                if raw_value is True
                else "OFF"
                if raw_value is False
                else str(raw_value).upper()
            )
        normalized[key] = value
    return normalized


def parse_show_status(output: str, previous: FtsStatus | None = None) -> FtsStatus:
    """Merge a ``show status`` response into a stable canonical snapshot."""

    result = copy.deepcopy(previous or device_schema.empty_fts_ls_status())
    modules = {"uplink": result["uplink"]}
    modules.update({f"port{index}": result["ports"][index - 1] for index in range(1, 8)})
    current: FtsModule | None = None
    for raw_line in output.replace("\r", "").splitlines():
        line = raw_line.strip()
        heading_text = line.rstrip(":").strip()
        heading = re.fullmatch(
            r"(?:Uplink|UL|Port\s*([1-7])|P([1-7]))", heading_text, re.IGNORECASE
        )
        if heading:
            if heading_text.lower() in {"uplink", "ul"}:
                current = modules["uplink"]
            else:
                number = heading.group(1) or heading.group(2)
                current = modules[f"port{number}"]
            continue
        if current is not None and line.upper() == "UNEQUIPPED":
            current.update({"type": "Unequipped", "state": "UNEQUIPPED", "connectors": []})
            continue
        if current is None or ":" not in line:
            continue
        label, value = (part.strip() for part in line.split(":", 1))
        normalized = _key(label)
        if normalized == "type":
            current["type"] = value or "Unknown"
            current["connectors"] = _connectors(current["type"])
        elif normalized == "state":
            current["state"] = value.upper()
        elif normalized == "description":
            current["description"] = value
        elif "estimated" in normalized and "power" in normalized:
            current["optical_power"] = _number(value)
            current["optical_power_display"] = value
        elif "low" in normalized and "noise" in normalized:
            current["noise_lf"] = _number(value)
        elif "high" in normalized and "noise" in normalized:
            current["noise_hf"] = _number(value)
        elif normalized == "jitter":
            current["jitter"] = _number(value)
    return result


def apply_detailed_output(status: FtsStatus, section: str, output: str) -> FtsStatus:
    """Apply a detailed ``show`` response using canonical section field names."""

    destination: dict[str, Any] | FtsModule
    if section == "laser":
        destination = status["laser"]
        alias_section = "laser"
    elif section == "tec":
        destination = status["tec"]
        alias_section = "tec"
    elif section == "synth":
        destination = status["synth"]
        alias_section = "synth"
    elif section == "power":
        destination = status["power"]
        alias_section = "power"
    elif section == "system":
        destination = status["system"]
        alias_section = "system"
    elif section == "ul":
        destination = status["uplink"]
        alias_section = "module"
    else:
        match = re.fullmatch(r"port([1-7])", section)
        if not match:
            return status
        destination = status["ports"][int(match.group(1)) - 1]
        alias_section = "module"

    values = _canonical_values(alias_section, parse_key_values(output))
    mutable_destination = cast(dict[str, Any], destination)
    mutable_destination.update(values)
    if "type" in values:
        mutable_destination["type"] = str(values["type"])
        mutable_destination["connectors"] = _connectors(mutable_destination["type"])
    return status
