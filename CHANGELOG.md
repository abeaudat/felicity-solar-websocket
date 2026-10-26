# Changelog

## 2.0.5 — 2026-10-26

Fix progressively delayed inverter values when FSolar pushes messages faster
than the configured command interval. The receiver now consumes messages
continuously while a separate task paces read commands. Previously, one message
was consumed per read cycle, so queued measurements could look freshly received
even when their contents were old.

- Preserve retry on the existing socket, bounded freshness timeouts, device
  filtering, reconnect backoff and clean cancellation on unload.
- Add a regression test that pushes several frames after one command and checks
  that all are received before another command is sent.
- Preserve account entries, entity IDs, power conversions, historical data and
  default five-minute HTTP polling for separate batteries.
- Update the transport documentation and document the diagnostic procedure used
  during the October investigations.
- Validate the complete 29-test suite against Home Assistant 2026.9.4 on Python
  3.14 and verify that all 12 Python files in the HACS archive match the installed
  component audited on October 26.

### Audit of changes since 2.0.4

| Date | Work | Repository status |
| --- | --- | --- |
| October 4 | Same-socket recovery for delayed responses and browser-compatible ping handling | Already published in 2.0.4 |
| October 7 | Investigated intermittent gaps using HA states, direct frames, vendor history and network observations; enabled persistent diagnostic logging | Operational diagnostics, not another integration-code change; general procedure documented in this release |
| October 21 | Fixed queued WebSocket messages; added a regression test; deployed and verified on Home Assistant | Previously local and deployed only; now included in 2.0.5 |
| October 26 | Compared all 19 installed component files against 2.0.4 and local source | Only `realtime.py` differed from 2.0.4; installed files matched local source before the release version/documentation updates |

The October 21 live check used Home Assistant 2026.10.2 and the IVGM15KLP3G1
inverter. Over approximately three minutes, 86 HA samples had no unavailable
values and agreed with direct FSolar data on SOC and daily counters. The check
does not establish the cause of every earlier outage, long-term endurance, or
physical-control behavior.

Private account data, captures, credentials, personal dashboards and local
deployment helpers are not part of the release.

## 2.0.4 — 2026-10-04

- Retry delayed telemetry responses on the existing socket instead of
  immediately reconnecting.
- Answer server pings without sending additional heartbeat pings, matching the
  FSolar browser client.
- Retain a bounded freshness deadline, reconnect backoff, existing entity IDs,
  power units and separate battery HTTP polling.
- Validate recovery after a dropped response and stale detection during
  continuous unrelated messages; 28 tests passed for this release.
