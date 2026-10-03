# Felicity Solar WebSocket

Home Assistant custom integration for Felicity Solar / FSolar, forked from
[Smilebob Edition](https://github.com/smilebob/felicity_solar_hacs), itself based
on [Matheus Trindade's integration](https://github.com/matheustavarestrindade/felicity_solar_hacs).

Version **2.0.3** replaces HTTP telemetry snapshots with the same WebSocket read
protocol used by the FSolar web portal's **Real-time Data** button. The default
read interval is **5 seconds**, adjustable between 2 and 60 seconds.

## How it works

- Authenticates with the existing Shine / FSolar account and discovers its devices.
- Opens `wss://shine-api.felicitysolar.com/socket/energy-flow/{deviceSn}` per device.
- Sends the portal's telemetry read command with the account-owned device and
  collector serial numbers. It sends no inverter setting changes automatically.
- Updates the existing Home Assistant entities from `deviceSnapshot` messages.
- Normalizes inverter snapshot powers to W; the live envelope is already in W.
- Waits for each response before sending another read, respects the configured
  interval, and reconnects with backoff capped at 60 seconds.
- Marks a device's sensors unavailable when the connection fails or its read
  times out (20 seconds). Last values are retained for diagnosis but are not
  presented as available telemetry.
- Cancels listeners and closes its owned session when the integration unloads.

Inverter telemetry always uses WebSocket. Separate battery packs use HTTP every 5 minutes by default because some packs
do not support their own WebSocket. The **Use HTTP every 5 minutes for separate
battery packs** option can disable these reads for WebSocket-only battery
telemetry. Only discovered battery packs use `/device/get_device_snapshot`, every 300 seconds. There is no inverter
HTTP fallback. Battery request failures mark the battery unavailable; task
cancellation stops polling on unload.
HTTPS remains necessary for authentication, discovery, device metadata, alarms,
existing remote-setting functions, and explicitly requested historical queries.
This remains a **cloud** integration and needs Internet access.

Support requires a logger/device that provides Real-time Data in FSolar and an
accessible collector serial number. Missing collector information leaves that
device unavailable; the integration does not silently switch to slow snapshots.

## Installation and migration

Requires Home Assistant **2026.9.4 or newer**. Add this repository as a custom HACS
repository, category **Integration**:

`https://github.com/abeaudat/felicity-solar-websocket`

The domain is deliberately still `felicity_solar`. Install this fork **in place
of** the original/Smilebob files, not alongside them: both repositories provide
the same component. Keep only one HACS repository responsible for those files,
so an upstream update cannot overwrite the WebSocket implementation.

Before replacing files, back up Home Assistant and
`/config/custom_components/felicity_solar`. For manual installation, replace that
directory with `custom_components/felicity_solar` from this repository, or extract
the release ZIP into `/config/custom_components/felicity_solar`, then restart
Home Assistant.

**Keep the existing integration entry. Do not delete and recreate it.** Its
account configuration, entity unique IDs, device identifiers and entity history
remain associated with the same `felicity_solar` domain. The old HTTP polling
option is ignored; the new WebSocket option defaults to 5 seconds. Configure it
through Settings → Devices & services → Felicity Solar WebSocket → Configure.
This also fixes Smilebob's read-only `OptionsFlow.config_entry` assignment error.

### Power values when migrating

Some upstream inverter sensors exposed numbers in kW while declaring W. This
fork reports real **W** and maps PV Power to **total** PV generation, preserving
separate PV1/PV2 sensors. For example, 0.56 kW becomes 560 W. Existing historical
values are not rewritten.

Check any custom template that compensated for the upstream scale error: convert
the new W value to kW by dividing by 1000 when the template declares kW. Remove
old multiplication or unit-relabeling workarounds. This repository does not edit
your dashboards or templates automatically.

## Validation

Tests run against the real Home Assistant 2026.9.4 framework, with local aiohttp
WebSocket servers exercising receive pacing, device isolation, timeout,
reconnect, cancellation, unit normalization, retained partial fields, sensor
availability, entity IDs and the options flow. HTTP account discovery is tested
separately; no real credentials are used by CI.

```sh
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

### Tested hardware and versions

The following installation was tested on **2026-10-03**, running integration
**2.0.3** on **Home Assistant 2026.9.4**. The 26 automated tests also pass against
the real Home Assistant 2026.9.4 framework on Python 3.14.

| Device | Model | Rating reported by FSolar | Telemetry verified in Home Assistant |
| --- | --- | --- | --- |
| Inverter | Felicity Solar **IVGM15KLP3G1** | 15 kW | WebSocket reads at approximately 5-second intervals, with TLS verification enabled |
| Separate battery pack | Felicity Solar **FLA48300TG2** | 300 Ah; 15 kWh reported by the battery API | Authenticated HTTP snapshots at approximately 5-minute intervals, including BMS SOC and remaining energy |

Version values below were read directly from the **Shine / FSolar device detail
pages** on the same date. Field names match the portal's labels; hardware and
firmware versions are listed separately.

**IVGM15KLP3G1 inverter**

| FSolar version field | Tested value |
| --- | --- |
| Master Version | `128` |
| Slave Version | `123` |
| Comm Version | `308.06.005` |
| Hardware Version | `261` |
| Firmware Version | `100` |

**FLA48300TG2 battery pack**

| FSolar version field | Tested value |
| --- | --- |
| Master Version | `524` |
| IAP Version | `8` |
| Sub Version | `0` |

The battery did not answer its own energy-flow WebSocket, including when tested
without the inverter connection. The default HTTP battery reads restore its BMS
entities and battery-based dashboard estimates; these entities remain unavailable
in WebSocket-only mode. The inverter continues to use WebSocket independently.

These were live telemetry and dashboard checks, not a long-term endurance test
or a physical-control test. Missing lifetime energy counters are reported as
unknown rather than zero. This records one verified hardware/firmware combination;
compatibility with other models, versions or loggers is not established by these
tests.

## Credits and license

MIT license. Preserve the attribution in [LICENSE](LICENSE). Thanks to Matheus
Trindade, Pierre / Smilebob, Fábio Matavelli, and the original contributors.
