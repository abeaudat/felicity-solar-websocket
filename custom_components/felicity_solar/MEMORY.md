# 📦 Module Memory: Felicity Solar Component (`custom_components/felicity_solar/`)

> **Directory**: `custom_components/felicity_solar/` | **Last Updated**: 2026-10-26 | **Fork version**: 2.0.5

## 🎯 Role & Responsibility
Contains the Home Assistant integration code: continuous FSolar WebSocket telemetry for inverters, a Felicity Shine REST client for account/metadata and separate battery snapshots, a push DataUpdateCoordinator, UI ConfigFlow, and dynamic entities.

---

## 🗂️ Key Files & Components
| File / Module | Role | Key Inputs / Outputs |
| :--- | :--- | :--- |
| [`__init__.py`](__init__.py) | Component Entry Point & Services | Registers platforms (sensor, select, number, switch) & 4 HA services |
| [`api.py`](api.py) | Felicity Shine REST API Client | Authentication, discovery, separate battery snapshots, metadata, warnings, settings, history queries |
| [`realtime.py`](realtime.py) | Continuous WebSocket receiver and paced commands | Per-device pushes, response retry, bounded freshness, reconnect and cancellation |
| [`coordinator.py`](coordinator.py) | Push Telemetry & Device Discovery | Maps normalized live snapshots and separately polls battery packs; `update_interval=None` |
| [`config_flow.py`](config_flow.py) | UI Configuration Flow | Email, password, update interval setup |
| [`sensor.py`](sensor.py) | Sensor Platform | Dynamic sensor entity factory |
| [`sensors_inverter.py`](sensors_inverter.py) | Inverter Sensors (105) | Grid Feed-In/Import energies (HA Energy Dashboard), daily/monthly/yearly battery & PV energies, Smart Load port, generator energies & L2-L3 powers, meter status, EMS capacity, native work mode, plus all previous telemetry |
| [`sensors_battery.py`](sensors_battery.py) | Battery Sensors (49) | Voltage, current, SOC, SOH, individual cell voltages 1–16 (mV with V/mV auto-detect & clean availability), cell min/max mV & probe IDs, dV Cells (mV), cell temps (1-4), BMS charge/discharge current limits, sanitized cell count, battery type, BMS status, connected inverter SN |
| [`select.py`](select.py) | Select Controls (5) | `Work Mode`, `Energy Priority`, `Zero Export Mode`, `AC Output Freq`, `Battery Model` |
| [`number.py`](number.py) | Number Controls (11) | Charge/discharge currents, discharge depth SOC, charge/float volts, generator limits |
| [`switch.py`](switch.py) | Switch Controls (10) | `Grid Charge`, `Buzzer`, `LCD Backlight`, `Remote Standby`, `AC Output Relay`, etc. |
| [`services.yaml`](services.yaml) | HA Service Schemas | UI definitions for `set_device_setting`, `set_eco_rule`, `query_energy_data`, `query_history_data` |

---

## 🔄 Dependencies & Data Flow
- **External API**: Shine Felicity Solar OpenAPI (`https://shine-api.felicitysolar.com`).
- **Data Flow**:
  - `FelicitySolarCoordinator` discovers account-owned devices and their collectors, then creates a WebSocket client per inverter. Metadata, warnings and settings are separate HTTPS queries.
  - `realtime.py` continuously consumes valid pushes while a separate task paces read commands. Never put a command-interval sleep in the receiver: it lets old frames queue and appear fresh.
  - Optional separate battery HTTP polling calls `get_battery_snapshot()` every 300 seconds; there is no inverter HTTP snapshot method or fallback.
  - `normalize_snapshot()` converts nested inverter powers to W, preserves authoritative W envelope totals and canonicalizes live energy-counter names. The coordinator retains fields omitted by partial messages.
  - Stored in `coordinator.data[device_sn]` with separate `"data"` (telemetry) and `"settings"` (controls) dictionaries.
  - Entities inherit from `CoordinatorEntity` and update state reactively or optimistically.
  - Controls dispatch writes to `FelicitySolarAPI.set_device_setting()`, followed by `async_request_refresh()`.

---

## ⚠️ Technical Gotchas
- **TLS**: HTTP and WebSocket sessions use normal certificate verification. Do not reintroduce the upstream certificate-verification bypass.
- **Dynamic Model Identification**: Never hardcode model strings; read dynamically from `deviceModel` or `modelName`.
- **API Return Codes**: `998`/`999` (token expired, triggers re-auth), `1006051` (device unreachable), `2001528` (permission denied on OpenAPI layer; automatically halts unpermitted calls to silence log spam).
- **Target Inverter Controls**: Parameter writes (`/openApi/cmd/deviceSetting`) target inverter serial numbers, not standalone battery pack serial numbers. Control entities are instantiated only when settings are permitted and available.
- **Update Interval**: Read commands default to 5s (2–60s in Options Flow); reception is continuous. Separate battery snapshots use 300s. A missing valid frame for 20s invalidates freshness; retries/invalid messages do not extend that deadline.
- **Lifecycle**: Reader and sender share a `TaskGroup`. Unload must cancel both plus battery tasks before closing the owned session. Preserve same-socket retries and reconnect backoff.
- **Release**: Keep the manifest version, source tag and release ZIP aligned. A source commit alone is not a HACS release. See the root README and changelog for tests and observed hardware checks.
