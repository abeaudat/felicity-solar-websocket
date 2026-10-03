"""Exercise actual aiohttp sockets, timeout, isolation, reconnect and shutdown."""
import asyncio
from contextlib import asynccontextmanager

import aiohttp
from aiohttp import web
import pytest

from custom_components.felicity_solar.realtime import (
    FelicityRealtimeClient, normalize_snapshot,
)


@asynccontextmanager
async def server(handler, path='/stream', method='GET'):
    app = web.Application()
    app.router.add_route(method, path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f'http://127.0.0.1:{port}{path}'
    finally:
        await runner.cleanup()


def frame(sn='inverter'):
    return {'deviceSn': sn, 'pvTotalPower': '560', 'emsPower': '-800',
            'acTotalOutActPower': '1200',
            'deviceSnapshot': {'pvTotalPower': '0.56', 'pvPower': '0.33',
                               'pv2Power': '0.23', 'emsPower': '-0.8',
                               'acTotalOutActPower': '1.2', 'emsPowerTotal': '-800'}}


def test_watts_and_kilowatts_are_normalized_without_double_scaling():
    snapshot, scale = normalize_snapshot(frame())
    assert scale == 1000
    assert snapshot['pvTotalPower'] == 560
    assert snapshot['pvPower'] == 330
    assert snapshot['pv2Power'] == 230
    assert snapshot['emsPower'] == -800
    assert snapshot['emsPowerTotal'] == '-800'
    assert snapshot['acTotalOutActPower'] == 1200


def test_zero_uses_confirmed_units_and_zero_envelope_is_authoritative():
    message = frame()
    message.update(pvTotalPower='0', emsPower='0', acTotalOutActPower='0')
    message['deviceSnapshot'].update(pvTotalPower='0', emsPower='0', acTotalOutActPower='0')
    snapshot, scale = normalize_snapshot(message, previous_scale=1000)
    assert scale == 1000
    assert snapshot['pvTotalPower'] == snapshot['emsPower'] == 0


@pytest.mark.parametrize('unit,raw,expected', [('W', 560, 560), ('kW', 0.56, 560)])
def test_declared_power_units(unit, raw, expected):
    snapshot, _ = normalize_snapshot({'deviceSnapshot': {'powerUnit': unit, 'pvPower': raw}})
    assert snapshot['pvPower'] == expected


def test_nonfinite_values_are_not_published_as_power():
    snapshot, _ = normalize_snapshot({'pvTotalPower': 'NaN', 'deviceSnapshot': {'pvPower': None}})
    assert 'pvTotalPower' not in snapshot


async def test_stream_ignores_other_devices_and_paces_read_commands():
    requests, frames, statuses = [], [], []
    times = []
    async def handler(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            requests.append(message.json())
            times.append(asyncio.get_running_loop().time())
            await socket.send_str('bad JSON')
            await socket.send_json(frame('someone-else'))
            await socket.send_json(frame())
        return socket
    async with server(handler) as url, aiohttp.ClientSession() as session:
        client = FelicityRealtimeClient(session, 'inverter', 'logger', frames.append,
                                       statuses.append, interval=.03, url=url)
        client.start()
        await asyncio.wait_for(client.first_frame.wait(), 1)
        await asyncio.sleep(.09)
        await client.stop()
        count = len(frames)
        await asyncio.sleep(.04)
        assert len(frames) == count
        assert count >= 2
        assert all(item['deviceSn'] == 'inverter' for item in frames)
        assert all(item == {'type': 'command', 'deviceCommand': {
            'deviceSn': 'inverter', 'collectorSn': 'logger'}} for item in requests)
        assert all(b - a >= .025 for a, b in zip(times, times[1:]))
        assert statuses[-1] is False
        assert not session.closed  # Caller owns the session.


async def test_silence_invalidates_freshness_and_reconnect_recovers():
    connections, statuses, frames = [], [], []
    async def handler(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        connections.append(socket)
        async for message in socket:
            if len(connections) > 1:
                await socket.send_json(frame())
            else:
                # An unrelated frame must not count as valid telemetry.
                await socket.send_json(frame('other-device'))
        return socket
    async with server(handler) as url, aiohttp.ClientSession() as session:
        client = FelicityRealtimeClient(session, 'inverter', 'logger', frames.append,
                                       statuses.append, interval=.02,
                                       response_timeout=.03, url=url)
        client._backoff = .01
        client.start()
        await asyncio.wait_for(client.first_frame.wait(), 1)
        await client.stop()
        assert len(connections) >= 2
        assert frames
        assert statuses[0] is False
        assert True in statuses


async def test_stop_cancels_waiting_reader_without_leaking_task():
    async def handler(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            pass
        return socket
    async with server(handler) as url, aiohttp.ClientSession() as session:
        client = FelicityRealtimeClient(session, 'inverter', 'logger', lambda _: None,
                                       lambda _: None, url=url)
        client.start()
        await asyncio.sleep(.02)
        task = client._task
        await asyncio.wait_for(client.stop(), .5)
        assert task.done()
        assert client._task is None
