"""Account discovery uses HTTPS metadata, never HTTP telemetry snapshots."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import aiohttp
from aiohttp import web
import pytest

from custom_components.felicity_solar.api import FelicitySolarAPI
from tests.test_realtime import server


async def test_authenticated_discovery_retains_collectors_and_all_pages():
    requests = []
    async def handler(request):
        assert request.headers['authorization'] == 'test-token'
        body = await request.json()
        requests.append(body)
        count = 100 if body['pageNum'] == 1 else 1
        rows = [{'deviceSn': str((body['pageNum'] - 1) * 100 + i),
                 'collectorSn': f'logger-{i}', 'deviceType': 'INV'}
                for i in range(1, count + 1)]
        return web.json_response({'code': 0, 'data': {'dataList': rows}})
    async with server(handler, method='POST') as url, aiohttp.ClientSession() as session:
        api = FelicitySolarAPI('account@example.invalid', 'unused', session)
        api.API_URL_DEVICE_LIST = url
        api.bearer_token = 'test-token'
        api.token_expiration = datetime.now() + timedelta(hours=1)
        api._load_from_file = AsyncMock()
        api._login = AsyncMock()
        await api.initialize()
        assert len(api.devices) == 101
        assert api.devices['101']['collectorSn'] == 'logger-1'
        assert api.get_devices_serial_numbers() == list(api.devices)
        assert [r['pageNum'] for r in requests] == [1, 2]
        api._login.assert_not_awaited()


async def test_discovery_failure_does_not_replace_known_devices():
    async def handler(request):
        return web.json_response({'code': 401, 'data': None})
    async with server(handler, method='POST') as url, aiohttp.ClientSession() as session:
        api = FelicitySolarAPI('account@example.invalid', 'unused', session)
        api.API_URL_DEVICE_LIST = url
        api.bearer_token = 'test-token'
        api.devices = {'existing': {'collectorSn': 'known'}}
        with pytest.raises(ValueError, match='discovery failed'):
            await api._load_devices_serial_numbers()
        assert 'existing' in api.devices


async def test_opt_in_battery_snapshot_request_and_serial_isolation():
    expected_sn = 'battery'
    returned_sn = 'battery'
    requests = []
    async def handler(request):
        body = await request.json()
        assert request.headers['authorization'] == 'test-token'
        requests.append(body)
        return web.json_response({'code': 200, 'data': {
            'deviceSn': returned_sn, 'battSoc': 80, 'ratedEnergy': 15,
        }})
    async with server(handler, method='POST') as url, aiohttp.ClientSession() as session:
        api = FelicitySolarAPI('account@example.invalid', 'unused', session)
        api.API_URL_BATTERY_SNAPSHOT = url
        api.bearer_token = 'test-token'
        api.token_expiration = datetime.now() + timedelta(hours=1)
        api.devices = {expected_sn: {'deviceType': 'BP'}}
        result = await api.get_battery_snapshot(expected_sn)
        assert result['battSoc'] == 80
        assert requests[0]['deviceSn'] == expected_sn
        assert requests[0]['deviceType'] == 'BP'
        returned_sn = 'different-battery'
        with pytest.raises(ValueError, match='mismatch'):
            await api.get_battery_snapshot(expected_sn)
