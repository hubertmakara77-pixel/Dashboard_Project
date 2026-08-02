import copy
import dataclasses
import datetime
import ipaddress
import math
import queue
import re
import threading
import time
from typing import Any

try:
    import serial
except ModuleNotFoundError:  # Allows parser/unit tests without runtime extras.
    serial = None

from app.core import config, state
from app.services import database as database_service
from app.services import syslog as syslog_service


PORT_PATTERN = re.compile(r"^(?:port|p)([1-7])$", re.IGNORECASE)
SAFE_DESCRIPTION = re.compile(r"^[^\r\n]{0,120}$")
PROMPT_PATTERN = re.compile(r"(?:^|\n)[^\n]{0,80}[>#]\s*$")


@dataclasses.dataclass
class PendingCommand:
    command: str
    action: str
    event: threading.Event = dataclasses.field(default_factory=threading.Event)
    output: str = ""
    error: str | None = None


command_queue: queue.Queue[PendingCommand] = queue.Queue(maxsize=32)
FTS_WARNING_KINDS = {"lock_state", "noise_lf", "jitter", "optical_power", "power_supply"}
SERIAL_ERRORS = (
    (RuntimeError, OSError, ValueError)
    if serial is None
    else (RuntimeError, serial.SerialException, OSError, ValueError)
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
        mode = _choice(parameters.get("value"), {"continuous", "triggered"}, "Polarization controller mode")
        return f"set {target} polarization controller mode {mode}"
    if action == "ping":
        host = str(parameters.get("value", "")).strip()
        if len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9._:-]+", host):
            raise ValueError("Ping target must be a valid IP address or DNS name.")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
                raise ValueError("Ping target must be a valid IP address or DNS name.")
        return f"ping {host}"
    raise ValueError("Unsupported FTS-LS action.")


def _number(text: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
    return float(match.group(0).replace(",", ".")) if match else None


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def parse_key_values(output: str) -> dict[str, Any]:
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


def parse_show_status(output: str, previous: dict | None = None) -> dict:
    result = copy.deepcopy(previous or state.empty_fts_ls_status())
    modules = {"uplink": result["uplink"]}
    modules.update({f"port{index}": result["ports"][index - 1] for index in range(1, 8)})
    current: dict | None = None

    for raw_line in output.replace("\r", "").splitlines():
        line = raw_line.strip()
        heading_text = line.rstrip(":").strip()
        heading = re.fullmatch(r"(?:Uplink|UL|Port\s*([1-7])|P([1-7]))", heading_text, re.IGNORECASE)
        if heading:
            if heading_text.lower() in {"uplink", "ul"}:
                current = modules["uplink"]
            else:
                number = heading.group(1) or heading.group(2)
                current = modules[f"port{number}"]
            continue
        if current is not None and line.upper() == "UNEQUIPPED":
            current["type"] = "Unequipped"
            current["state"] = "UNEQUIPPED"
            current["connectors"] = []
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


def apply_detailed_output(status: dict, section: str, output: str) -> dict:
    values = parse_key_values(output)
    destination: dict
    if section == "laser":
        destination = status["laser"]
    elif section == "tec":
        destination = status["tec"]
    elif section == "synth":
        destination = status["synth"]
    elif section == "power":
        destination = status["power"]
    elif section == "system":
        destination = status["system"]
    elif section == "ul":
        destination = status["uplink"]
    else:
        match = re.fullmatch(r"port([1-7])", section)
        if not match:
            return status
        destination = status["ports"][int(match.group(1)) - 1]
    destination.update(values)

    aliases = {
        "estimated_optical_power": "optical_power_display",
        "noise_low_frequency": "noise_lf",
        "low_frequency_noise": "noise_lf",
        "noise_high_frequency": "noise_hf",
        "high_frequency_noise": "noise_hf",
        "equivalent_distance": "distance_km",
        "additional_gain_set": "additional_gain_db",
        "temperature_set": "temperature_set_c",
        "temperature_read": "temperature_read_c",
        "power_usage": "power_usage_percent",
    }
    for source, target in aliases.items():
        if source in values:
            numeric = _number(str(values[source]))
            destination[target] = numeric if numeric is not None else values[source]
    if "state" in values:
        state_value = values["state"]
        destination["state"] = (
            "ON" if state_value is True else "OFF" if state_value is False
            else str(state_value).upper()
        )
    if "type" in values:
        destination["type"] = str(values["type"])
        destination["connectors"] = _connectors(destination["type"])
    return status


def _warning_candidates(status: dict, now: str) -> dict[tuple[str, str], dict]:
    candidates = {}
    for module in [status["uplink"], *status["ports"]]:
        module_state = str(module.get("state", "UNKNOWN")).upper()
        name = module["name"]
        if module_state == "UNLOCKED":
            candidates[(name, "lock_state")] = {
                "time": now, "field": name, "kind": "lock_state",
                "label": f"{name} lock", "value": module_state,
                "target": "LOCKED", "delta": None, "allowed": None,
                "message": f"{name} is unlocked",
            }
        noise_lf = module.get("noise_lf")
        if isinstance(noise_lf, (int, float)) and noise_lf > 100:
            candidates[(name, "noise_lf")] = {
                "time": now, "field": name, "kind": "noise_lf",
                "label": f"{name} LF noise", "value": noise_lf,
                "target": 100, "delta": noise_lf - 100, "allowed": 0,
                "message": f"{name} low-frequency noise is unusually high",
            }
        jitter = module.get("jitter")
        if isinstance(jitter, (int, float)) and jitter > 50:
            candidates[(name, "jitter")] = {
                "time": now, "field": name, "kind": "jitter",
                "label": f"{name} jitter", "value": jitter,
                "target": 50, "delta": jitter - 50, "allowed": 0,
                "message": f"{name} jitter indicates possible massive cycle slips",
            }
        optical_display = str(module.get("optical_power_display", "")).upper()
        if optical_display in {"LOW", "HIGH"}:
            candidates[(name, "optical_power")] = {
                "time": now, "field": name, "kind": "optical_power",
                "label": f"{name} optical power", "value": optical_display,
                "target": "-65…-33 dBm", "delta": None, "allowed": None,
                "message": f"{name} estimated optical power is {optical_display}",
            }
    power = status.get("power", {})
    for side in ("a", "b"):
        value = power.get(f"power_{side}", power.get(side))
        normalized = str(value).strip().lower()
        if value is False or normalized in {"off", "absent", "failed", "failure"}:
            label = f"Power {side.upper()}"
            candidates[(label, "power_supply")] = {
                "time": now, "field": label, "kind": "power_supply",
                "label": label, "value": value, "target": "ON",
                "delta": None, "allowed": None,
                "message": f"{label} is unavailable",
            }
    return candidates


def _update_warnings(status: dict, now: str) -> None:
    current = _warning_candidates(status, now)
    opened = []
    cleared = []
    with state.state_lock:
        managed_previous = {key for key in state.active_warnings if key[1] in FTS_WARNING_KINDS}
        for key in managed_previous - set(current):
            warning = dict(state.active_warnings.pop(key))
            state.acknowledged_warning_keys.discard(key)
            warning.update({"event": "CLEARED", "event_time": now, "cleared_at": now})
            cleared.append(warning)
        for key, warning in current.items():
            if key in state.active_warnings:
                original = state.active_warnings[key]
                warning.update({
                    "event": "OPEN",
                    "event_time": original["event_time"],
                    "opened_at": original["opened_at"],
                    "acknowledged": key in state.acknowledged_warning_keys,
                })
            else:
                warning.update({"event": "OPEN", "event_time": now, "opened_at": now, "acknowledged": False})
                opened.append(dict(warning))
            state.active_warnings[key] = warning
    for warning in opened:
        syslog_service.send_warning_event("OPEN", warning)
        try:
            from app.services import snmp as snmp_service

            snmp_service.send_trap(warning)
        except Exception as exc:
            print("SNMP trap send failed:", exc)
    for warning in cleared:
        syslog_service.send_warning_event("CLEARED", warning)


class SerialCliSession:
    def __init__(self, port: str):
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        self.serial = serial.Serial(
            port=port,
            baudrate=config.SERIAL_BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.25,
            write_timeout=2,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        self.exec_mode = False

    def close(self) -> None:
        self.serial.close()

    def _write_line(self, value: str) -> None:
        self.serial.write((value + "\r\n").encode("utf-8"))
        self.serial.flush()

    def _read_response(self, max_seconds: float = 8.0) -> str:
        chunks = []
        deadline = time.monotonic() + max_seconds
        last_data = time.monotonic()
        while time.monotonic() < deadline:
            chunk = self.serial.readline()
            if chunk:
                chunks.append(chunk.decode("utf-8", errors="replace"))
                last_data = time.monotonic()
                joined = "".join(chunks)
                if PROMPT_PATTERN.search(joined.replace("\r", "")):
                    break
            elif chunks and time.monotonic() - last_data >= 0.6:
                break
        return "".join(chunks).strip()

    def login(self) -> None:
        self.serial.reset_input_buffer()
        self._write_line("")
        output = self._read_response(3)
        lowered = output.lower()
        if "login:" in lowered or "username:" in lowered:
            self._write_line(config.FTS_LS_USERNAME)
            output += "\n" + self._read_response(3)
            lowered = output.lower()
        if "password:" in lowered:
            if not config.FTS_LS_PASSWORD:
                raise RuntimeError("FTS_LS_PASSWORD is not configured")
            self._write_line(config.FTS_LS_PASSWORD)
            output += "\n" + self._read_response(5)
        if re.search(r"incorrect|authentication failed|login failed", output, re.IGNORECASE):
            raise RuntimeError("FTS-LS console authentication failed")

    def command(self, command: str, *, exec_required: bool = False) -> str:
        if exec_required and not self.exec_mode:
            self._write_line("exec")
            exec_output = self._read_response()
            if re.search(r"busy|denied|not allowed|error", exec_output, re.IGNORECASE):
                raise RuntimeError(exec_output or "FTS-LS EXEC mode is unavailable")
            self.exec_mode = True
        self._write_line(command)
        output = self._read_response(15 if command in {"power reset", "reboot"} else 8)
        if command in {"power reset", "reboot", "set factory default"} and re.search(
            r"confirm|are you sure|\[[yY]/[nN]\]|yes/no",
            output,
            re.IGNORECASE,
        ):
            self._write_line("yes")
            output += "\n" + self._read_response(35 if command == "power reset" else 15)
        if re.search(r"unknown command|invalid command|permission denied", output, re.IGNORECASE):
            raise RuntimeError(output)
        return output


def submit_action(action: str, parameters: dict[str, Any], timeout: float = 20) -> dict:
    command = build_command(action, parameters)
    pending = PendingCommand(command=command, action=action)
    try:
        command_queue.put_nowait(pending)
    except queue.Full as exc:
        raise RuntimeError("The FTS-LS command queue is full.") from exc
    if not pending.event.wait(timeout):
        raise RuntimeError("The FTS-LS device did not answer in time.")
    if pending.error:
        raise RuntimeError(pending.error)
    return {"status": "ok", "action": action, "output": pending.output}


def _process_commands(session: SerialCliSession) -> None:
    while True:
        try:
            pending = command_queue.get_nowait()
        except queue.Empty:
            return
        try:
            pending.output = session.command(
                pending.command,
                exec_required=pending.action != "ping",
            )
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            with state.state_lock:
                state.fts_ls_status["last_command"] = {
                    "action": pending.action,
                    "time": now,
                    "output": pending.output,
                }
        except Exception as exc:
            pending.error = str(exc)
        finally:
            if session.exec_mode:
                try:
                    session.command("back")
                except Exception:
                    pass
                session.exec_mode = False
            pending.event.set()
            command_queue.task_done()


def _poll(session: SerialCliSession) -> None:
    with state.state_lock:
        status = copy.deepcopy(state.fts_ls_status)
    summary_output = session.command("show status")
    if not re.search(r"\b(?:Uplink|UL|Port\s*[1-7]|P[1-7])\b", summary_output, re.IGNORECASE):
        raise RuntimeError("FTS-LS did not return a valid 'show status' response")
    status = parse_show_status(summary_output, status)
    for section in ("laser", "ul", "port1", "port2", "port3", "port4", "port5", "port6", "port7", "tec", "synth", "power"):
        try:
            apply_detailed_output(status, section, session.command(f"show {section}"))
        except SERIAL_ERRORS:
            raise
    for name, command in (
        ("network", "show network settings"),
        ("time", "show time settings"),
        ("snmp", "show snmp settings"),
        ("syslog", "show syslog settings"),
        ("hardware", "show hardware"),
        ("version", "show version"),
        ("hostname", "show hostname"),
    ):
        output = session.command(command)
        parsed = parse_key_values(output)
        status["system"][name] = parsed or {"raw": output}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with state.state_lock:
        state.fts_ls_status = status
        state.latest_data = {"device_profile": "fts-ls", "fts_ls": copy.deepcopy(status)}
        state.last_update = now
        state.serial_connected = True
        state.serial_error = None
    database_service.write_device_snapshot("fts-ls", status, now)
    _update_warnings(status, now)


def reader_loop() -> None:
    while not state.stop_event.is_set():
        with state.state_lock:
            port = str(state.service_settings["serial_port"])
        session = None
        try:
            session = SerialCliSession(port)
            with state.serial_lock:
                state.serial_port = session.serial
            session.login()
            with state.state_lock:
                state.serial_connected = True
                state.serial_error = None
            next_poll = 0.0
            while not state.stop_event.is_set():
                _process_commands(session)
                if time.monotonic() >= next_poll:
                    _poll(session)
                    next_poll = time.monotonic() + config.FTS_LS_POLL_SECONDS
                state.stop_event.wait(0.2)
        except SERIAL_ERRORS as exc:
            with state.state_lock:
                state.serial_connected = False
                state.serial_error = str(exc)
            print("FTS-LS serial error:", exc)
        finally:
            if session is not None:
                try:
                    session.close()
                except SERIAL_ERRORS:
                    pass
            with state.serial_lock:
                state.serial_port = None
            with state.state_lock:
                state.serial_connected = False
        if not state.stop_event.is_set():
            state.serial_reconnect_event.wait(timeout=2)
            state.serial_reconnect_event.clear()
