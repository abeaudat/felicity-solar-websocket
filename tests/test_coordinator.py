"""Run the coordinator with the installed Home Assistant framework."""
from unittest.mock import AsyncMock
from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest

from custom_components.felicity_solar.api import DeviceTypeEnum, FelicitySolarAPI
from custom_components.felicity_solar.coordinator import FelicitySolarCoordinator
from custom_components.felicity_solar.config_flow import FelicitySolarOptionsFlowHandler
from custom_components.felicity_solar.sensors_inverter import (
    FelicityInverterSensor, INVERTER_DESCRIPTIONS,
)
from custom_components.felicity_solar.sensors_battery import (
    FelicityBatterySensor, BATTERY_DESCRIPTIONS,
)
from tests.test_realtime import frame, server


@pytest.fixture
async def coordinator(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    entry = ConfigEntry(data={'email': 'test@example.invalid', 'password': 'test'},
                        discovery_keys=MappingProxyType({}), domain='felicity_solar',
                        minor_version=1, options={}, source='user', title='Test',
                        unique_id=None, version=1, subentries_data=[],
                        state=ConfigEntryState.SETUP_IN_PROGRESS)
    coord = FelicitySolarCoordinator(hass, 'test@example.invalid', 'test', config_entry=entry)
    coord._metadata['inverter'] = {
        'productTypeEnum': DeviceTypeEnum.HYBRID_INVERTER,
        'collectorSn': 'logger', 'deviceModel': 'IVGM15KLP3G1',
        'warnings': [], 'settings': {'workMode': 3},
    }
    yield coord
    await coord.async_close()
    await hass.async_stop()


async def test_existing_entity_ids_and_power_values(coordinator):
    coordinator._on_frame('inverter', frame())
    values = coordinator.data['inverter']['data']
    assert values['pvPower'] == values['pvTotalPower'] == 560
    assert values['pv1Power'] == 330
    assert values['pv2Power'] == 230
    assert values['batteryPower'] == -800
    assert values['batteryDischargingPower'] == 800
    assert values['acTotalOutputActivePower'] == 1200
    description = next(d for d in INVERTER_DESCRIPTIONS if d.key == 'pvPower')
    sensor = FelicityInverterSensor(coordinator, 'inverter', description)
    assert sensor.unique_id == 'inverter_pvPower'
    assert sensor.native_value == 560
    assert sensor.available
    coordinator._on_status('inverter', False)
    assert not sensor.available
    assert sensor.native_value == 560  # Retained for diagnosis, unavailable for use.


async def test_partial_frames_preserve_energy_and_true_zero_soc(coordinator):
    full = frame()
    full['deviceSnapshot'].update(ePvToday='29.2', emsSoc='50')
    coordinator._on_frame('inverter', full)
    coordinator._on_frame('inverter', {
        'deviceSn': 'inverter', 'pvTotalPower': '0', 'emsPower': '0',
        'deviceSnapshot': {'emsSoc': '0', 'emsPower': '0'},
    })
    values = coordinator.data['inverter']['data']
    assert values['pvPower'] == 0
    assert values['batterySoc'] == 0
    assert values['energyPvToday'] == 29.2
    assert coordinator.data['inverter']['settings'] == {'workMode': 3}


async def test_live_lowercase_energy_counters_and_missing_totals(coordinator):
    message = frame()
    message['deviceSnapshot'].update(eloadToday='22.6', eloadTotal='179.4',
                                     eloadMonth='72.1', eloadYear='179.3',
                                     epvMonth='95.2', epvYear='224.1')
    coordinator._on_frame('inverter', message)
    values = coordinator.data['inverter']['data']
    assert values['energyLoadToday'] == 22.6
    assert values['energyLoadTotal'] == 179.4
    assert values['energyLoadMonth'] == 72.1
    assert values['energyLoadYear'] == 179.3
    assert values['energyPvMonth'] == 95.2
    assert values['energyPvYear'] == 224.1
    assert values['energyPvTotal'] is None  # Missing counter must not reset to zero.

    coordinator._on_frame('inverter', {'deviceSn': 'inverter',
                                      'deviceSnapshot': {'eloadToday': '0'}})
    assert coordinator.data['inverter']['data']['energyLoadToday'] == 0


async def test_no_http_snapshot_api_or_polling(coordinator):
    assert not hasattr(FelicitySolarAPI, 'get_device_snapshot')
    assert not hasattr(FelicitySolarAPI, 'API_URL_DEVICE_SNAPSHOT')
    assert coordinator.update_interval is None
    coordinator._on_frame('inverter', frame())
    coordinator._initialized = True
    coordinator.api.get_device_warnings = AsyncMock(return_value=[])
    coordinator.api.get_device_settings = AsyncMock(return_value={})
    result = await coordinator._async_update_data()
    assert result['inverter']['data']['pvPower'] == 560
    assert result['inverter']['settings'] == {'workMode': 3}


async def test_battery_stream_keeps_bms_watts_and_entity_ids(coordinator):
    coordinator._metadata['battery'] = {
        'productTypeEnum': DeviceTypeEnum.LITHIUM_BATTERY_PACK,
        'collectorSn': 'battery-logger', 'warnings': [], 'settings': {},
    }
    coordinator._on_frame('battery', {
        'deviceSn': 'battery', 'deviceSnapshot': {
            'productTypeEnum': 'LITHIUM_BATTERY_PACK', 'powerUnit': 'W',
            'bmsPower': '-903.34', 'battVolt': '53.77', 'battCurr': '-16.8',
            'battSoc': '70', 'battCapacity': '300', 'bmsChargingState': 2,
            'bmsFlag': True, 'cellVolt1': '3382',
        },
    })
    entry = coordinator.data['battery']
    assert entry['type'] == DeviceTypeEnum.LITHIUM_BATTERY_PACK
    assert entry['data']['power'] == -903.34
    description = next(d for d in BATTERY_DESCRIPTIONS if d.key == 'soc')
    sensor = FelicityBatterySensor(coordinator, 'battery', description)
    assert sensor.unique_id == 'battery_soc'
    assert sensor.native_value == 70
    assert sensor.available
    coordinator._on_status('battery', False)
    assert not sensor.available


async def test_options_flow_uses_home_assistant_readonly_config_entry():
    # Constructor previously tried to assign config_entry and raised the exact
    # AttributeError observed on HA 2026.9.4. Exercise the real HA class.
    flow = FelicitySolarOptionsFlowHandler()
    result = await flow.async_step_init({'realtime_interval': 5})
    assert result['data'] == {'realtime_interval': 5}


async def test_update_interval_adjusts_existing_readers(coordinator):
    from types import SimpleNamespace
    client = SimpleNamespace(interval=5)
    coordinator._clients['inverter'] = client
    coordinator.set_realtime_interval(10)
    assert client.interval == 10
    coordinator._clients.clear()


async def test_initial_refresh_discovers_device_and_starts_real_stream(coordinator, monkeypatch):
    from aiohttp import web
    from custom_components.felicity_solar import realtime
    from custom_components.felicity_solar.sensor import async_setup_entry
    from custom_components.felicity_solar.const import DOMAIN
    from types import SimpleNamespace

    commands = []
    async def handler(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            commands.append(message.json())
            await socket.send_json(frame())
        return socket

    coordinator._metadata.clear()
    coordinator.api.devices = {'inverter': {
        'deviceSn': 'inverter', 'collectorSn': 'logger', 'deviceType': 'INV',
    }}
    coordinator.api.initialize = AsyncMock()
    coordinator.api.get_device_basic_info = AsyncMock(return_value={})
    coordinator.api.get_device_warnings = AsyncMock(return_value=[])
    coordinator.api.get_device_settings = AsyncMock(return_value={})
    async with server(handler, path='/inverter') as url:
        monkeypatch.setattr(realtime, 'WS_BASE_URL', url.rsplit('/', 1)[0])
        await coordinator.async_config_entry_first_refresh()
        assert coordinator.data['inverter']['data']['pvPower'] == 560
        assert coordinator.data['inverter']['realtime_available']
        assert commands == [{'type': 'command', 'deviceCommand': {
            'deviceSn': 'inverter', 'collectorSn': 'logger'}}]
        coordinator.hass.data[DOMAIN] = {'entry': coordinator}
        entities = []
        await async_setup_entry(coordinator.hass, SimpleNamespace(entry_id='entry'), entities.extend)
        assert any(e.unique_id == 'inverter_pvPower' and e.available for e in entities)
        tasks = [client._task for client in coordinator._clients.values()]
        await coordinator.async_close()
        assert coordinator._session.closed
        assert all(task.done() for task in tasks)
