#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMIN_PASSWORD_SUMMARY="existing account password unchanged"
DEFAULT_ADMIN_PASSWORD="Admin123!Amp"
cd "$PROJECT_DIR"

info() {
  printf '\n[%s] %s\n' "amp-dashboard" "$1"
}

fail() {
  printf '\n[amp-dashboard] ERROR: %s\n' "$1" >&2
  exit 1
}

require_linux() {
  [[ "$(uname -s)" == "Linux" ]] || fail "This installer requires Linux."

  if ! command -v apt-get >/dev/null 2>&1; then
    fail "This installer supports Debian, Ubuntu and Raspberry Pi OS."
  fi
}

systemd_is_running() {
  [[ "$(ps -p 1 -o comm= 2>/dev/null | tr -d ' ')" == "systemd" ]]
}

install_system_packages() {
  info "Installing required system packages"
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg iproute2 python3
}

install_docker_engine() {
  # Check for the Linux daemon, not only for the Docker client.
  if ! command -v dockerd >/dev/null 2>&1; then
    info "Installing Docker Engine inside Linux"
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sudo sh /tmp/get-docker.sh
  else
    info "Docker Engine is already installed"
  fi

  if ! docker compose version >/dev/null 2>&1; then
    info "Installing Docker Compose plugin"
    sudo apt-get install -y docker-compose-plugin
  fi

  if systemd_is_running; then
    sudo systemctl enable --now docker
  else
    sudo service docker start
  fi

  sudo usermod -aG docker "$USER" || true
}

detect_serial_device() {
  if [[ -e /dev/ttyACM0 ]]; then
    echo "/dev/ttyACM0"
  elif [[ -e /dev/ttyUSB0 ]]; then
    echo "/dev/ttyUSB0"
  else
    # /dev/null lets the web application start before USB is attached.
    echo "/dev/null"
  fi
}

prepare_environment_file() {
  local serial_device
  local influx_data_exists=false
  local persisted_state_exists=false
  serial_device="$(detect_serial_device)"

  if [[ ! -f .env ]]; then
    info "Creating .env configuration file"
    cp .env.example .env
  else
    info "Updating serial device in existing .env"
  fi

  set_env_value "SERIAL_DEVICE" "$serial_device"
  set_env_value "SERIAL_PORT" "$serial_device"
  if [[ -z "$(env_value SNMP_PORT)" ]]; then
    set_env_value "SNMP_PORT" "1161"
  fi

  if [[ -d data/influxdb2 ]]; then
    influx_data_exists=true
  fi

  if [[ -f data/persisted_state.json ]]; then
    persisted_state_exists=true
  fi

  if [[ "$persisted_state_exists" == false ]]; then
    if [[ -z "$(env_value INITIAL_ADMIN_PASSWORD)" ]]; then
      set_env_value "INITIAL_ADMIN_PASSWORD" "$DEFAULT_ADMIN_PASSWORD"
    fi
    ADMIN_PASSWORD_SUMMARY="$(env_value INITIAL_ADMIN_PASSWORD)"
  fi
  ensure_random_secret "SNMP_COMMUNITY" 24 false
  ensure_random_secret "INFLUX_TOKEN" 48 "$influx_data_exists"
  ensure_random_secret "INFLUX_INIT_PASSWORD" 32 "$influx_data_exists"

  mkdir -p data
  chmod 600 .env

  if [[ "$serial_device" == "/dev/null" ]]; then
    info "No serial adapter detected; starting dashboard without live serial data"
  else
    info "Using serial adapter ${serial_device}"
  fi
}

random_secret() {
  local length="$1"
  python3 -c "import secrets; print(secrets.token_urlsafe(${length}))"
}

env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" .env | tail -n1
}

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s#^${key}=.*#${key}=${value}#" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

ensure_random_secret() {
  local key="$1"
  local length="$2"
  local preserve_existing_data="$3"
  local current
  current="$(env_value "$key")"

  case "$current" in
    ""|admin|admin12345|my-super-token|public|replace-with-a-random-*)
      if [[ "$preserve_existing_data" == true ]]; then
        info "WARNING: ${key} is insecure, but existing InfluxDB data prevents automatic rotation"
        return
      fi
      current="$(random_secret "$length")"
      set_env_value "$key" "$current"
      ;;
  esac
}

start_dashboard() {
  info "Building and starting containers"
  sudo docker compose --profile dashboard up -d --build
  sudo systemctl start amp-dashboard.service
}

install_network_agent_service() {
  local python_path
  python_path="$(command -v python3)"

  info "Installing host network agent"
  sudo install -D -m 0755 "${PROJECT_DIR}/network_agent.py" /usr/local/lib/amp-dashboard/network_agent.py
  sudo tee /etc/systemd/system/amp-network-agent.service >/dev/null <<SERVICE
[Unit]
Description=Optical amplifier host network agent
After=NetworkManager.service

[Service]
Type=simple
User=root
Group=root
RuntimeDirectory=amp-dashboard
RuntimeDirectoryMode=0755
RuntimeDirectoryPreserve=yes
ExecStart=${python_path} /usr/local/lib/amp-dashboard/network_agent.py --socket /run/amp-dashboard/network-agent.sock
Restart=on-failure
RestartSec=2
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
RestrictAddressFamilies=AF_UNIX AF_NETLINK

[Install]
WantedBy=multi-user.target
SERVICE

  sudo systemctl daemon-reload
  sudo systemctl enable --now amp-network-agent.service
}

install_dashboard_service() {
  local docker_path
  docker_path="$(command -v docker)"

  info "Configuring dashboard to start automatically with Linux"
  sudo tee /etc/systemd/system/amp-dashboard.service >/dev/null <<SERVICE
[Unit]
Description=Optical amplifier dashboard containers
Requires=docker.service amp-network-agent.service
After=docker.service amp-network-agent.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=${docker_path} compose --profile dashboard up -d

[Install]
WantedBy=multi-user.target
SERVICE

  sudo systemctl daemon-reload
  sudo systemctl enable amp-dashboard.service
}

print_summary() {
  local dashboard_address
  dashboard_address="$(hostname -I 2>/dev/null | awk '{print $1}')"
  dashboard_address="${dashboard_address:-localhost}"

  cat <<SUMMARY

Installation finished.

Dashboard:
  http://${dashboard_address}:8000

InfluxDB:
  http://localhost:8086 (available only on the Linux server)

SNMP:
  UDP port $(env_value "SNMP_PORT")

Default login:
  username: admin
  password: ${ADMIN_PASSWORD_SUMMARY}

Useful commands:
  cd ${PROJECT_DIR}
  docker compose --profile dashboard logs -f app
  docker compose --profile dashboard restart app
  docker compose --profile dashboard down
  sudo systemctl status amp-dashboard.service
  sudo systemctl status amp-network-agent.service

If a serial adapter is connected later, rerun this installer so that .env is
updated from /dev/null to /dev/ttyACM0 or /dev/ttyUSB0.

You may need to close and reopen the Linux shell once before docker commands
work without sudo. The dashboard is already running.
SUMMARY
}

require_linux
systemd_is_running || fail "systemd must be running on the Linux server."
install_system_packages
install_docker_engine
prepare_environment_file
install_network_agent_service
install_dashboard_service
start_dashboard
print_summary