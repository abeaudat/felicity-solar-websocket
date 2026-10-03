"""FSolar telemetry transport. No HTTP snapshot requests or device settings."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import logging
import math

import aiohttp

_LOGGER = logging.getLogger(__name__)
WS_BASE_URL = "wss://shine-api.felicitysolar.com/socket/energy-flow"

# These inverter snapshot fields use the snapshot's power unit. Battery bmsPower
# and emsPowerTotal are already W and must not be multiplied with them.
INVERTER_POWER_FIELDS = {
    "pvPower", "pv1Power", "pv2Power", "pv3Power", "pv4Power", "pvTotalPower",
    "pvPower1", "pvPower2", "pvPower3", "pvPower4",
    "acRInPower", "acSInPower", "acTInPower", "acTtlInpower", "acTtlInPower",
    "acROutPower", "acSOutPower", "acTOutPower", "acTotalOutActPower",
    "acTotalOutAppaPower", "emsPower", "emsPower2", "genPower", "genTotalPower",
    "genPower2", "genPower3", "smartTotalPower", "smartLoadPower",
    "smartLoadTotalPower", "totalConsumPower", "meterPower", "familyLoadPower",
}


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def normalize_snapshot(frame: dict, previous_scale: float = 1.0) -> tuple[dict, float]:
    """Normalize a live snapshot to W without guessing from power magnitude.

    The envelope is in W, while IVGM's nested snapshot is in kW. Other devices
    can report W. Prefer the declared unit, then the observed envelope/snapshot
    ratio; remember the last confirmed scale when all reference powers are zero.
    """
    snapshot = dict(frame["deviceSnapshot"])
    scale = previous_scale
    unit = str(snapshot.get("powerUnit", "")).strip().lower()
    if unit in ("kw", "kva"):
        scale = 1000.0
    elif unit in ("w", "va"):
        scale = 1.0
    else:
        for key in ("pvTotalPower", "acTotalOutActPower", "emsPower"):
            outer, inner = _number(frame.get(key)), _number(snapshot.get(key))
            if outer is None or inner is None or inner == 0:
                continue
            ratio = outer / inner
            if math.isclose(ratio, 1000.0, rel_tol=0.02):
                scale = 1000.0
                break
            if math.isclose(ratio, 1.0, rel_tol=0.02):
                scale = 1.0
                break
    for key in INVERTER_POWER_FIELDS:
        value = _number(snapshot.get(key))
        if value is not None:
            snapshot[key] = round(value * scale, 6)
        elif key in snapshot:
            snapshot[key] = None
    # The envelope gives authoritative W totals, including true zero values.
    for key in ("pvTotalPower", "emsPower", "acTotalOutActPower", "meterPower",
                "genPower", "totalConsumPower"):
        value = _number(frame.get(key))
        if value is not None:
            snapshot[key] = value
    if _number(frame.get("acTtlInPower")) is not None:
        snapshot["acTtlInpower"] = _number(frame["acTtlInPower"])
    snapshot["powerUnit"] = "W"
    return snapshot, scale


class FelicityRealtimeClient:
    """One bounded request/response stream per account-owned device.

    A new read is sent only after the previous response, at most once per
    configured interval. Silence closes the stream and causes reconnect.
    """

    def __init__(self, session: aiohttp.ClientSession, device_sn: str,
                 collector_sn: str, on_frame: Callable[[dict], None],
                 on_status: Callable[[bool], None], interval: float = 5,
                 response_timeout: float = 20, *, url: str | None = None):
        self.session = session
        self.device_sn = str(device_sn)
        self.collector_sn = str(collector_sn)
        self.on_frame = on_frame
        self.on_status = on_status
        self.interval = interval
        self.response_timeout = response_timeout
        self.url = url or f"{WS_BASE_URL}/{self.device_sn}"
        self.first_frame = asyncio.Event()
        self.last_received: datetime | None = None
        self._task: asyncio.Task | None = None
        self._backoff = 1.0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="felicity_realtime")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _receive_frame(self, socket) -> dict:
        # Ignore acknowledgements, malformed frames, and frames for another
        # device without extending the timeout or changing sensor freshness.
        async with asyncio.timeout(self.response_timeout):
            while True:
                message = await socket.receive()
                if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE,
                                    aiohttp.WSMsgType.ERROR):
                    raise ConnectionError("FSolar telemetry stream closed")
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    frame = message.json()
                except (ValueError, TypeError):
                    continue
                if (isinstance(frame, dict)
                        and str(frame.get("deviceSn", "")) == self.device_sn
                        and isinstance(frame.get("deviceSnapshot"), dict)
                        and frame["deviceSnapshot"]):
                    return frame

    async def _run_connected(self) -> None:
        # This is the vendor portal's read command, not a settings command.
        async with self.session.ws_connect(
            self.url, heartbeat=15, max_msg_size=1024 * 1024,
        ) as socket:
            loop = asyncio.get_running_loop()
            while True:
                requested_at = loop.time()
                await socket.send_json({
                    "type": "command",
                    "deviceCommand": {"deviceSn": self.device_sn,
                                      "collectorSn": self.collector_sn},
                })
                frame = await self._receive_frame(socket)
                self.on_frame(frame)
                self.last_received = datetime.now(timezone.utc)
                self.on_status(True)
                self.first_frame.set()
                self._backoff = 1.0
                await asyncio.sleep(max(0, self.interval - (loop.time() - requested_at)))

    async def _run(self) -> None:
        try:
            while True:
                try:
                    await self._run_connected()
                except Exception:
                    self.on_status(False)
                    _LOGGER.debug("FSolar telemetry disconnected; retrying in %.0fs",
                                  self._backoff, exc_info=True)
                    await asyncio.sleep(self._backoff)
                    self._backoff = min(self._backoff * 2, 60.0)
        finally:
            self.on_status(False)
