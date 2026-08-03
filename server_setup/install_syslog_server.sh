#!/usr/bin/env bash
set -euo pipefail

fail() { printf 'ERROR: %s\n' "$1" >&2; exit 1; }
info() { printf '\n[amp-syslog] %s\n' "$1"; }
[[ "$(uname -s)" == "Linux" ]] || fail "Linux is required"
[[ "$EUID" -eq 0 ]] || fail "Run this script as root (use su - first)"
command -v apt-get >/dev/null || fail "A Debian-family system with apt is required"

read -r -p "Syslog protocol [tcp]: " protocol
read -r -p "Syslog port [514]: " port
protocol="${protocol:-tcp}"
port="${port:-514}"
[[ "$protocol" == "tcp" || "$protocol" == "udp" ]] || fail "Protocol must be tcp or udp"
[[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )) || fail "Invalid port"

info "Installing rsyslog and logrotate"
apt-get update
apt-get install -y rsyslog logrotate
getent group adm >/dev/null || groupadd --system adm
install -d -o root -g adm -m 0750 /var/log/amp-panel
touch /var/log/amp-panel/amp-panel.log
chown root:adm /var/log/amp-panel/amp-panel.log
chmod 0640 /var/log/amp-panel/amp-panel.log

module="imtcp"
input="input(type=\"imtcp\" port=\"${port}\")"
[[ "$protocol" == "udp" ]] && module="imudp" && input="input(type=\"imudp\" port=\"${port}\")"
cat > /etc/rsyslog.d/30-amp-panel-receiver.conf <<RSYSLOG
module(load="${module}")
template(name="ampPanelRemoteLine" type="string" string="%timereported:::date-rfc3339% %msg:2:\$%\\n")
if (\$programname == "amp-panel") then {
    action(type="omfile" file="/var/log/amp-panel/amp-panel.log" fileOwner="root" fileGroup="adm" fileCreateMode="0640" template="ampPanelRemoteLine")
    stop
}
${input}
RSYSLOG

cat > /etc/logrotate.d/amp-panel-receiver <<'ROTATE'
/var/log/amp-panel/amp-panel.log {
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
ROTATE

rsyslogd -N1
systemctl enable --now rsyslog
systemctl restart rsyslog
server_ip="$(hostname -I | awk '{print $1}')"
cat <<SUMMARY

Remote syslog receiver is ready.
Use these values in the Amp Panel configuration:
  REMOTE_SYSLOG_ENABLED=true
  REMOTE_SYSLOG_HOST=${server_ip}
  REMOTE_SYSLOG_PORT=${port}
  REMOTE_SYSLOG_PROTOCOL=${protocol}

Log file: /var/log/amp-panel/amp-panel.log
Allow ${protocol^^}/${port} only from Amp Panel hosts in the firewall.
SUMMARY
