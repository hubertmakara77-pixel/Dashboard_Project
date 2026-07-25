import json

import fastapi
import pydantic
import starlette.requests

from app.api import security as api_security
from app.core import config, state, validation
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
        return {
            **json.loads(json.dumps(state.dashboard_settings)),
            "gain_set_limits": {
                "min": config.GAIN_SET_MIN,
                "max": config.GAIN_SET_MAX,
            },
        }


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
        try:
            state.dashboard_settings = validation.validated_dashboard_settings(
                state.dashboard_settings,
                request.gain_tolerance,
                request.warn_limits,
            )
        except ValueError as exc:
            raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
        state.save_persisted_dashboard_settings()
        after = json.loads(json.dumps(state.dashboard_settings))
    api_security.audit_event(
        http_request,
        "settings_updated",
        current_user["username"],
        api_security.audit_changes(before, after),
    )
    return {
        **after,
        "gain_set_limits": {
            "min": config.GAIN_SET_MIN,
            "max": config.GAIN_SET_MAX,
        },
    }


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
        gain_set = validation.validate_gain_set(
            request.gain_set,
            config.GAIN_SET_MIN,
            config.GAIN_SET_MAX,
        )
        serial_reader.send_gain_set(gain_set)
    except ValueError as exc:
        raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise fastapi.HTTPException(status_code=503, detail=str(exc)) from exc
    api_security.audit_event(
        http_request,
        "gain_setpoint_updated",
        current_user["username"],
        api_security.audit_changes(
            {"gain_set": previous_gain_set},
            {"gain_set": gain_set},
        ),
    )
    return {"status": "ok", "gain_set": gain_set}
