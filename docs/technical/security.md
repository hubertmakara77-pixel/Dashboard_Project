# Security

## Authentication model

Access requires two independent conditions:

1. the username exists and is active in the local `access_users` list;
2. RADIUS accepts the username and password.

The local state stores only username, role, and active status. User passwords do
not remain in the dashboard beyond a single login request. The FTS-LS console
password and RADIUS secret are host secrets stored in `amp-panel.env`.

## Sessions

The session token is random, stored in process memory, and sent in a cookie with:

- `HttpOnly` — JavaScript cannot read it;
- `SameSite=Strict` — the browser restricts cross-site sending;
- `Secure` according to `SESSION_COOKIE_SECURE`;
- a default lifetime of 43200 seconds.

Restarting the application invalidates all sessions. For HTTPS deployments, set
`SESSION_COOKIE_SECURE=true`. The dashboard does not terminate TLS itself; use a
trusted reverse proxy or an isolated management network.

## Login protection

By default, 5 failures from one IP within 300 seconds block further attempts.
`TRUST_PROXY_HEADERS=false` should remain the default unless all traffic passes
through a controlled reverse proxy that overwrites client-address headers.

## Authorization

The backend checks roles on every endpoint. Button visibility is not
authorization. User management, network, diagnostics, SNMP, and administrative
station commands are specifically protected. Last-active-Administrator rules
prevent accidental administrative lockout.

## Input and device validation

Pydantic validates HTTP types, while the validation layer checks ranges, finite
numbers, usernames, ports, and thresholds. FTS-LS commands are constructed from
an allowlist; HTTP text is never sent directly to the console. Network changes
use a minimal privileged agent, a checkpoint, and explicit confirmation.

## Secrets and files

- `/etc/amp-panel/amp-panel.env` and `persisted_state.json` use mode `0600`;
- never put real secrets in `.env.example`, logs, Git, or shell-history-visible
  commands;
- treat the SNMP community like a password; SNMP v2c does not encrypt traffic;
- audit logs may contain usernames, IP addresses, and changed values, but the
  community is redacted;
- configuration backups must be encrypted and access-controlled.

## Audit trail

Syslog records login successes and failures, logout, changes to users, thresholds,
setpoints, diagnostics, network and SNMP settings, exports, and FTS-LS commands.
Events contain the user, IP, action, and details. An Administrator's log export is
also audited.

## Deployment recommendations

1. Separate the management network from public traffic.
2. Use HTTPS and `SESSION_COOKIE_SECURE=true` outside a trusted LAN.
3. Restrict RADIUS, SNMP, and syslog traffic to known hosts with a firewall.
4. Use a random SNMP community substantially longer than the required 12
   characters.
5. Review audit logs, update the package, and test backup restoration regularly.
6. Do not grant Administrator to operators who do not require it.
