import json

import fastapi
import pydantic
import starlette.requests

from app.api import security as api_security
from app.core import state
from app.services import database as database_service
from app.services import serial as serial_reader


router = fastapi.APIRouter()


class GainSetRequest(pydantic.BaseModel):
    gain_set: float


class DashboardSettingsRequest(pydantic.BaseModel):
    gain_tolerance: float | None = None
    warn_limits: dict[str, dict[str, float | None]] | None = None


@router.get("/api/latest")
def latest(
    _current_user: dict = fastapi.Depends(
        api_security.require_roles("Administrator", "Operator", "Viewer")
    ),
):
    database_status = database_service.get_runtime_status()
    with state.state_lock:
        return {
            "connected": state.serial_connected,
            "error": state.serial_error,
            "last_update": state.last_update,
            "last_known_gain_set": state.last_known_gain_set,
            "data": state.latest_data,
            "database": database_status,
        }


@router.get("/api/settings")
def get_settings(
    _current_user: dict = fastapi.Depends(
        api_security.require_roles("Administrator", "Operator", "Viewer")
    ),
):
    with state.state_lock:
        return state.dashboard_settings


@router.post("/api/settings")
def update_settings(
    request: DashboardSettingsRequest,
    http_request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(
        api_security.require_roles("Administrator", "Operator")
    ),
):
    with state.state_lock:
        before = json.loads(json.dumps(state.dashboard_settings))
        if request.gain_tolerance is not None:
            state.dashboard_settings["gain_tolerance"] = float(request.gain_tolerance)
        if request.warn_limits is not None:
            for key, limits in request.warn_limits.items():
                if key not in state.dashboard_settings["warn_limits"]:
                    continue
                for side in ("min", "max"):
                    if side in limits:
                        value = limits[side]
                        state.dashboard_settings["warn_limits"][key][side] = (
                            None if value is None else float(value)
                        )
        state.save_persisted_dashboard_settings()
        after = json.loads(json.dumps(state.dashboard_settings))
    api_security.audit_event(
        http_request,
        "settings_updated",
        current_user["username"],
        api_security.audit_changes(before, after),
    )
    return after


@router.get("/api/errors")
def get_errors(
    _current_user: dict = fastapi.Depends(
        api_security.require_roles("Administrator", "Operator", "Viewer")
    ),
):
    with state.state_lock:
        return {"errors": list(state.error_buffer)}


@router.post("/api/errors/clear")
def clear_errors(
    request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(
        api_security.require_roles("Administrator", "Operator")
    ),
):
    with state.state_lock:
        cleared_count = len(state.error_buffer)
        state.error_buffer.clear()
    api_security.audit_event(
        request,
        "warnings_cleared",
        current_user["username"],
        f"count={cleared_count}",
    )
    return {"errors": []}


@router.post("/api/set_gain")
def set_gain(
    request: GainSetRequest,
    http_request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(
        api_security.require_roles("Administrator", "Operator")
    ),
):
    with state.state_lock:
        previous_gain_set = state.last_known_gain_set
    try:
        serial_reader.send_gain_set(request.gain_set)
    except RuntimeError as exc:
        raise fastapi.HTTPException(status_code=503, detail=str(exc)) from exc
    api_security.audit_event(
        http_request,
        "gain_setpoint_updated",
        current_user["username"],
        api_security.audit_changes(
            {"gain_set": previous_gain_set},
            {"gain_set": request.gain_set},
        ),
    )
    return {"status": "ok", "gain_set": request.gain_set}
