import datetime
import pathlib
import socket
import zoneinfo

from app.core import config


FACILITY_LOCAL0 = config.SYSLOG_FACILITY
SEVERITY_WARNING = 4
SEVERITY_INFO = 6
def local_now() -> datetime.datetime:
    try:
        timezone = zoneinfo.ZoneInfo(config.SYSLOG_TIMEZONE)
    except zoneinfo.ZoneInfoNotFoundError:
        timezone = datetime.timezone.utc
    return datetime.datetime.now(timezone)


def send_syslog(message: str, severity: int) -> None:
    if not config.SYSLOG_ENABLED:
        return

    priority = FACILITY_LOCAL0 * 8 + severity
    timestamp = local_now().strftime("%b %d %H:%M:%S")
    hostname = socket.gethostname()
    payload = (
        f"<{priority}>{timestamp} {hostname} {config.SYSLOG_APP_NAME}: "
        f"device={config.DEVICE_NAME}; {message}"
    )

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload.encode("utf-8"), (config.SYSLOG_HOST, config.SYSLOG_PORT))
    except OSError as error:
        print(f"Syslog send failed: {error}")


def send_warning(message: str) -> None:
    send_syslog(f"warning; {message}", SEVERITY_WARNING)


def send_lifecycle(event: str, **fields: object) -> None:
    field_text = "".join(f"; {name}={value}" for name, value in fields.items())
    send_syslog(f"lifecycle; event={event}{field_text}", SEVERITY_INFO)


def get_syslog_log_path() -> pathlib.Path:
    return pathlib.Path(config.SYSLOG_EXPORT_FILE)


def send_audit(action: str, username: str, ip_address: str, details: str = "") -> None:
    detail_text = f"; details={details}" if details else ""
    message = f"audit; user={username}; ip={ip_address}; action={action}{detail_text}"

    send_syslog(
        message,
        SEVERITY_INFO,
    )
