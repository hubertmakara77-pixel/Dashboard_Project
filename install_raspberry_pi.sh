#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

info() {
  printf '\n[%s] %s\n' "amp-dashboard" "$1"
}

require_linux() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This installer is intended for Raspberry Pi OS or another Linux system."
    exit 1
  fi
}

install_system_packages() {
  info "Installing Docker and basic system packages"
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg

  if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sudo sh /tmp/get-docker.sh
  fi

  sudo systemctl enable --now docker

  if ! sudo docker compose version >/dev/null 2>&1; then
    sudo apt-get install -y docker-compose-plugin || true
  fi

  if ! sudo docker compose version >/dev/null 2>&1; then
    echo "Docker is installed, but Docker Compose plugin is missing."
    echo "Install docker-compose-plugin and run this script again."
    exit 1
  fi
}

prepare_permissions() {
  info "Preparing user permissions"
  sudo usermod -aG docker "$USER" || true
  sudo usermod -aG dialout "$USER" || true
}

detect_serial_device() {
  if [[ -e /dev/ttyACM0 ]]; then
    echo "/dev/ttyACM0"
  elif [[ -e /dev/ttyUSB0 ]]; then
    echo "/dev/ttyUSB0"
  else
    echo "/dev/ttyACM0"
  fi
}

prepare_environment_file() {
  local serial_device
  serial_device="$(detect_serial_device)"

  if [[ ! -f .env ]]; then
    info "Creating .env configuration file"
    cp .env.example .env
    sed -i "s#^SERIAL_DEVICE=.*#SERIAL_DEVICE=${serial_device}#" .env
    sed -i "s#^SERIAL_PORT=.*#SERIAL_PORT=${serial_device}#" .env
  else
    info ".env already exists, keeping current configuration"
  fi

  mkdir -p data
}

start_dashboard() {
  info "Building and starting containers"
  sudo docker compose --profile dashboard up -d --build
}

print_summary() {
  local ip_address
  ip_address="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -z "${ip_address}" ]]; then
    ip_address="raspberrypi.local"
  fi

  cat <<SUMMARY

Installation finished.

Dashboard:
  http://${ip_address}:8000

Default login:
  username: admin
  password: admin

Useful commands:
  sudo docker compose --profile dashboard logs -f app
  sudo docker compose --profile dashboard restart app
  sudo docker compose --profile dashboard down

If the serial adapter is not /dev/ttyACM0, edit .env and change SERIAL_DEVICE and SERIAL_PORT.
After the first installation, logging out and back in lets your user run docker without sudo.
SUMMARY
}

require_linux
install_system_packages
prepare_permissions
prepare_environment_file
start_dashboard
print_summary
