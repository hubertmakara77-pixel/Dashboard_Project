#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
  sudo apt-get install -y ca-certificates curl gnupg iproute2
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
  serial_device="$(detect_serial_device)"

  if [[ ! -f .env ]]; then
    info "Creating .env configuration file"
    cp .env.example .env
  else
    info "Updating serial device in existing .env"
  fi

  sed -i "s#^SERIAL_DEVICE=.*#SERIAL_DEVICE=${serial_device}#" .env
  sed -i "s#^SERIAL_PORT=.*#SERIAL_PORT=${serial_device}#" .env
  mkdir -p data

  if [[ "$serial_device" == "/dev/null" ]]; then
    info "No serial adapter detected; starting dashboard without live serial data"
  else
    info "Using serial adapter ${serial_device}"
  fi
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
  http://${dashboard_address}:8086

Default login:
  username: admin
  password: admin

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
