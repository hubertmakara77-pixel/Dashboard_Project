import datetime
import pathlib
import socket
import threading

import config


FACILITY_LOCAL0 = config.SYSLOG_FACILITY
SEVERITY_WARNING = 4
SEVERITY_INFO = 6
audit_log_lock = threading.Lock()


def send_syslog(message: str, severity: int) -> None:
    if not config.SYSLOG_ENABLED:
        return

    priority = FACILITY_LOCAL0 * 8 + severity
    timestamp = datetime.datetime.now().strftime("%b %d %H:%M:%S")
    hostname = socket.gethostname()
    payload = f"<{priority}>{timestamp} {hostname} {config.SYSLOG_APP_NAME}: {message}"

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload.encode("utf-8"), (config.SYSLOG_HOST, config.SYSLOG_PORT))
    except OSError as error:
        print(f"Syslog send failed: {error}")


def send_warning(message: str) -> None:
    send_syslog(message, SEVERITY_WARNING)


def append_audit_log(message: str) -> None:
    if not config.AUDIT_LOG_FILE:
        return

    path = pathlib.Path(config.AUDIT_LOG_FILE)

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with audit_log_lock:
            with path.open("a", encoding="utf-8") as file:
                file.write(message + "\n")
    except OSError as error:
        print(f"Audit log write failed: {error}")


def get_audit_log_path() -> pathlib.Path:
    return pathlib.Path(config.AUDIT_LOG_FILE)


def send_audit(action: str, username: str, ip_address: str, details: str = "") -> None:
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    detail_text = f"; details={details}" if details else ""
    message = f"audit timestamp={timestamp}; user={username}; ip={ip_address}; action={action}{detail_text}"

    append_audit_log(message)
    send_syslog(
        message,
        SEVERITY_INFO,
    )
