#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/amp-influxdb"

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
info() { printf '\n[amp-influxdb] %s\n' "$1"; }
[[ "$(uname -s)" == "Linux" ]] || fail "Linux is required"
[[ "$EUID" -eq 0 ]] || fail "Run this script as root (use su - first)"
command -v apt-get >/dev/null || fail "A Debian-family system with apt is required"

info "Installing prerequisites"
apt-get -o Acquire::ForceIPv4=true update
apt-get install -y ca-certificates curl python3
if ! command -v dockerd >/dev/null; then
  . /etc/os-release
  docker_codename="${VERSION_CODENAME:-}"
  [[ "$ID" == "debian" && -n "$docker_codename" ]] || fail "Docker installation requires Debian with VERSION_CODENAME"
  docker_arch="$(dpkg --print-architecture)"
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /tmp/docker.asc
  install -d -m 0755 /etc/apt/keyrings
  install -m 0644 /tmp/docker.asc /etc/apt/keyrings/docker.asc
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian %s stable\n' \
    "$docker_arch" "$docker_codename" > /etc/apt/sources.list.d/docker.list
  apt-get -o Acquire::ForceIPv4=true update
  apt-get -o Acquire::ForceIPv4=true install -y \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
docker compose version >/dev/null 2>&1 || apt-get -o Acquire::ForceIPv4=true install -y docker-compose-plugin
systemctl enable --now docker

mkdir -p "$INSTALL_DIR/secrets"
chmod 0700 "$INSTALL_DIR" "$INSTALL_DIR/secrets"
cd "$INSTALL_DIR"

if [[ ! -f server.env ]]; then
  read -r -p "InfluxDB organization [agh]: " org
  read -r -p "InfluxDB bucket [sensors]: " bucket
  read -r -p "Listen address [0.0.0.0]: " bind_address
  read -r -p "TCP port [8086]: " port
  org="${org:-agh}"
  bucket="${bucket:-sensors}"
  bind_address="${bind_address:-0.0.0.0}"
  port="${port:-8086}"
  [[ "$org" =~ ^[A-Za-z0-9._-]+$ ]] || fail "Organization contains unsupported characters"
  [[ "$bucket" =~ ^[A-Za-z0-9._-]+$ ]] || fail "Bucket contains unsupported characters"
  [[ "$bind_address" =~ ^[0-9.]+$ ]] || fail "Listen address must be an IPv4 address"
  [[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )) || fail "Invalid port"
  printf 'INFLUX_ORG=%s\nINFLUX_BUCKET=%s\nINFLUX_BIND_ADDRESS=%s\nINFLUX_PORT=%s\n' \
    "$org" "$bucket" "$bind_address" "$port" > server.env
  printf 'admin\n' > secrets/admin-username
  python3 -c 'import secrets; print(secrets.token_urlsafe(24))' > secrets/admin-password
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > secrets/operator-token
  chmod 0600 server.env secrets/*
else
  info "Keeping existing server configuration and credentials"
fi

cat > compose.yaml <<'COMPOSE'
services:
  influxdb:
    image: influxdb:2.9
    container_name: amp-influxdb
    restart: unless-stopped
    ports:
      - "${INFLUX_BIND_ADDRESS}:${INFLUX_PORT}:8086"
    environment:
      DOCKER_INFLUXDB_INIT_MODE: setup
      DOCKER_INFLUXDB_INIT_USERNAME_FILE: /run/secrets/admin_username
      DOCKER_INFLUXDB_INIT_PASSWORD_FILE: /run/secrets/admin_password
      DOCKER_INFLUXDB_INIT_ADMIN_TOKEN_FILE: /run/secrets/operator_token
      DOCKER_INFLUXDB_INIT_ORG: ${INFLUX_ORG}
      DOCKER_INFLUXDB_INIT_BUCKET: ${INFLUX_BUCKET}
    secrets:
      - admin_username
      - admin_password
      - operator_token
    volumes:
      - influxdb-data:/var/lib/influxdb2
      - influxdb-config:/etc/influxdb2
secrets:
  admin_username:
    file: ./secrets/admin-username
  admin_password:
    file: ./secrets/admin-password
  operator_token:
    file: ./secrets/operator-token
volumes:
  influxdb-data:
  influxdb-config:
COMPOSE

. ./server.env
docker compose --env-file server.env up -d
info "Waiting for InfluxDB"
health_host="127.0.0.1"
[[ "$INFLUX_BIND_ADDRESS" != "0.0.0.0" ]] && health_host="$INFLUX_BIND_ADDRESS"
for _ in $(seq 1 60); do
  curl -fsS "http://${health_host}:${INFLUX_PORT}/health" >/dev/null && break
  sleep 2
done
curl -fsS "http://${health_host}:${INFLUX_PORT}/health" >/dev/null || fail "InfluxDB did not become healthy"

if [[ ! -f secrets/dashboard-token ]]; then
  operator_token="$(<secrets/operator-token)"
  bucket_json="$(docker exec amp-influxdb influx bucket list --org "$INFLUX_ORG" --name "$INFLUX_BUCKET" --token "$operator_token" --json)"
  bucket_id="$(printf '%s' "$bucket_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')"
  auth_json="$(docker exec amp-influxdb influx auth create --org "$INFLUX_ORG" --read-bucket "$bucket_id" --write-bucket "$bucket_id" --description amp-dashboard-devices --token "$operator_token" --json)"
  printf '%s' "$auth_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])' > secrets/dashboard-token
  chmod 0600 secrets/dashboard-token
fi

server_ip="$(hostname -I | awk '{print $1}')"
[[ "$INFLUX_BIND_ADDRESS" != "0.0.0.0" ]] && server_ip="$INFLUX_BIND_ADDRESS"
cat <<SUMMARY

InfluxDB server is ready.
Use these values in the dashboard installer:
  INFLUX_URL=http://${server_ip}:${INFLUX_PORT}
  INFLUX_ORG=${INFLUX_ORG}
  INFLUX_BUCKET=${INFLUX_BUCKET}
  INFLUX_TOKEN=$(<secrets/dashboard-token)

Admin UI: http://${server_ip}:${INFLUX_PORT}
Admin username: $(<secrets/admin-username)
Admin password: $(<secrets/admin-password)

Protect TCP/${INFLUX_PORT} with a firewall. Credentials remain in ${INSTALL_DIR}/secrets.
SUMMARY
