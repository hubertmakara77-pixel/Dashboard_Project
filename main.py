import contextlib
import datetime
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

    print("Zamykanie aplikacji...")

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
def latest():
    with state.state_lock:
        return {
            "connected": state.serial_connected,
            "error": state.serial_error,
            "last_update": state.last_update,
            "data": state.latest_data
        }


@app.get("/api/status")
def status():
    with state.state_lock:
        return {
            "device": config.DEVICE_NAME,
            "serial_port": config.SERIAL_PORT,
            "serial_connected": state.serial_connected,
            "serial_error": state.serial_error,
            "influx_enabled": config.INFLUX_ENABLED
        }


@app.get("/api/history")
def history(range: str = "5m"):
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
def set_gain(request: GainSetRequest):
    serial_reader.send_gain_set(request.gain_set)

    return {
        "status": "ok",
        "gain_set": request.gain_set
    }