#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ADMIN_PASSWORD_SUMMARY="existing account password unchanged"
RADIUS_SUMMARY=""
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
  sudo apt-get install -y ca-certificates curl gnupg iproute2 logrotate python3 rsyslog systemd-timesyncd
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
  local radius_mode
  serial_device="$(detect_serial_device)"

  if [[ ! -f .env ]]; then
    info "Creating .env configuration file"
    cp .env.example .env
  else
    info "Updating serial device in existing .env"
  fi

  prompt_radius_configuration

  # Hasło Dashboardu z poprzednich wersji nie jest już używane. RADIUS jest
  # jedynym źródłem haseł, więc usuń także pozostawioną wartość z .env.
  sed -i '/^INITIAL_ADMIN_PASSWORD=/d' .env

  set_env_value "SERIAL_DEVICE" "$serial_device"
  set_env_value "SERIAL_PORT" "$serial_device"
  if [[ -z "$(env_value SNMP_PORT)" ]]; then
    set_env_value "SNMP_PORT" "1161"
  fi

  if [[ -d data/influxdb2 ]]; then
    influx_data_exists=true
  fi

  ensure_random_secret "SNMP_COMMUNITY" 24 false
  ensure_random_secret "INFLUX_TOKEN" 48 "$influx_data_exists"
  ensure_random_secret "INFLUX_INIT_PASSWORD" 32 "$influx_data_exists"
  set_env_default "RADIUS_MODE" "local"
  set_env_default "RADIUS_SERVER" "radius"
  set_env_default "RADIUS_PORT" "1812"
  set_env_default "RADIUS_TIMEOUT_SECONDS" "3"
  set_env_default "RADIUS_RETRIES" "1"
  set_env_default "RADIUS_NAS_IDENTIFIER" "amp-dashboard"
  set_env_default "NTP_SERVER" "tempus1.gum.gov.pl"
  set_env_default "NTP_SERVER_FALLBACK_IP" "194.146.251.100"
  set_env_default "NTP_PORT" "123"
  set_env_default "NTP_TIMEOUT_SECONDS" "3"
  set_env_default "NTP_CACHE_SECONDS" "15"
  radius_mode="$(env_value RADIUS_MODE)"
  case "$radius_mode" in
    local)
      set_env_value "RADIUS_SERVER" "radius"
      ensure_random_secret "RADIUS_SECRET" 48 false
      ensure_random_secret "RADIUS_ADMIN_PASSWORD" 24 false
      ADMIN_PASSWORD_SUMMARY="$(env_value RADIUS_ADMIN_PASSWORD)"
      RADIUS_SUMMARY="local FreeRADIUS container on UDP port $(env_value RADIUS_PORT)"
      ;;
    remote)
      [[ -n "$(env_value RADIUS_SERVER)" ]] || fail "RADIUS_SERVER is required when RADIUS_MODE=remote"
      [[ -n "$(env_value RADIUS_SECRET)" ]] || fail "RADIUS_SECRET is required when RADIUS_MODE=remote"
      ADMIN_PASSWORD_SUMMARY="managed by the remote RADIUS server"
      RADIUS_SUMMARY="remote server $(env_value RADIUS_SERVER):$(env_value RADIUS_PORT)"
      ;;
    *)
      fail "RADIUS_MODE must be 'local' or 'remote'"
      ;;
  esac

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

set_env_default() {
  local key="$1"
  local value="$2"
  if [[ -z "$(env_value "$key")" ]]; then
    set_env_value "$key" "$value"
  fi
}

prompt_radius_configuration() {
  local current_mode
  local selected_mode
  local radius_server
  local radius_port
  local radius_secret
  local entered_secret=""
  local entered_server=""
  local entered_port=""
  local confirmation

  # Przy uruchomieniu automatycznym nie ma terminala. Wtedy instalator używa
  # istniejącego .env i nie blokuje startu systemd oczekiwaniem na odpowiedź.
  [[ -t 0 ]] || return

  current_mode="$(env_value RADIUS_MODE)"
  current_mode="${current_mode:-local}"
  radius_server="$(env_value RADIUS_SERVER)"
  radius_server="${radius_server:-radius}"
  radius_port="$(env_value RADIUS_PORT)"
  radius_port="${radius_port:-1812}"
  radius_secret="$(env_value RADIUS_SECRET)"

  info "RADIUS configuration"
  read -r -p "RADIUS mode [local/remote] (${current_mode}): " selected_mode
  selected_mode="${selected_mode:-$current_mode}"

  case "$selected_mode" in
    local)
      radius_server="radius"
      ;;
    remote)
      read -r -p "Remote RADIUS server (${radius_server}): " entered_server
      radius_server="${entered_server:-$radius_server}"
      read -r -p "Remote RADIUS UDP port (${radius_port}): " entered_port
      radius_port="${entered_port:-$radius_port}"

      while true; do
        if [[ "$current_mode" == "remote" && -n "$radius_secret" ]]; then
          read -r -s -p "RADIUS shared secret (Enter keeps the current secret): " entered_secret
          printf '\n'
          entered_secret="${entered_secret:-$radius_secret}"
        else
          read -r -s -p "RADIUS shared secret: " entered_secret
          printf '\n'
        fi

        [[ -n "$entered_secret" ]] && break
        info "RADIUS shared secret cannot be empty"
      done
      radius_secret="$entered_secret"
      ;;
    *)
      fail "RADIUS mode must be 'local' or 'remote'"
      ;;
  esac

  printf '\nRADIUS mode: %s\n' "$selected_mode"
  if [[ "$selected_mode" == "remote" ]]; then
    printf 'RADIUS server: %s:%s\n' "$radius_server" "$radius_port"
    printf 'RADIUS shared secret: configured (hidden)\n'
  else
    printf 'RADIUS server: local FreeRADIUS container\n'
  fi

  read -r -p "Apply this RADIUS configuration? [y/N]: " confirmation
  case "$confirmation" in
    y|Y|yes|YES)
      set_env_value "RADIUS_MODE" "$selected_mode"
      set_env_value "RADIUS_SERVER" "$radius_server"
      set_env_value "RADIUS_PORT" "$radius_port"
      if [[ "$selected_mode" == "remote" ]]; then
        set_env_value "RADIUS_SECRET" "$radius_secret"
      fi
      ;;
    *)
      fail "RADIUS configuration was not confirmed"
      ;;
  esac
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

prepare_local_radius() {
  local radius_secret
  local radius_admin_password
  if [[ "$(env_value RADIUS_MODE)" != "local" ]]; then
    info "Using remote RADIUS server; skipping local FreeRADIUS configuration"
    return
  fi

  radius_secret="$(env_value RADIUS_SECRET)"
  radius_admin_password="$(env_value RADIUS_ADMIN_PASSWORD)"

  info "Preparing local FreeRADIUS configuration"
  mkdir -p radius

  # Docker tworzy katalog w miejscu brakujacego bind-mountu. Naprawiamy
  # bezpiecznie tylko pusty katalog; rmdir odmowi usuniecia danych.
  if [[ -d radius/clients.conf ]]; then
    info "Replacing Docker-created radius/clients.conf directory with a file"
    sudo rmdir radius/clients.conf || fail "radius/clients.conf is a non-empty directory; move its contents and rerun the installer"
  fi
  if [[ -d radius/authorize ]]; then
    info "Replacing Docker-created radius/authorize directory with a file"
    sudo rmdir radius/authorize || fail "radius/authorize is a non-empty directory; move its contents and rerun the installer"
  fi

  # Ten plik musi zawsze odpowiadać RADIUS_SECRET z .env, również po zmianie
  # trybu remote -> local albo świadomej rotacji sekretu.
  cat > radius/clients.conf <<RADIUS_CLIENT
client dashboard {
    ipaddr = 172.16.0.0/12
    secret = ${radius_secret}
}
RADIUS_CLIENT

  if [[ ! -f radius/authorize ]]; then
    cat > radius/authorize <<RADIUS_USER
admin Cleartext-Password := "${radius_admin_password}"
RADIUS_USER
  else
    info "Keeping existing radius/authorize; its credentials remain unchanged"
    ADMIN_PASSWORD_SUMMARY="defined in radius/authorize"
  fi

  # Bind-mounty zachowuja uprawnienia hosta, a FreeRADIUS dziala w kontenerze
  # jako nieuprzywilejowany uzytkownik `freerad` i musi moc odczytac te pliki.
  chmod 644 radius/clients.conf radius/authorize
}

configure_time_sync() {
  local ntp_server
  local fallback_server
  ntp_server="$(env_value NTP_SERVER)"
  fallback_server="$(env_value NTP_SERVER_FALLBACK_IP)"

  info "Configuring host clock synchronization with NTP"
  sudo install -d -m 0755 /etc/systemd/timesyncd.conf.d
  sudo tee /etc/systemd/timesyncd.conf.d/amp-dashboard.conf >/dev/null <<TIMESYNC
[Time]
NTP=${ntp_server}
FallbackNTP=${fallback_server}
TIMESYNC
  sudo timedatectl set-ntp true
  sudo systemctl enable --now systemd-timesyncd.service
  sudo systemctl restart systemd-timesyncd.service
}

configure_system_syslog() {
  info "Configuring system rsyslog for amp-dashboard"
  sudo install -d -o root -g adm -m 0750 /var/log/amp-dashboard
  sudo touch /var/log/amp-dashboard/amp-dashboard.log
  sudo chown root:adm /var/log/amp-dashboard/amp-dashboard.log
  sudo chmod 0640 /var/log/amp-dashboard/amp-dashboard.log

  sudo tee /etc/rsyslog.d/30-amp-dashboard.conf >/dev/null <<'RSYSLOG'
module(load="imudp")
$AllowedSender UDP, 127.0.0.1, 172.16.0.0/12

ruleset(name="ampDashboard") {
    if ($programname == "amp-dashboard") then {
        action(
            type="omfile"
            file="/var/log/amp-dashboard/amp-dashboard.log"
            fileOwner="root"
            fileGroup="adm"
            fileCreateMode="0640"
        )
        stop
    }
}

input(type="imudp" port="514" ruleset="ampDashboard")
RSYSLOG

  sudo tee /etc/logrotate.d/amp-dashboard >/dev/null <<'LOGROTATE'
/var/log/amp-dashboard/amp-dashboard.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 root adm
    postrotate
        systemctl kill -s HUP rsyslog.service >/dev/null 2>&1 || true
    endscript
}
LOGROTATE

  sudo rsyslogd -N1
  sudo systemctl enable --now rsyslog.service
  sudo systemctl restart rsyslog.service

  # Jednorazowa migracja starych plikow aplikacyjnych do jedynego logu systemowego.
  for legacy_log in /var/log/amp-dashboard.log data/syslog.log data/audit.log; do
    if [[ -f "$legacy_log" ]]; then
      sudo sh -c 'cat "$1" >> /var/log/amp-dashboard/amp-dashboard.log' sh "$legacy_log"
      sudo rm -f "$legacy_log"
    fi
  done
}

start_dashboard() {
  info "Building and starting containers"
  if [[ "$(env_value RADIUS_MODE)" == "local" ]]; then
    sudo docker compose --profile dashboard --profile local-radius up -d --build
  else
    # Usuń wcześniejszy lokalny kontener również wtedy, gdy miał restart policy.
    sudo docker compose --profile local-radius rm -sf radius
    sudo docker compose --profile dashboard up -d --build
  fi
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
  local radius_profile=""
  docker_path="$(command -v docker)"

  if [[ "$(env_value RADIUS_MODE)" == "local" ]]; then
    radius_profile="--profile local-radius"
  fi

  info "Configuring dashboard to start automatically with Linux"
  sudo tee /etc/systemd/system/amp-dashboard.service >/dev/null <<SERVICE
[Unit]
Description=Optical amplifier dashboard containers
Requires=docker.service amp-network-agent.service
After=docker.service amp-network-agent.service systemd-timesyncd.service network-online.target
Wants=network-online.target systemd-timesyncd.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=${docker_path} compose --profile dashboard ${radius_profile} up -d

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

RADIUS:
  ${RADIUS_SUMMARY}

Time synchronization:
  systemd-timesyncd uses $(env_value "NTP_SERVER")

System log:
  /var/log/amp-dashboard/amp-dashboard.log (managed by rsyslog and logrotate)

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
prepare_local_radius
configure_time_sync
configure_system_syslog
install_network_agent_service
install_dashboard_service
start_dashboard
print_summary
