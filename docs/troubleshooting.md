# Comparing FSolar and Home Assistant telemetry

If FSolar and a dashboard disagree, compare the sources before deleting the
integration or changing equipment settings. This integration keeps the existing
`felicity_solar` account entry and entity identifiers.

## Compare the same device and measurement

1. Open the inverter's **Real-time Data** view in FSolar. A plant overview or
   historical snapshot can update at a different rate.
2. Read the corresponding inverter entities in Home Assistant Developer Tools.
   Compare PV total power, AC output, battery power/SOC and daily energy counters.
3. Check units: inverter entities report W; a dashboard helper displaying kW
   should divide by 1000. Daily energy counters are kWh.
4. Inspect the dashboard's entity references and any templates. Compare source
   entities before attributing a difference to rendering or a template.

Separate battery packs use authenticated HTTP snapshots every five minutes by
default. Their values and timestamps can legitimately differ from the inverter's
live values. Battery SOC and remaining energy should be interpreted with their
source and sampling time in mind.

## Distinguish changing data from current data

Home Assistant's `last_updated` is not the device measurement time: unchanged
values may retain an older timestamp, and an old queued frame can change an
entity when it is finally consumed. A moving dashboard alone does not prove
that the stream is current.

In versions before 2.0.5, incoming pushes could queue behind the command interval.
Reconnecting cleared that queue temporarily. Version 2.0.5 consumes incoming
messages continuously, independently of the command schedule.

## Capture an intermittent gap

From the integration menu in **Settings → Devices & services**, enable debug
logging for the duration of the observation, then stop it and download the log.
For a narrower capture, the following Developer Tools action enables only the
WebSocket transport logger:

```yaml
action: logger.set_level
data:
  custom_components.felicity_solar.realtime: debug
```

Record the observation time, inverter availability and values, FSolar's live
view, and relevant Internet/connectivity measurements. If the integration becomes
unavailable while FSolar still shows data, check whether those values are from
live messages or historical cloud uploads. Historical data during a gap proves
cloud uploads continued; it does not identify which part of the live transport
failed.

Transport logs include delayed-response retries and disconnect tracebacks. They
do not intentionally log telemetry payloads or account credentials. Review any
downloaded logs before sharing them, since other integration modules can include
account or device details. Restore the transport logger to its inherited level
when the capture is finished:

```yaml
action: logger.set_level
data:
  custom_components.felicity_solar.realtime: notset
```

## Install the fix while preserving configuration

Back up `/config/custom_components/felicity_solar`, install the release using HACS
or the release ZIP, and restart Home Assistant so the Python modules reload.
Keep the account entry, then compare the live source and HA again for several
minutes. Check that the integration is loaded and that normal automation states
have been restored. A restart interrupts Home Assistant while it boots.

The integration does not rewrite dashboards or old recorded statistics. Existing
remote controls remain available where the FSolar account permits them; they
are not needed to test telemetry freshness.
