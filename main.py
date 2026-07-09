import contextlib
import datetime
import secrets
import threading

import fastapi
import fastapi.staticfiles
import fastapi.templating
import pydantic
import starlette.requests

import config
import influx_service
import serial_reader
import state


class GainSetRequest(pydantic.BaseModel):
    gain_set: float


class DashboardSettingsRequest(pydantic.BaseModel):
    gain_tolerance: float | None = None
    warn_limits: dict[str, dict[str, float | None]] | None = None


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


def query_history_from_memory(range_value: str):
    start_time = parse_memory_range(range_value)

    with state.state_lock:
        points = list(state.history_buffer)

    if start_time is None:
        return points

    filtered_points = []

    for point in points:
        point_time = datetime.datetime.fromisoformat(point["time"])

        if point_time >= start_time:
            filtered_points.append(point)

    return filtered_points


@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    influx_service.init_influx()

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


@app.post("/api/auth/login")
def login(request: LoginRequest, response: fastapi.Response):
    username = normalize_username(request.username)

    with state.state_lock:
        user = find_access_user(username)

        if (
            user is None
            or not user["active"]
            or not state.verify_password(request.password, user["password_hash"], user["password_salt"])
        ):
            raise fastapi.HTTPException(status_code=401, detail="Invalid username or password")

        token = create_session(username)
        public_user = state.access_user_public(user)

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
def logout(response: fastapi.Response, session_token: str | None = fastapi.Cookie(default=None)):
    with state.state_lock:
        if session_token:
            state.auth_sessions.pop(session_token, None)

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


@app.post("/api/access/users")
def create_access_user(
    request: AccessUserCreateRequest,
    _current_user: dict = fastapi.Depends(require_roles("Administrator")),
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

        return state.access_user_public(user)


@app.put("/api/access/users/{username}")
def update_access_user(
    username: str,
    request: AccessUserUpdateRequest,
    _current_user: dict = fastapi.Depends(require_roles("Administrator")),
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

        return state.access_user_public(user)


@app.delete("/api/access/users/{username}")
def delete_access_user(
    username: str,
    _current_user: dict = fastapi.Depends(require_roles("Administrator")),
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

    return {
        "status": "ok"
    }


@app.post("/api/settings")
def update_settings(
    request: DashboardSettingsRequest,
    _current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator")),
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

        return state.dashboard_settings


@app.get("/api/errors")
def get_errors(_current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer"))):
    with state.state_lock:
        return {
            "errors": list(state.error_buffer)
        }


@app.post("/api/errors/clear")
def clear_errors(_current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator"))):
    with state.state_lock:
        state.error_buffer.clear()

    return {
        "errors": []
    }


@app.get("/api/history")
def history(
    range: str = "5m",
    _current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator", "Viewer")),
):
    influx_points = influx_service.query_history_from_influx(range)

    if influx_points is not None:
        return {
            "source": "influx",
            "range": range,
            "points": influx_points
        }

    memory_points = query_history_from_memory(range)

    return {
        "source": "memory",
        "range": range,
        "points": memory_points
    }


@app.post("/api/set_gain")
def set_gain(
    request: GainSetRequest,
    _current_user: dict = fastapi.Depends(require_roles("Administrator", "Operator")),
):
    try:
        serial_reader.send_gain_set(request.gain_set)
    except RuntimeError as e:
        raise fastapi.HTTPException(
            status_code=503,
            detail=str(e)
        )

    return {
        "status": "ok",
        "gain_set": request.gain_set
    }

