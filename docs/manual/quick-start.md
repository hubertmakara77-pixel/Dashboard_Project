# Quick start

## Before logging in

The installation administrator should provide:

- the dashboard address, usually `http://<name>.local:8000`;
- a username included in the local access list;
- that user's RADIUS password;
- confirmation of whether the amplifier or FTS-LS profile is active.

The dashboard runs in a browser and does not require client software.

## First login

1. Open the supplied dashboard address.
2. Enter the username and RADIUS password.
3. Verify the device name and profile displayed after login.
4. Open **Live View** and check the connection state.

If the dashboard reports too many attempts, wait for the configured window,
which is 5 minutes by default. The default limit is reached after 5 failed
attempts from one IP address. A RADIUS-unavailable message indicates a problem
with the authentication service, not an incorrect password.

## Startup verification

A healthy state meets all of the following conditions:

- the serial connection is **Connected**;
- **Last update** changes regularly;
- no active alarm requires action;
- the history chart receives new points;
- for FTS-LS, UL and exactly P1–P7 are visible, even when some slots are marked
  `UNEQUIPPED`.

## When no data is available

First refresh the page and check **Last update**. If the connection is down or
the timestamp does not change, provide the Administrator with:

- the time the problem started;
- the device name;
- the visible error message;
- whether the device was restarted or its USB cable was reconnected.

The Administrator should run `sudo amp-panel doctor` and inspect the logs as
described in [troubleshooting](../operations/troubleshooting.md).

## Logging out

Use **Logout**. Closing the browser tab does not immediately invalidate the
session. It expires after `SESSION_MAX_AGE_SECONDS`, which defaults to 12 hours.
