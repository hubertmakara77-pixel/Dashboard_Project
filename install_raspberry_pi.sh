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
  [[ "$(uname -s)" == "Linux" ]] || fail "This installer requires Linux or WSL."

  if ! command -v apt-get >/dev/null 2>&1; then
    fail "This installer currently supports Debian, Ubuntu, Raspberry Pi OS and WSL distributions based on them."
  fi
}

is_wsl() {
  grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null
}

systemd_is_running() {
  [[ "$(ps -p 1 -o comm= 2>/dev/null | tr -d ' ')" == "systemd" ]]
}

enable_systemd_in_wsl() {
  is_wsl || return 0
  systemd_is_running && return 0

  info "Enabling systemd in WSL"

  if [[ ! -f /etc/wsl.conf ]]; then
    printf '[boot]\nsystemd=true\n' | sudo tee /etc/wsl.conf >/dev/null
  elif grep -q '^\[boot\]' /etc/wsl.conf; then
    if grep -q '^systemd=' /etc/wsl.conf; then
      sudo sed -i 's/^systemd=.*/systemd=true/' /etc/wsl.conf
    else
      sudo sed -i '/^\[boot\]/a systemd=true' /etc/wsl.conf
    fi
  else
    printf '\n[boot]\nsystemd=true\n' | sudo tee -a /etc/wsl.conf >/dev/null
  fi

  cat <<'MESSAGE'

Systemd has been enabled for this WSL distribution.

Run the following command once in Windows PowerShell:

  wsl --shutdown

Then open WSL again and rerun:

  cd ~/Dashboard_Project
  bash install_raspberry_pi.sh
MESSAGE
  exit 0
}

install_system_packages() {
  info "Installing required system packages"
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg
}

install_docker_engine() {
  # A Docker Desktop integration may leave the CLI available in WSL without
  # installing the Linux daemon. Check for dockerd, not only for docker.
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
}

install_dashboard_service() {
  local docker_path
  docker_path="$(command -v docker)"

  info "Configuring dashboard to start automatically with Linux"
  sudo tee /etc/systemd/system/amp-dashboard.service >/dev/null <<SERVICE
[Unit]
Description=Optical amplifier dashboard containers
Requires=docker.service
After=docker.service network-online.target
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
  if is_wsl; then
    dashboard_address="localhost"
  else
    dashboard_address="$(hostname -I 2>/dev/null | awk '{print $1}')"
    dashboard_address="${dashboard_address:-localhost}"
  fi

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

If a serial adapter is connected later, rerun this installer so that .env is
updated from /dev/null to /dev/ttyACM0 or /dev/ttyUSB0.

You may need to close and reopen the Linux shell once before docker commands
work without sudo. The dashboard is already running.
SUMMARY
}

require_linux
enable_systemd_in_wsl
install_system_packages
install_docker_engine
prepare_environment_file
install_dashboard_service
start_dashboard
print_summary
