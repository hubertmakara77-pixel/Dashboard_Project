import contextlib
import csv
import datetime
import io
import secrets
import threading

import fastapi
import fastapi.responses
import fastapi.staticfiles
import fastapi.templating
import pydantic
import starlette.requests

import config
import influx_service
import network_service
import snmp_service
import serial_reader
import state
import syslog_service


class GainSetRequest(pydantic.BaseModel):
    gain_set: float


class DashboardSettingsRequest(pydantic.BaseModel):
    gain_tolerance: float | None = None
    warn_limits: dict[str, dict[str, float | None]] | None = None


class NetworkSettingsRequest(pydantic.BaseModel):
    interface: str
    mode: str
    ip_address: str = ""
    netmask: str = ""
    gateway: str = ""
    dns: str = ""



class SnmpSettingsUpdateRequest(pydantic.BaseModel):
    enabled: bool
    port: int
    community: str
    trap_host: str
    trap_port: int

class LoginRequest(pydantic.BaseModel):
    username: str
    password: str


class AccessUserCreateRequest(pydantic.BaseModel):
    username: str
    password: str
    role: str = "Operator"
    active: bool = True


class AccessUserUpdateRequest(pydantic.BaseModel):
    password: str | None = None
    role: str | None = None
    active: bool | None = None


def find_access_user(username: str) -> dict | None:
    for user in state.access_users:
        if user["username"] == username:
            return user

    return None


def normalize_username(username: str) -> str:
    value = username.strip()

    if not value:
        raise fastapi.HTTPException(status_code=400, detail="Username is required")

    return value


def count_active_administrators() -> int:
    return sum(
        1
        for user in state.access_users
        if user["role"] == "Administrator" and user["active"]
    )


def user_has_role(user: dict, allowed_roles: set[str]) -> bool:
    return user["role"] in allowed_roles


def get_client_ip(request: starlette.requests.Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    if request.client is None:
        return "unknown"

    return request.client.host


def audit_event(request: starlette.requests.Request, action: str, username: str, details: str = "") -> None:
    syslog_service.send_audit(
        action=action,
        username=username,
        ip_address=get_client_ip(request),
        details=details,
    )


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    state.auth_sessions[token] = {
        "username": username,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    return token


def get_current_user(session_token: str | None = fastapi.Cookie(default=None)) -> dict:
    if not session_token:
        raise fastapi.HTTPException(status_code=401, detail="Not authenticated")

    with state.state_lock:
        session = state.auth_sessions.get(session_token)

        if session is None:
            raise fastapi.HTTPException(status_code=401, detail="Not authenticated")

        user = find_access_user(session["username"])

        if user is None or not user["active"]:
            state.auth_sessions.pop(session_token, None)
            raise fastapi.HTTPException(status_code=401, detail="Not authenticated")

        return state.access_user_public(user)


def require_roles(*allowed_roles: str):
    allowed = set(allowed_roles)

    def dependency(current_user: dict = fastapi.Depends(get_current_user)) -> dict:
        if not user_has_role(current_user, allowed):
            raise fastapi.HTTPException(status_code=403, detail="Not allowed")

        return current_user

    return dependency


def parse_iso_datetime(value: str | None):
    if not value:
        return None

    normalized_value = value.strip()

    if not normalized_value:
        return None

    if normalized_value.endswith("Z"):
        normalized_value = normalized_value[:-1] + "+00:00"

    parsed = datetime.datetime.fromisoformat(normalized_value)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)

    return parsed.astimezone(datetime.timezone.utc)


def parse_memory_range(range_value: str):
    now = datetime.datetime.now(datetime.timezone.utc)

    if range_value == "5m":
        return now - datetime.timedelta(minutes=5)

    if range_value == "1h":
        return now - datetime.timedelta(hours=1)

    if range_value == "24h":
        return now - datetime.timedelta(hours=24)

    if range_value == "7d":
        return now - datetime.timedelta(days=7)

    if range_value == "30d":
        return now - datetime.timedelta(days=30)

    return None


def query_history_from_memory(range_value: str, start: str | None = None, end: str | None = None):
    start_time = parse_iso_datetime(start) or parse_memory_range(range_value)
    end_time = parse_iso_datetime(end)

    with state.state_lock:
        points = list(state.history_buffer)

    if start_time is None and end_time is None:
        return points

    filtered_points = []

    for point in points:
        point_time = datetime.datetime.fromisoformat(point["time"])
        if point_time.tzinfo is None:
            point_time = point_time.replace(tzinfo=datetime.timezone.utc)
        else:
            point_time = point_time.astimezone(datetime.timezone.utc)

        if start_time is not None and point_time < start_time:
            continue

        if end_time is not None and point_time > end_time:
            continue

        filtered_points.append(point)

    return filtered_points


def build_history_csv(points: list[dict]) -> str:
    output = io.StringIO()
    output.write("sep=;\r\n")
    fieldnames = [
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
    ]
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        extrasaction="ignore",
        delimiter=";",
        lineterminator="\r\n",
    )
    writer.writeheader()

    for point in points:
        writer.writerow(point)

    return output.getvalue()


@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    influx_service.init_influx()
    snmp_service.init_snmp()

    state.stop_event.clear()

    thread = threading.Thread(
        target=serial_reader.serial_reader_loop,
        daemon=True
    )

    thread.start()

    yield

    print("Shutting down application...")

    state.stop_event.set()
    thread.join(timeout=2)

    snmp_service.close_snmp()
    influx_service.close_influx()


app = fastapi.FastAPI(lifespan=lifespan)

app.mount(
    "/static",
    fastapi.staticfiles.StaticFiles(directory="static"),
    name="static"
)

templates = fastapi.templating.Jinja2Templates(directory="templates")


@app.get("/")
def home(request: starlette.requests.Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )


@app.get("/api/latest")
def latest(_current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer"))):
    with state.state_lock:
        return {
            "connected": state.serial_connected,
            "error": state.serial_error,
            "last_update": state.last_update,
            "last_command_response": state.last_command_response,
            "last_known_gain_set": state.last_known_gain_set,
            "data": state.latest_data
        }


@app.get("/api/status")
def status(_current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer"))):
    with state.state_lock:
        return {
            "device": config.DEVICE_NAME,
            "serial_port": config.SERIAL_PORT,
            "serial_connected": state.serial_connected,
            "serial_error": state.serial_error,
            "influx_enabled": config.INFLUX_ENABLED
        }


@app.get("/api/settings")
def get_settings(_current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer"))):
    with state.state_lock:
        return state.dashboard_settings


@app.get("/api/network")
def get_network_settings(
    _current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer")),
):
    try:
        return network_service.get_network_state()
    except network_service.NetworkError as exc:
        raise fastapi.HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/network")
def update_network_settings(
    settings: NetworkSettingsRequest,
    request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(require_roles("Administrator")),
):
    try:
        result = network_service.apply_network_settings(settings.model_dump())
    except network_service.NetworkError as exc:
        raise fastapi.HTTPException(status_code=400, detail=str(exc)) from exc

    audit_event(
        request,
        "network_settings_updated",
        current_user["username"],
        f"interface={settings.interface}; mode={settings.mode}",
    )
    return result


@app.post("/api/auth/login")
def login(
    login_request: LoginRequest,
    response: fastapi.Response,
    request: starlette.requests.Request,
):
    username = normalize_username(login_request.username)

    with state.state_lock:
        user = find_access_user(username)

        if (
            user is None
            or not user["active"]
            or not state.verify_password(login_request.password, user["password_hash"], user["password_salt"])
        ):
            audit_event(request, "login_failed", username, "invalid_credentials_or_inactive_user")
            raise fastapi.HTTPException(status_code=401, detail="Invalid username or password")

        token = create_session(username)
        public_user = state.access_user_public(user)

    audit_event(request, "login_success", username, f"role={public_user['role']}")

    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="strict",
        max_age=60 * 60 * 12,
    )

    return {
        "user": public_user
    }


@app.get("/api/auth/me")
def auth_me(current_user: dict = fastapi.Depends(get_current_user)):
    return {
        "user": current_user
    }


@app.post("/api/auth/logout")
def logout(
    response: fastapi.Response,
    request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(get_current_user),
    session_token: str | None = fastapi.Cookie(default=None),
):
    with state.state_lock:
        if session_token:
            state.auth_sessions.pop(session_token, None)

    audit_event(request, "logout", current_user["username"])

    response.delete_cookie("session_token")

    return {
        "status": "ok"
    }


@app.get("/api/access/users")
def get_access_users(_current_user: dict = fastapi.Depends(require_roles("Administrator"))):
    with state.state_lock:
        return {
            "users": [state.access_user_public(user) for user in state.access_users]
        }


@app.get("/api/audit/export.log")
def export_audit_log(
    request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(require_roles("Administrator")),
):
    audit_event(request, "audit_log_exported", current_user["username"])

    path = syslog_service.get_audit_log_path()
    filename_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    if not path.exists():
        return fastapi.responses.Response(
            content="",
            media_type="text/plain",
            headers={
                "Content-Disposition": f'attachment; filename="amp_audit_{filename_time}.log"'
            },
        )

    return fastapi.responses.FileResponse(
        path,
        media_type="text/plain",
        filename=f"amp_audit_{filename_time}.log",
    )


@app.post("/api/access/users")
def create_access_user(
    request: AccessUserCreateRequest,
    http_request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(require_roles("Administrator")),
):
    username = normalize_username(request.username)

    if not request.password:
        raise fastapi.HTTPException(status_code=400, detail="Password is required")

    with state.state_lock:
        if find_access_user(username) is not None:
            raise fastapi.HTTPException(status_code=409, detail="User already exists")

        password_hash, password_salt = state.hash_password(request.password)
        user = {
            "username": username,
            "role": request.role.strip() or "Operator",
            "active": bool(request.active),
            "password_hash": password_hash,
            "password_salt": password_salt,
        }
        state.access_users.append(user)
        state.save_persisted_access_users()

        audit_event(
            http_request,
            "access_user_created",
            current_user["username"],
            f"target={username}; role={user['role']}; active={user['active']}",
        )

        return state.access_user_public(user)


@app.put("/api/access/users/{username}")
def update_access_user(
    username: str,
    request: AccessUserUpdateRequest,
    http_request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(require_roles("Administrator")),
):
    username = normalize_username(username)

    with state.state_lock:
        user = find_access_user(username)

        if user is None:
            raise fastapi.HTTPException(status_code=404, detail="User not found")

        next_role = request.role.strip() if request.role is not None else user["role"]
        next_active = bool(request.active) if request.active is not None else bool(user["active"])

        if user["role"] == "Administrator" and user["active"]:
            if (next_role != "Administrator" or not next_active) and count_active_administrators() <= 1:
                raise fastapi.HTTPException(
                    status_code=400,
                    detail="At least one active administrator is required"
                )

        if request.role is not None:
            user["role"] = next_role or "Operator"

        if request.active is not None:
            user["active"] = next_active

        if request.password:
            user["password_hash"], user["password_salt"] = state.hash_password(request.password)

        state.save_persisted_access_users()

        audit_event(
            http_request,
            "access_user_updated",
            current_user["username"],
            f"target={username}; role={user['role']}; active={user['active']}; password_changed={bool(request.password)}",
        )

        return state.access_user_public(user)


@app.delete("/api/access/users/{username}")
def delete_access_user(
    username: str,
    http_request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(require_roles("Administrator")),
):
    username = normalize_username(username)

    with state.state_lock:
        user = find_access_user(username)

        if user is None:
            raise fastapi.HTTPException(status_code=404, detail="User not found")

        if len(state.access_users) == 1:
            raise fastapi.HTTPException(status_code=400, detail="At least one user is required")

        if user["role"] == "Administrator" and user["active"] and count_active_administrators() <= 1:
            raise fastapi.HTTPException(
                status_code=400,
                detail="At least one active administrator is required"
            )

        state.access_users.remove(user)
        state.save_persisted_access_users()

    audit_event(http_request, "access_user_deleted", current_user["username"], f"target={username}")

    return {
        "status": "ok"
    }


@app.post("/api/settings")
def update_settings(
    request: DashboardSettingsRequest,
    http_request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator")),
):
    with state.state_lock:
        if request.gain_tolerance is not None:
            state.dashboard_settings["gain_tolerance"] = float(request.gain_tolerance)

        if request.warn_limits is not None:
            for key, limits in request.warn_limits.items():
                if key not in state.dashboard_settings["warn_limits"]:
                    continue

                for side in ("min", "max"):
                    if side in limits:
                        value = limits[side]
                        state.dashboard_settings["warn_limits"][key][side] = None if value is None else float(value)

        state.save_persisted_dashboard_settings()

        audit_event(
            http_request,
            "settings_updated",
            current_user["username"],
            f"gain_tolerance={state.dashboard_settings['gain_tolerance']}; warn_limits_updated={request.warn_limits is not None}",
        )

        return state.dashboard_settings


@app.get("/api/errors")
def get_errors(_current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer"))):
    with state.state_lock:
        return {
            "errors": list(state.error_buffer)
        }


@app.post("/api/errors/clear")
def clear_errors(
    request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator")),
):
    with state.state_lock:
        cleared_count = len(state.error_buffer)
        state.error_buffer.clear()

    audit_event(request, "warnings_cleared", current_user["username"], f"count={cleared_count}")

    return {
        "errors": []
    }



@app.get("/api/snmp/live_data")
def get_snmp_live_data(_current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer"))):
    with state.state_lock:
        return dict(state.latest_snmp_data)


@app.get("/api/snmp/settings")
def get_snmp_settings(_current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer"))):
    with state.state_lock:
        return dict(state.snmp_settings)


@app.post("/api/snmp/settings")
def update_snmp_settings(
    settings: SnmpSettingsUpdateRequest,
    _current_user: dict = fastapi.Depends(require_roles("Administrator")),
):
    with state.state_lock:
        state.snmp_settings = settings.model_dump()
        state.save_persisted_state()

    snmp_service.close_snmp()
    if settings.enabled:
        snmp_service.init_snmp()

    return state.snmp_settings

@app.get("/api/history")
def history(
    range: str = "5m",
    start: str | None = None,
    end: str | None = None,
    _current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer")),
):
    influx_points = influx_service.query_history_from_influx(range, start, end)

    if influx_points is not None:
        return {
            "source": "influx",
            "range": range,
            "start": start,
            "end": end,
            "points": influx_points
        }

    memory_points = query_history_from_memory(range, start, end)

    return {
        "source": "memory",
        "range": range,
        "start": start,
        "end": end,
        "points": memory_points
    }


@app.get("/api/history/export.csv")
def export_history_csv(
    request: starlette.requests.Request,
    range: str = "5m",
    start: str | None = None,
    end: str | None = None,
    current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer")),
):
    influx_points = influx_service.query_history_from_influx(range, start, end)
    points = influx_points if influx_points is not None else query_history_from_memory(range, start, end)
    csv_text = build_history_csv(points)

    audit_event(
        request,
        "history_csv_exported",
        current_user["username"],
        f"range={range}; start={start}; end={end}; rows={len(points)}",
    )

    filename_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    return fastapi.responses.Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="amp_history_{filename_time}.csv"'
        },
    )


@app.post("/api/set_gain")
def set_gain(
    request: GainSetRequest,
    http_request: starlette.requests.Request,
    current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator")),
):
    try:
        serial_reader.send_gain_set(request.gain_set)
    except RuntimeError as e:
        raise fastapi.HTTPException(
            status_code=503,
            detail=str(e)
        )

    audit_event(http_request, "gain_setpoint_updated", current_user["username"], f"gain_set={request.gain_set}")

    return {
        "status": "ok",
        "gain_set": request.gain_set
    }
