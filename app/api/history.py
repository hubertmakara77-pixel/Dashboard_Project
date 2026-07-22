import csv
import datetime
import io

import fastapi
import fastapi.responses
import starlette.requests

from app.api import security as api_security
from app.services import database as database_service


router = fastapi.APIRouter()
ALLOWED_RANGES = {"5m", "1h", "24h", "7d", "30d", "all"}
CSV_FIELDS = (
    "time", "M", "PiA", "PiB", "PoA", "PoB", "G", "SG", "PP", "SPP",
    "gain_set", "gain_actual", "gain_delta", "temperature", "seq_nr",
)


def _parse_iso_datetime(value: str | None):
    if not value or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def _normalize_request(
    range_value: str,
    start: str | None,
    end: str | None,
) -> tuple[str, str | None, str | None]:
    if range_value not in ALLOWED_RANGES:
        raise fastapi.HTTPException(status_code=400, detail="Invalid history range")
    try:
        start_value = _parse_iso_datetime(start)
        end_value = _parse_iso_datetime(end)
    except ValueError as exc:
        raise fastapi.HTTPException(status_code=400, detail="Invalid history timestamp") from exc
    if start_value and end_value and start_value >= end_value:
        raise fastapi.HTTPException(status_code=400, detail="History start must be before end")
    return (
        range_value,
        start_value.isoformat() if start_value else None,
        end_value.isoformat() if end_value else None,
    )


def _read_history(range_value: str, start: str | None, end: str | None) -> list[dict]:
    points = database_service.query_history(range_value, start, end)
    if points is None:
        raise fastapi.HTTPException(status_code=503, detail="Local database is unavailable")
    return points


@router.get("/api/history")
def history(
    range: str = "5m",
    start: str | None = None,
    end: str | None = None,
    _current_user: dict = fastapi.Depends(
        api_security.require_roles("Administrator", "Operator", "Viewer")
    ),
):
    range, start, end = _normalize_request(range, start, end)
    return {
        "source": "sqlite",
        "range": range,
        "start": start,
        "end": end,
        "points": _read_history(range, start, end),
    }


@router.get("/api/history/export.csv")
def export_history_csv(
    request: starlette.requests.Request,
    range: str = "5m",
    start: str | None = None,
    end: str | None = None,
    current_user: dict = fastapi.Depends(
        api_security.require_roles("Administrator", "Operator", "Viewer")
    ),
):
    range, start, end = _normalize_request(range, start, end)
    points = _read_history(range, start, end)
    output = io.StringIO()
    output.write("sep=;\r\n")
    writer = csv.DictWriter(
        output,
        fieldnames=CSV_FIELDS,
        extrasaction="ignore",
        delimiter=";",
        lineterminator="\r\n",
    )
    writer.writeheader()
    writer.writerows(points)
    api_security.audit_event(
        request,
        "history_csv_exported",
        current_user["username"],
        f"range={range}; start={start}; end={end}; rows={len(points)}",
    )
    filename = f"amp_history_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return fastapi.responses.Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
