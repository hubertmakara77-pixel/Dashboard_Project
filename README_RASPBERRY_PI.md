# Raspberry Pi installation

Run this command from the project directory:

```bash
bash install_raspberry_pi.sh
```

The installer:

- installs Docker and Docker Compose plugin,
- creates `.env` from `.env.example`,
- detects `/dev/ttyACM0` or `/dev/ttyUSB0` for the serial device,
- creates the local `data` directory,
- builds and starts the FastAPI dashboard and InfluxDB containers.

After installation the dashboard is available at:

```text
http://RASPBERRY_PI_IP:8000
```

Default login:

```text
username: admin
password: admin
```

Change serial device or service settings in `.env`:

```text
SERIAL_DEVICE=/dev/ttyACM0
SERIAL_PORT=/dev/ttyACM0
SERIAL_BAUDRATE=9600
```

Common maintenance commands:

```bash
sudo docker compose --profile dashboard logs -f app
sudo docker compose --profile dashboard restart app
sudo docker compose --profile dashboard down
sudo docker compose --profile dashboard up -d --build
```
