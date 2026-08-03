#!/usr/bin/env bash
set -euo pipefail

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
info() { printf '\n[amp-radius] %s\n' "$1"; }
[[ "$(uname -s)" == "Linux" ]] || fail "Linux is required"
[[ "$EUID" -eq 0 ]] || fail "Run this script as root (use su - first)"
command -v apt-get >/dev/null || fail "A Debian-family system with apt is required"

read -r -p "Amp Panel client IP or CIDR (for example 192.168.0.51/32): " client_ip
read -r -p "Initial RADIUS username [admin]: " radius_user
radius_user="${radius_user:-admin}"
[[ "$client_ip" =~ ^[0-9a-fA-F:./]+$ ]] || fail "Invalid client address"
[[ "$radius_user" =~ ^[A-Za-z0-9._-]+$ ]] || fail "Invalid username"
read -r -s -p "RADIUS shared secret (Enter generates one): " radius_secret; printf '\n'
read -r -s -p "Password for ${radius_user} (Enter generates one): " radius_password; printf '\n'

info "Installing FreeRADIUS"
apt-get update
apt-get install -y freeradius freeradius-utils python3
radius_secret="${radius_secret:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"
radius_password="${radius_password:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')}"
[[ "$radius_secret" =~ ^[A-Za-z0-9._~!@%+=:-]+$ ]] || fail "The shared secret contains unsupported characters"
[[ "$radius_password" =~ ^[A-Za-z0-9._~!@%+=:-]+$ ]] || fail "The password contains unsupported characters"

config_dir="/etc/freeradius/3.0"
[[ -d "$config_dir" ]] || config_dir="/etc/raddb"
[[ -f "$config_dir/clients.conf" ]] || fail "Could not locate FreeRADIUS clients.conf"
authorize_file="$config_dir/mods-config/files/authorize"
[[ -f "$authorize_file" ]] || fail "Could not locate FreeRADIUS authorize file"

sed -i '/^# BEGIN AMP-PANEL CLIENT$/,/^# END AMP-PANEL CLIENT$/d' "$config_dir/clients.conf"
cat >> "$config_dir/clients.conf" <<CLIENT

# BEGIN AMP-PANEL CLIENT
client amp_panel {
    ipaddr = ${client_ip}
    secret = ${radius_secret}
    require_message_authenticator = yes
}
# END AMP-PANEL CLIENT
CLIENT

sed -i '/^# BEGIN AMP-PANEL USER$/,/^# END AMP-PANEL USER$/d' "$authorize_file"
cat >> "$authorize_file" <<USER

# BEGIN AMP-PANEL USER
${radius_user} Cleartext-Password := "${radius_password}"
# END AMP-PANEL USER
USER
chown root:freerad "$config_dir/clients.conf" "$authorize_file" 2>/dev/null || true
chmod 0640 "$config_dir/clients.conf" "$authorize_file"

freeradius -XC
systemctl enable --now freeradius
systemctl restart freeradius
server_ip="$(hostname -I | awk '{print $1}')"
cat <<SUMMARY

Temporary RADIUS server is ready.
Use these values in the Amp Panel configuration:
  RADIUS_SERVER=${server_ip}
  RADIUS_PORT=1812
  RADIUS_SECRET=${radius_secret}

Test user:
  username=${radius_user}
  password=${radius_password}

Allow UDP/1812 only from ${client_ip}. This installer is independent and can be removed later.
SUMMARY
