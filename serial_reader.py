import datetime
import time

import serial

import config
import influx_service
import parser
import state


def enrich_data(data: dict) -> dict:
    if "gain_actual" not in data:
        required = ["p_a_in", "p_a_out", "p_b_in", "p_b_out"]

        if all(key in data for key in required):
            gain_a = data["p_a_out"] - data["p_a_in"]
            gain_b = data["p_b_out"] - data["p_b_in"]
            data["gain_actual"] = (gain_a + gain_b) / 2.0

    if "gain_delta" not in data:
        if "gain_set" in data and "gain_actual" in data:
            data["gain_delta"] = data["gain_set"] - data["gain_actual"]

    return data


def serial_reader_loop():
    try:
        ser = serial.Serial(
            port=config.SERIAL_PORT,
            baudrate=config.SERIAL_BAUDRATE,
            timeout=1
        )

        with state.serial_lock:
            state.serial_port = ser

        with state.state_lock:
            state.serial_connected = True
            state.serial_error = None

        print(f"Połączono z portem {config.SERIAL_PORT}")

        time.sleep(2)

        while not state.stop_event.is_set():
            line = ser.readline().decode("utf-8", errors="replace").strip()

            if not line:
                continue

            data = parser.parse_line(line)

            if not data:
                continue

            data = enrich_data(data)

            now = datetime.datetime.now(datetime.timezone.utc).isoformat()

            with state.state_lock:
                state.latest_data = data
                state.last_update = now
                state.serial_connected = True
                state.serial_error = None

                state.history_buffer.append({
                    "time": now,
                    **data
                })

            influx_service.write_measurement(data)

            print("Odczyt:", data)

    except serial.SerialException as e:
        with state.state_lock:
            state.serial_connected = False
            state.serial_error = str(e)

        print("Błąd portu szeregowego:", e)

    finally:
        with state.serial_lock:
            if state.serial_port is not None:
                try:
                    state.serial_port.close()
                except serial.SerialException:
                    pass

                state.serial_port = None

        with state.state_lock:
            state.serial_connected = False


def send_gain_set(gain_set: float):
    command = f"SET_GAIN={gain_set:.2f}\n"

    with state.serial_lock:
        if state.serial_port is None:
            raise RuntimeError("Port szeregowy nie jest otwarty")

        state.serial_port.write(command.encode("utf-8"))
        state.serial_port.flush()

    influx_service.write_setpoint(gain_set)