#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
    fail "This installer requires a Debian-family Linux system with apt."
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
  local docker_arch
  local docker_codename

  # Check for the Linux daemon, not only for the Docker client.
  if ! command -v dockerd >/dev/null 2>&1; then
    info "Installing Docker Engine inside Linux"
    # Configure the repository directly instead of using get.docker.com. The
    # convenience script hides apt output and installs optional packages such
    # as docker-model-plugin which are unnecessary on embedded devices.
    # Force IPv4 because some appliance networks advertise unusable IPv6.
    . /etc/os-release
    docker_codename="${VERSION_CODENAME:-}"
    [[ "$ID" == "debian" && -n "$docker_codename" ]] || fail "Docker installation requires Debian with VERSION_CODENAME"
    docker_arch="$(dpkg --print-architecture)"
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /tmp/docker.asc
    gpg --dearmor --yes --output /tmp/docker.gpg /tmp/docker.asc
    sudo install -d -m 0755 /etc/apt/keyrings
    sudo install -m 0644 /tmp/docker.gpg /etc/apt/keyrings/docker.gpg
    sudo rm -f /etc/apt/sources.list.d/docker.sources /etc/apt/keyrings/docker.asc
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian %s stable\n' \
      "$docker_arch" "$docker_codename" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get -o Acquire::ForceIPv4=true update
    sudo apt-get -o Acquire::ForceIPv4=true install -y \
      docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  else
    info "Docker Engine is already installed"
  fi

  if ! docker compose version >/dev/null 2>&1; then
    info "Installing Docker Compose plugin"
    sudo apt-get -o Acquire::ForceIPv4=true install -y docker-compose-plugin
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

ensure_device_name() {
  local current_name
  local prefix
  local hardware_id=""
  local mac_address=""

  current_name="$(env_value DEVICE_NAME)"
  if [[ -n "$current_name" && "$current_name" != "optical_amp_1" ]]; then
    [[ "$current_name" =~ ^[A-Za-z0-9._-]+$ ]] || fail "DEVICE_NAME may contain only letters, digits, dots, underscores and hyphens"
    return
  fi

  prefix="$(hostname -s | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g; s/^-*//; s/-*$//')"
  prefix="${prefix:-beaglebone}"

  if [[ -r /sys/class/net/eth0/address ]]; then
    mac_address="$(tr -d ':\r\n' < /sys/class/net/eth0/address)"
    if [[ "$mac_address" =~ ^[0-9a-fA-F]{12}$ && "$mac_address" != "000000000000" ]]; then
      hardware_id="${mac_address: -8}"
    fi
  fi

  if [[ -z "$hardware_id" && -r /etc/machine-id ]]; then
    hardware_id="$(tr -d -- '-\r\n' < /etc/machine-id | head -c 8)"
  fi

  if [[ ! "$hardware_id" =~ ^[0-9a-fA-F]{8}$ ]]; then
    hardware_id="$(python3 -c 'import secrets; print(secrets.token_hex(4))')"
  fi

  current_name="${prefix}-${hardware_id,,}"
  set_env_value "DEVICE_NAME" "$current_name"
  info "Assigned stable device identifier ${current_name}"
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

  prompt_radius_configuration
  prompt_remote_syslog_configuration

  # Hasło Dashboardu z poprzednich wersji nie jest już używane. RADIUS jest
  # jedynym źródłem haseł, więc usuń także pozostawioną wartość z .env.
  sed -i '/^INITIAL_ADMIN_PASSWORD=/d' .env

  set_env_value "SERIAL_PORT" "$([[ "$serial_device" == "/dev/null" ]] && printf '/host/dev/ttyACM0' || printf '/host%s' "$serial_device")"
  sed -i '/^SERIAL_DEVICE=/d' .env
  ensure_device_name
  if [[ -z "$(env_value SNMP_PORT)" ]]; then
    set_env_value "SNMP_PORT" "1161"
  fi

  ensure_random_secret "SNMP_COMMUNITY" 24
  set_env_default "DATABASE_FILE" "/app/data/measurements.db"
  set_env_default "DATABASE_MAX_RECORDS" "250000"
  set_env_default "RADIUS_PORT" "1812"
  set_env_default "RADIUS_TIMEOUT_SECONDS" "3"
  set_env_default "RADIUS_RETRIES" "1"
  if [[ -z "$(env_value RADIUS_NAS_IDENTIFIER)" || "$(env_value RADIUS_NAS_IDENTIFIER)" == "amp-dashboard" ]]; then
    set_env_value "RADIUS_NAS_IDENTIFIER" "$(env_value DEVICE_NAME)"
  fi
  set_env_default "NTP_SERVER" "tempus1.gum.gov.pl"
  set_env_default "NTP_SERVER_FALLBACK_IP" "194.146.251.100"
  set_env_default "NTP_PORT" "123"
  set_env_default "NTP_TIMEOUT_SECONDS" "3"
  set_env_default "NTP_CACHE_SECONDS" "15"
  set_env_default "REMOTE_SYSLOG_ENABLED" "false"
  set_env_default "REMOTE_SYSLOG_PORT" "514"
  set_env_default "REMOTE_SYSLOG_PROTOCOL" "tcp"
  set_env_default "SYSLOG_HEARTBEAT_SECONDS" "300"
  validate_radius_configuration
  RADIUS_SUMMARY="remote server $(env_value RADIUS_SERVER):$(env_value RADIUS_PORT)"

  # Remove settings from obsolete InfluxDB and local RADIUS versions.
  sed -i '/^INFLUX_/d; /^MEASUREMENT_NAME=/d; /^SETPOINT_MEASUREMENT_NAME=/d; /^RADIUS_MODE=/d; /^RADIUS_ADMIN_PASSWORD=/d' .env

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
  local escaped_value
  escaped_value="$(printf '%s' "$value" | sed 's/[\\&#]/\\&/g')"
  if grep -q "^${key}=" .env; then
    sed -i "s#^${key}=.*#${key}=${escaped_value}#" .env
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
  local radius_server radius_port radius_secret entered_value confirmation

  [[ -t 0 ]] || return

  radius_server="$(env_value RADIUS_SERVER)"
  [[ "$radius_server" == "radius" ]] && radius_server=""
  radius_port="$(env_value RADIUS_PORT)"
  radius_port="${radius_port:-1812}"
  radius_secret="$(env_value RADIUS_SECRET)"

  info "Remote RADIUS configuration"
  read -r -p "RADIUS server address (${radius_server}): " entered_value
  radius_server="${entered_value:-$radius_server}"
  read -r -p "RADIUS UDP port (${radius_port}): " entered_value
  radius_port="${entered_value:-$radius_port}"
  if [[ -n "$radius_secret" ]]; then
    read -r -s -p "RADIUS shared secret (Enter keeps the current secret): " entered_value
  else
    read -r -s -p "RADIUS shared secret: " entered_value
  fi
  printf '\n'
  radius_secret="${entered_value:-$radius_secret}"

  printf '\nRADIUS: %s:%s\n' "$radius_server" "$radius_port"
  printf 'RADIUS shared secret: configured (hidden)\n'
  read -r -p "Apply this remote services configuration? [y/N]: " confirmation
  case "$confirmation" in
    y|Y|yes|YES)
      set_env_value "RADIUS_SERVER" "$radius_server"
      set_env_value "RADIUS_PORT" "$radius_port"
      set_env_value "RADIUS_SECRET" "$radius_secret"
      ;;
    *) fail "RADIUS configuration was not confirmed" ;;
  esac
}

validate_radius_configuration() {
  local radius_server radius_port
  radius_server="$(env_value RADIUS_SERVER)"
  radius_port="$(env_value RADIUS_PORT)"

  [[ -n "$radius_server" && "$radius_server" != "radius" && "$radius_server" != "localhost" ]] || fail "RADIUS_SERVER must point to an external server"
  [[ "$radius_port" =~ ^[0-9]+$ ]] && (( radius_port >= 1 && radius_port <= 65535 )) || fail "RADIUS_PORT must be between 1 and 65535"
  [[ -n "$(env_value RADIUS_SECRET)" ]] || fail "RADIUS_SECRET for the remote server is required"
}

prompt_remote_syslog_configuration() {
  local current_enabled
  local remote_host
  local remote_port
  local remote_protocol
  local choice
  local entered_value
  local confirmation

  [[ -t 0 ]] || return

  current_enabled="$(env_value REMOTE_SYSLOG_ENABLED)"
  remote_host="$(env_value REMOTE_SYSLOG_HOST)"
  remote_port="$(env_value REMOTE_SYSLOG_PORT)"
  remote_port="${remote_port:-514}"
  remote_protocol="$(env_value REMOTE_SYSLOG_PROTOCOL)"
  remote_protocol="${remote_protocol:-tcp}"

  info "Remote syslog configuration"
  case "${current_enabled,,}" in
    true|yes|1|on)
      read -r -p "Forward dashboard logs to a remote syslog server? [Y/n]: " choice
      choice="${choice:-yes}"
      ;;
    *)
      read -r -p "Forward dashboard logs to a remote syslog server? [y/N]: " choice
      choice="${choice:-no}"
      ;;
  esac

  case "${choice,,}" in
    n|no)
      set_env_value "REMOTE_SYSLOG_ENABLED" "false"
      info "Remote syslog forwarding disabled; the local log remains enabled"
      return
      ;;
    y|yes) ;;
    *) fail "Answer yes or no for remote syslog forwarding" ;;
  esac

  read -r -p "Remote syslog server address (${remote_host}): " entered_value
  remote_host="${entered_value:-$remote_host}"
  read -r -p "Remote syslog port (${remote_port}): " entered_value
  remote_port="${entered_value:-$remote_port}"
  read -r -p "Protocol [tcp/udp] (${remote_protocol}): " entered_value
  remote_protocol="${entered_value:-$remote_protocol}"
  remote_protocol="${remote_protocol,,}"

  printf '\nRemote syslog: %s:%s over %s\n' "$remote_host" "$remote_port" "$remote_protocol"
  printf 'The local log will also remain enabled.\n'
  read -r -p "Apply this remote syslog configuration? [y/N]: " confirmation
  case "$confirmation" in
    y|Y|yes|YES)
      set_env_value "REMOTE_SYSLOG_ENABLED" "true"
      set_env_value "REMOTE_SYSLOG_HOST" "$remote_host"
      set_env_value "REMOTE_SYSLOG_PORT" "$remote_port"
      set_env_value "REMOTE_SYSLOG_PROTOCOL" "$remote_protocol"
      ;;
    *) fail "Remote syslog configuration was not confirmed" ;;
  esac
}

ensure_random_secret() {
  local key="$1"
  local length="$2"
  local current
  current="$(env_value "$key")"

  case "$current" in
    ""|admin|admin12345|my-super-token|public|replace-with-a-random-*)
      current="$(random_secret "$length")"
      set_env_value "$key" "$current"
      ;;
  esac
}

cleanup_legacy_local_configuration() {
  if [[ -e radius/authorize || -e radius/clients.conf ]]; then
    info "Removing obsolete local FreeRADIUS configuration"
    sudo rm -f radius/authorize radius/clients.conf
    sudo rmdir radius 2>/dev/null || true
  fi
  if [[ -d data/influxdb2 ]]; then
    info "Legacy InfluxDB data remains in data/influxdb2 and is not used by the dashboard"
  fi
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
  local remote_enabled
  local remote_host
  local remote_port
  local remote_protocol
  remote_enabled="$(env_value REMOTE_SYSLOG_ENABLED)"
  remote_host="$(env_value REMOTE_SYSLOG_HOST)"
  remote_port="$(env_value REMOTE_SYSLOG_PORT)"
  remote_protocol="$(env_value REMOTE_SYSLOG_PROTOCOL)"

  case "${remote_enabled,,}" in
    true|yes|1|on)
      [[ -n "$remote_host" ]] || fail "REMOTE_SYSLOG_HOST is required when remote syslog is enabled"
      [[ "$remote_host" =~ ^[A-Za-z0-9._:-]+$ ]] || fail "REMOTE_SYSLOG_HOST contains unsupported characters"
      [[ "$remote_port" =~ ^[0-9]+$ ]] && (( remote_port >= 1 && remote_port <= 65535 )) || fail "REMOTE_SYSLOG_PORT must be between 1 and 65535"
      [[ "$remote_protocol" == "tcp" || "$remote_protocol" == "udp" ]] || fail "REMOTE_SYSLOG_PROTOCOL must be 'tcp' or 'udp'"
      remote_enabled=true
      ;;
    false|no|0|off|"")
      remote_enabled=false
      ;;
    *)
      fail "REMOTE_SYSLOG_ENABLED must be true or false"
      ;;
  esac

  info "Configuring system rsyslog for amp-dashboard"
  sudo install -d -o root -g adm -m 0750 /var/log/amp-dashboard
  sudo touch /var/log/amp-dashboard/amp-dashboard.log
  sudo chown root:adm /var/log/amp-dashboard/amp-dashboard.log
  sudo chmod 0640 /var/log/amp-dashboard/amp-dashboard.log

  sudo tee /etc/rsyslog.d/30-amp-dashboard.conf >/dev/null <<'RSYSLOG'
module(load="imudp")
$AllowedSender UDP, 127.0.0.1, 172.16.0.0/12

template(name="ampDashboardLine" type="string" string="%timereported:::date-rfc3339% %msg:2:$%\n")

ruleset(name="ampDashboard") {
    if ($programname == "amp-dashboard") then {
        action(
            type="omfile"
            file="/var/log/amp-dashboard/amp-dashboard.log"
            fileOwner="root"
            fileGroup="adm"
            fileCreateMode="0640"
            template="ampDashboardLine"
        )
RSYSLOG

  if [[ "$remote_enabled" == true ]]; then
    sudo tee -a /etc/rsyslog.d/30-amp-dashboard.conf >/dev/null <<RSYSLOG_FORWARD
        action(
            type="omfwd"
            target="${remote_host}"
            port="${remote_port}"
            protocol="${remote_protocol}"
            action.resumeRetryCount="-1"
            queue.type="LinkedList"
            queue.filename="ampDashboardForward"
            queue.saveOnShutdown="on"
        )
RSYSLOG_FORWARD
  fi

  sudo tee -a /etc/rsyslog.d/30-amp-dashboard.conf >/dev/null <<'RSYSLOG'
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
  # --remove-orphans also stops old local InfluxDB and FreeRADIUS containers
  # left by installations made before both services became remote-only.
  sudo docker compose up -d --build --remove-orphans
  sudo systemctl start amp-dashboard.service
}

install_network_agent_service() {
  local python_path
  python_path="$(command -v python3)"

  info "Installing host network agent"
  sudo install -D -m 0755 "${PROJECT_DIR}/tools/network_agent.py" /usr/local/lib/amp-dashboard/network_agent.py
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
After=docker.service amp-network-agent.service systemd-timesyncd.service network-online.target
Wants=network-online.target systemd-timesyncd.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=${docker_path} compose up -d --remove-orphans

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

Device identifier:
  $(env_value "DEVICE_NAME")

Local database:
  SQLite file $(env_value "DATABASE_FILE")
  maximum records: $(env_value "DATABASE_MAX_RECORDS")

SNMP:
  UDP port $(env_value "SNMP_PORT")

RADIUS:
  ${RADIUS_SUMMARY}
  NAS-Identifier: $(env_value "RADIUS_NAS_IDENTIFIER")

Time synchronization:
  systemd-timesyncd uses $(env_value "NTP_SERVER")

System log:
  /var/log/amp-dashboard/amp-dashboard.log (managed by rsyslog and logrotate)

Default login:
  username: admin
  password: managed by the remote RADIUS server

Useful commands:
  cd ${PROJECT_DIR}
  docker compose logs -f app
  docker compose restart app
  docker compose down
  sudo systemctl status amp-dashboard.service
  sudo systemctl status amp-network-agent.service

An administrator can select a connected /dev/ttyACM* or /dev/ttyUSB* adapter
from Service Settings without rerunning this installer.

You may need to close and reopen the Linux shell once before docker commands
work without sudo. The dashboard is already running.
SUMMARY
}

require_linux
systemd_is_running || fail "systemd must be running on the Linux server."
install_system_packages
install_docker_engine
prepare_environment_file
cleanup_legacy_local_configuration
configure_time_sync
configure_system_syslog
install_network_agent_service
install_dashboard_service
start_dashboard
print_summary
