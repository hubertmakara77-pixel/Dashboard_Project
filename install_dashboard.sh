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

prepare_privilege_escalation() {
  if [[ "$EUID" -eq 0 ]]; then
    # Keep the rest of the installer identical for root and sudo users.
    sudo() {
      "$@"
    }
  elif ! command -v sudo >/dev/null 2>&1; then
    fail "Run this installer as root or install sudo first."
  fi
}

prompt_value() {
  local variable_name="$1"
  local label="$2"
  local default_value="$3"
  local entered_value

  if [[ -n "$default_value" ]]; then
    read -r -p "${label} [${default_value}]: " entered_value
  else
    read -r -p "${label}: " entered_value
  fi
  printf -v "$variable_name" '%s' "${entered_value:-$default_value}"
}

prompt_secret() {
  local variable_name="$1"
  local label="$2"
  local current_value="$3"
  local entered_value

  if [[ -n "$current_value" ]]; then
    read -r -s -p "${label} [Enter keeps current]: " entered_value
  else
    read -r -s -p "${label}: " entered_value
  fi
  printf '\n'
  printf -v "$variable_name" '%s' "${entered_value:-$current_value}"
}

confirm() {
  local question="$1"
  local default_answer="${2:-no}"
  local suffix="[y/N]"
  local answer

  [[ "$default_answer" == "yes" ]] && suffix="[Y/n]"
  read -r -p "${question} ${suffix}: " answer
  answer="${answer:-$default_answer}"
  case "${answer,,}" in
    y|yes) return 0 ;;
    n|no) return 1 ;;
    *) fail "Answer yes or no." ;;
  esac
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
  local packages=(avahi-daemon avahi-utils ca-certificates curl gnupg iproute2 logrotate network-manager python3 rsyslog systemd-timesyncd)
  local missing_packages=()
  local package

  for package in "${packages[@]}"; do
    if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q '^install ok installed$'; then
      missing_packages+=("$package")
    fi
  done

  if (( ${#missing_packages[@]} == 0 )); then
    info "Required system packages are already installed"
    return
  fi

  info "Installing missing system packages: ${missing_packages[*]}"
  sudo apt-get update
  sudo apt-get install -y "${missing_packages[@]}"
}

configure_network_manager() {
  command -v nmcli >/dev/null 2>&1 || fail "NetworkManager was installed but nmcli is unavailable."

  info "Enabling NetworkManager for dashboard network configuration"
  sudo systemctl enable --now NetworkManager.service
}

configure_mdns() {
  local device_name
  local dashboard_port
  local mdns_hostname

  device_name="$(env_value DEVICE_NAME)"
  dashboard_port="$(env_value DASHBOARD_PORT)"
  mdns_hostname="$(
    printf '%s' "$device_name" |
      tr '[:upper:]_' '[:lower:]-' |
      sed 's/[^a-z0-9-]/-/g; s/-\{2,\}/-/g; s/^-*//; s/-*$//' |
      cut -c1-63
  )"
  [[ -n "$mdns_hostname" ]] || fail "DEVICE_NAME cannot be converted to a valid mDNS hostname."

  info "Publishing Dashboard as ${mdns_hostname}.local"
  sudo hostnamectl set-hostname "$mdns_hostname"
  set_env_value "MDNS_HOSTNAME" "${mdns_hostname}.local"

  sudo install -d -m 0755 /etc/avahi/services
  sudo tee /etc/avahi/services/amp-dashboard.service >/dev/null <<AVAHI_SERVICE
<?xml version="1.0" standalone="no"?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">%h Dashboard</name>
  <service>
    <type>_http._tcp</type>
    <port>${dashboard_port}</port>
    <txt-record>path=/</txt-record>
  </service>
</service-group>
AVAHI_SERVICE

  sudo systemctl enable avahi-daemon.service
  sudo systemctl restart avahi-daemon.service
  sudo systemctl is-active --quiet avahi-daemon.service ||
    fail "Avahi did not start; inspect journalctl -u avahi-daemon.service."
}

disable_system_sleep() {
  info "Disabling system suspend and hibernation"

  sudo install -d -m 0755 /etc/systemd/sleep.conf.d
  sudo tee /etc/systemd/sleep.conf.d/50-amp-dashboard.conf >/dev/null <<'SLEEP'
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowSuspendThenHibernate=no
AllowHybridSleep=no
SLEEP

  # Masking the targets also blocks suspend requests made by a desktop
  # environment or another service. Screen blanking is intentionally untouched.
  sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
  sudo systemctl daemon-reload
}

install_docker_engine() {
  local docker_arch
  local docker_codename
  local docker_user

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

  docker_user="${SUDO_USER:-}"
  if [[ -z "$docker_user" || "$docker_user" == "root" ]]; then
    docker_user="$(stat -c '%U' "$PROJECT_DIR" 2>/dev/null || true)"
  fi
  if [[ -n "$docker_user" && "$docker_user" != "root" ]] && id "$docker_user" >/dev/null 2>&1; then
    sudo usermod -aG docker "$docker_user"
  fi
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

  prompt_dashboard_configuration
  prompt_radius_configuration
  prompt_remote_syslog_configuration
  prompt_gain_range_configuration

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
  set_env_default "DATABASE_MAX_RECORDS" "0"
  set_env_default "HISTORY_MAX_POINTS" "2000"
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
  ensure_service_identity "$serial_device"
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

ensure_service_identity() {
  local serial_device="$1"
  local dashboard_uid dashboard_gid serial_gid syslog_gid
  local existing_group existing_user

  dashboard_uid="$(env_value DASHBOARD_UID)"
  dashboard_gid="$(env_value DASHBOARD_GID)"
  dashboard_uid="${dashboard_uid:-10001}"
  dashboard_gid="${dashboard_gid:-10001}"
  [[ "$dashboard_uid" =~ ^[0-9]+$ ]] || fail "DASHBOARD_UID must be numeric."
  [[ "$dashboard_gid" =~ ^[0-9]+$ ]] || fail "DASHBOARD_GID must be numeric."

  if getent group amp-dashboard >/dev/null; then
    existing_group="$(getent group amp-dashboard | cut -d: -f3)"
    [[ "$existing_group" == "$dashboard_gid" ]] ||
      fail "Host group amp-dashboard uses GID ${existing_group}, but .env requests ${dashboard_gid}."
  else
    existing_group="$(getent group "$dashboard_gid" | cut -d: -f1 || true)"
    [[ -z "$existing_group" ]] ||
      fail "DASHBOARD_GID ${dashboard_gid} is already used by group ${existing_group}."
    sudo groupadd --gid "$dashboard_gid" amp-dashboard
  fi

  if getent passwd amp-dashboard >/dev/null; then
    existing_user="$(getent passwd amp-dashboard | cut -d: -f3)"
    [[ "$existing_user" == "$dashboard_uid" ]] ||
      fail "Host user amp-dashboard uses UID ${existing_user}, but .env requests ${dashboard_uid}."
  else
    existing_user="$(getent passwd "$dashboard_uid" | cut -d: -f1 || true)"
    [[ -z "$existing_user" ]] ||
      fail "DASHBOARD_UID ${dashboard_uid} is already used by user ${existing_user}."
    sudo useradd --uid "$dashboard_uid" --gid amp-dashboard --no-create-home \
      --home-dir /nonexistent --shell /usr/sbin/nologin amp-dashboard
  fi

  if [[ "$serial_device" != "/dev/null" && -e "$serial_device" ]]; then
    serial_gid="$(stat -c '%g' "$serial_device")"
  else
    serial_gid="$(getent group dialout | cut -d: -f3 || true)"
    serial_gid="${serial_gid:-20}"
  fi
  syslog_gid="$(getent group adm | cut -d: -f3 || true)"
  syslog_gid="${syslog_gid:-4}"

  set_env_value "DASHBOARD_UID" "$dashboard_uid"
  set_env_value "DASHBOARD_GID" "$dashboard_gid"
  set_env_value "SERIAL_DEVICE_GID" "$serial_gid"
  set_env_value "SYSLOG_READER_GID" "$syslog_gid"

  set_data_permissions
}

set_data_permissions() {
  # data may be a dedicated filesystem and contain root-owned lost+found.
  # Change only the mount point and application files at its top level.
  sudo chown amp-dashboard:amp-dashboard data
  sudo find data -xdev -mindepth 1 -maxdepth 1 -type f \
    -exec chown amp-dashboard:amp-dashboard {} +
  sudo chmod 0750 data
}

prompt_dashboard_configuration() {
  local admin_username
  local dashboard_port

  admin_username="$(env_value INITIAL_ADMIN_USERNAME)"
  admin_username="${admin_username:-admin}"
  dashboard_port="$(env_value DASHBOARD_PORT)"
  dashboard_port="${dashboard_port:-8000}"

  if [[ -t 0 ]]; then
    info "Dashboard access configuration"
    prompt_value admin_username "Initial Administrator username (must match RADIUS)" "$admin_username"
    prompt_value dashboard_port "Dashboard TCP port" "$dashboard_port"
  fi

  [[ "$admin_username" =~ ^[A-Za-z0-9._@-]{1,128}$ ]] ||
    fail "Administrator username may contain 1-128 letters, digits, dots, underscores, @ or hyphens."
  [[ "$dashboard_port" =~ ^[0-9]+$ ]] &&
    (( dashboard_port >= 1 && dashboard_port <= 65535 )) ||
    fail "Dashboard port must be between 1 and 65535."

  set_env_value "INITIAL_ADMIN_USERNAME" "$admin_username"
  set_env_value "DASHBOARD_PORT" "$dashboard_port"

  if [[ -s data/persisted_state.json ]]; then
    info "Existing access users are preserved; the initial Administrator name applies only when no access list exists."
  fi
}

prompt_gain_range_configuration() {
  local gain_min gain_max
  gain_min="$(env_value GAIN_SET_MIN)"
  gain_max="$(env_value GAIN_SET_MAX)"

  if [[ -t 0 ]]; then
    prompt_value gain_min "Minimum safe gain setpoint from the device specification" "$gain_min"
    prompt_value gain_max "Maximum safe gain setpoint from the device specification" "$gain_max"
  fi

  [[ -n "$gain_min" && -n "$gain_max" ]] ||
    fail "Set GAIN_SET_MIN and GAIN_SET_MAX to the safe range specified by the device manufacturer."
  python3 -c 'import math, sys
minimum, maximum = map(float, sys.argv[1:3])
if not (math.isfinite(minimum) and math.isfinite(maximum) and minimum < maximum):
    raise SystemExit(1)' "$gain_min" "$gain_max" ||
    fail "GAIN_SET_MIN and GAIN_SET_MAX must be finite numbers with MIN < MAX."

  set_env_value "GAIN_SET_MIN" "$gain_min"
  set_env_value "GAIN_SET_MAX" "$gain_max"
}

prompt_radius_configuration() {
  local radius_server radius_port radius_secret

  [[ -t 0 ]] || return

  radius_server="$(env_value RADIUS_SERVER)"
  [[ "$radius_server" == "radius" ]] && radius_server=""
  radius_port="$(env_value RADIUS_PORT)"
  radius_port="${radius_port:-1812}"
  radius_secret="$(env_value RADIUS_SECRET)"

  info "Remote RADIUS configuration"
  prompt_value radius_server "RADIUS server address" "$radius_server"
  prompt_value radius_port "RADIUS UDP port" "$radius_port"
  prompt_secret radius_secret "RADIUS shared secret" "$radius_secret"

  [[ -n "$radius_server" ]] || fail "RADIUS server address is required."
  [[ "$radius_port" =~ ^[0-9]+$ ]] && (( radius_port >= 1 && radius_port <= 65535 )) || fail "RADIUS port must be between 1 and 65535."
  [[ -n "$radius_secret" ]] || fail "RADIUS shared secret is required."

  printf '\n[amp-dashboard] RADIUS: %s:%s\n' "$radius_server" "$radius_port"
  printf '[amp-dashboard] Shared secret: configured (hidden)\n'
  confirm "Apply RADIUS configuration?" no || fail "RADIUS configuration was not confirmed."
  set_env_value "RADIUS_SERVER" "$radius_server"
  set_env_value "RADIUS_PORT" "$radius_port"
  set_env_value "RADIUS_SECRET" "$radius_secret"
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
      if confirm "Forward dashboard logs to a remote syslog server?" yes; then
        choice="yes"
      else
        choice="no"
      fi
      ;;
    *)
      if confirm "Forward dashboard logs to a remote syslog server?" no; then
        choice="yes"
      else
        choice="no"
      fi
      ;;
  esac

  case "${choice,,}" in
    n|no)
      set_env_value "REMOTE_SYSLOG_ENABLED" "false"
      info "Remote syslog forwarding disabled; the local log remains enabled"
      return
      ;;
    y|yes) ;;
  esac

  prompt_value remote_host "Remote syslog server address" "$remote_host"
  prompt_value remote_port "Remote syslog port" "$remote_port"
  prompt_value remote_protocol "Remote syslog protocol (tcp/udp)" "$remote_protocol"
  remote_protocol="${remote_protocol,,}"

  [[ -n "$remote_host" ]] || fail "Remote syslog server address is required."
  [[ "$remote_port" =~ ^[0-9]+$ ]] && (( remote_port >= 1 && remote_port <= 65535 )) || fail "Remote syslog port must be between 1 and 65535."
  [[ "$remote_protocol" == "tcp" || "$remote_protocol" == "udp" ]] || fail "Remote syslog protocol must be tcp or udp."

  printf '\n[amp-dashboard] Remote syslog: %s:%s over %s\n' "$remote_host" "$remote_port" "$remote_protocol"
  printf '[amp-dashboard] Local logging: enabled\n'
  confirm "Apply remote syslog configuration?" no || fail "Remote syslog configuration was not confirmed."
  set_env_value "REMOTE_SYSLOG_ENABLED" "true"
  set_env_value "REMOTE_SYSLOG_HOST" "$remote_host"
  set_env_value "REMOTE_SYSLOG_PORT" "$remote_port"
  set_env_value "REMOTE_SYSLOG_PROTOCOL" "$remote_protocol"
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
  info "Building dashboard image"
  sudo docker compose build
  info "Stopping the previous dashboard container before repairing data ownership"
  sudo docker compose down
  set_data_permissions
  info "Starting dashboard service"
  # The systemd unit uses --remove-orphans, which also stops containers left
  # by installations from before InfluxDB and FreeRADIUS became external.
  sudo systemctl restart amp-dashboard.service
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
Group=amp-dashboard
RuntimeDirectory=amp-dashboard
RuntimeDirectoryMode=0750
RuntimeDirectoryPreserve=yes
UMask=0007
ExecStart=${python_path} /usr/local/lib/amp-dashboard/network_agent.py --socket /run/amp-dashboard/network-agent.sock
Restart=on-failure
RestartSec=2
NoNewPrivileges=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectHome=yes
ProtectSystem=strict
ProtectClock=yes
ProtectControlGroups=yes
ProtectKernelLogs=yes
ProtectKernelModules=yes
ProtectKernelTunables=yes
CapabilityBoundingSet=
LockPersonality=yes
RestrictSUIDSGID=yes
RestrictAddressFamilies=AF_UNIX AF_NETLINK

[Install]
WantedBy=multi-user.target
SERVICE

  sudo systemctl daemon-reload
  sudo systemctl enable amp-network-agent.service
  sudo systemctl restart amp-network-agent.service
}

install_dashboard_service() {
  local docker_path
  docker_path="$(command -v docker)"

  info "Configuring dashboard to start automatically with Linux"
  sudo tee /etc/systemd/system/amp-dashboard.service >/dev/null <<SERVICE
[Unit]
Description=Optical amplifier dashboard containers
Requires=docker.service amp-network-agent.service
After=docker.service amp-network-agent.service avahi-daemon.service systemd-timesyncd.service network-online.target
Wants=avahi-daemon.service network-online.target systemd-timesyncd.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=${docker_path} compose up -d --remove-orphans
ExecStop=${docker_path} compose down

[Install]
WantedBy=multi-user.target
SERVICE

  sudo systemctl daemon-reload
  sudo systemctl enable amp-dashboard.service
}

print_summary() {
  local dashboard_port
  local dashboard_address
  local database_limit
  dashboard_port="$(env_value "DASHBOARD_PORT")"
  dashboard_address="$(hostname -I 2>/dev/null | awk '{print $1}')"
  dashboard_address="${dashboard_address:-localhost}"
  database_limit="$(env_value "DATABASE_MAX_RECORDS")"
  [[ "$database_limit" == "0" ]] && database_limit="unlimited"

  cat <<SUMMARY

Installation finished.

Dashboard:
  http://${dashboard_address}:${dashboard_port}

Device identifier:
  $(env_value "DEVICE_NAME")

Data storage:
  SQLite file $(env_value "DATABASE_FILE")
  maximum records: ${database_limit}

SNMP:
  UDP port $(env_value "SNMP_PORT")

RADIUS:
  ${RADIUS_SUMMARY}
  NAS-Identifier: $(env_value "RADIUS_NAS_IDENTIFIER")

Time synchronization:
  systemd-timesyncd uses $(env_value "NTP_SERVER")

Host services:
  NetworkManager enabled
  Avahi publishes http://$(env_value "MDNS_HOSTNAME"):${dashboard_port}
  suspend and hibernation disabled

System log:
  /var/log/amp-dashboard/amp-dashboard.log (managed by rsyslog and logrotate)

Default login:
  username: $(env_value "INITIAL_ADMIN_USERNAME")
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
prepare_privilege_escalation
systemd_is_running || fail "systemd must be running on the Linux server."
install_system_packages
configure_network_manager
disable_system_sleep
install_docker_engine
prepare_environment_file
configure_mdns
cleanup_legacy_local_configuration
configure_time_sync
configure_system_syslog
install_network_agent_service
install_dashboard_service
start_dashboard
print_summary
