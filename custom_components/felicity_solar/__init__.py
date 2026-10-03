import logging
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform

from .const import DOMAIN, CONF_EMAIL, CONF_PASSWORD, CONF_REALTIME_INTERVAL, DEFAULT_REALTIME_INTERVAL, CONF_BATTERY_HTTP, DEFAULT_BATTERY_HTTP
from .coordinator import FelicitySolarCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.SWITCH,
]

SERVICE_SET_SETTING = "set_device_setting"
SERVICE_SET_ECO_RULE = "set_eco_rule"
SERVICE_QUERY_ENERGY = "query_energy_data"
SERVICE_QUERY_HISTORY = "query_history_data"


def _get_coordinator_for_device(hass: HomeAssistant, device_sn: str) -> FelicitySolarCoordinator | None:
    domain_data = hass.data.get(DOMAIN, {})
    for coordinator in domain_data.values():
        if isinstance(coordinator, FelicitySolarCoordinator):
            if coordinator.data and device_sn in coordinator.data:
                return coordinator
            if device_sn in coordinator.api.get_devices_serial_numbers():
                return coordinator
    for coordinator in domain_data.values():
        if isinstance(coordinator, FelicitySolarCoordinator):
            return coordinator
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Felicity Solar from a config entry."""
    _LOGGER.info("Setting up Felicity Solar integration for %s", entry.data.get(CONF_EMAIL, "unknown"))
    hass.data.setdefault(DOMAIN, {})

    # Preserve the account config; use a separate realtime option from legacy HTTP polling
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    update_interval = int(entry.options.get(CONF_REALTIME_INTERVAL, entry.data.get(CONF_REALTIME_INTERVAL, DEFAULT_REALTIME_INTERVAL)))

    _LOGGER.info("WebSocket telemetry interval set to %d seconds", update_interval)

    # Boot up the background worker
    coordinator = FelicitySolarCoordinator(
        hass=hass,
        email=email,
        password=password,
        update_interval=update_interval,
        config_entry=entry,
        battery_http_polling=bool(entry.options.get(CONF_BATTERY_HTTP, DEFAULT_BATTERY_HTTP)),
    )

    async def async_stop_streams(_event):
        await coordinator.async_close()

    entry.async_on_unload(hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STOP, async_stop_streams,
    ))

    # Listen for options changes (update interval adjustment)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Fetch the very first batch of data before creating the entities
    try:
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        await coordinator.async_close()
        raise

    # Store the coordinator in memory
    hass.data[DOMAIN][entry.entry_id] = coordinator

    _LOGGER.info(
        "First refresh complete, found %d device(s), forwarding setup to platforms",
        len(coordinator.data) if coordinator.data else 0,
    )

    # Forward setup to all platforms
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    # Register custom Home Assistant services
    async def async_handle_set_setting(call: ServiceCall):
        device_sn = str(call.data.get("device_sn"))
        params = call.data.get("params", {})
        coord = _get_coordinator_for_device(hass, device_sn)
        if not coord:
            _LOGGER.error("Coordinator not found for device %s", device_sn)
            return {"success": False, "error": "Device coordinator not found"}
        success = await coord.api.set_device_setting(device_sn, params)
        if success:
            await coord.async_request_refresh()
        return {"success": success}

    async def async_handle_set_eco_rule(call: ServiceCall):
        device_sn = str(call.data.get("device_sn"))
        rule_index = int(call.data.get("rule_index", 1))
        coord = _get_coordinator_for_device(hass, device_sn)
        if not coord:
            _LOGGER.error("Coordinator not found for device %s", device_sn)
            return {"success": False, "error": "Device coordinator not found"}

        rule_dict = {}
        for field in ["rule_mode", "start_time", "stop_time", "power", "soc", "voltage", "start_day", "stop_day", "days_of_effective_week"]:
            if field in call.data:
                camel_field = "".join(word.capitalize() if i > 0 else word for i, word in enumerate(field.split("_")))
                if field == "rule_mode":
                    try:
                        rule_dict[camel_field] = int(call.data[field])
                    except (ValueError, TypeError):
                        rule_dict[camel_field] = call.data[field]
                else:
                    rule_dict[camel_field] = call.data[field]

        success = await coord.api.set_device_setting(device_sn, {f"ecoRule{rule_index}": rule_dict})
        if success:
            await coord.async_request_refresh()
        return {"success": success}

    async def async_handle_query_energy(call: ServiceCall):
        device_sn = str(call.data.get("device_sn"))
        time_dim = str(call.data.get("time_dimension", "day"))
        date_str = call.data.get("date_str")
        coord = _get_coordinator_for_device(hass, device_sn)
        if not coord:
            _LOGGER.error("Coordinator not found for device %s", device_sn)
            return {"error": "Device coordinator not found"}
        return await coord.api.get_device_energy_data(device_sn, time_dimension=time_dim, date_str=date_str)

    async def async_handle_query_history(call: ServiceCall):
        device_sn = str(call.data.get("device_sn"))
        date_str = call.data.get("date_str")
        coord = _get_coordinator_for_device(hass, device_sn)
        if not coord:
            _LOGGER.error("Coordinator not found for device %s", device_sn)
            return {"error": "Device coordinator not found"}
        return await coord.api.get_device_history_data(device_sn, date_str=date_str)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_SETTING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_SETTING,
            async_handle_set_setting,
            supports_response=SupportsResponse.OPTIONAL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_ECO_RULE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_ECO_RULE,
            async_handle_set_eco_rule,
            supports_response=SupportsResponse.OPTIONAL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_QUERY_ENERGY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_QUERY_ENERGY,
            async_handle_query_energy,
            supports_response=SupportsResponse.OPTIONAL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_QUERY_HISTORY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_QUERY_HISTORY,
            async_handle_query_history,
            supports_response=SupportsResponse.OPTIONAL,
        )

    _LOGGER.info("Felicity Solar integration setup complete with services registered")
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update coordinator update interval when options change."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator and isinstance(coordinator, FelicitySolarCoordinator):
        battery_http = bool(entry.options.get(CONF_BATTERY_HTTP, DEFAULT_BATTERY_HTTP))
        if coordinator.battery_http_polling != battery_http:
            await hass.config_entries.async_reload(entry.entry_id)
            return
        new_interval = int(entry.options.get(CONF_REALTIME_INTERVAL, DEFAULT_REALTIME_INTERVAL))
        coordinator.set_realtime_interval(new_interval)
        _LOGGER.info("Felicity Solar WebSocket interval changed to %d seconds", new_interval)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry (e.g. if the user clicks Delete)."""
    _LOGGER.info("Unloading Felicity Solar integration for %s", entry.data.get(CONF_EMAIL, "unknown"))

    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if coordinator:
            await coordinator.async_close()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            for service in (
                SERVICE_SET_SETTING,
                SERVICE_SET_ECO_RULE,
                SERVICE_QUERY_ENERGY,
                SERVICE_QUERY_HISTORY,
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
            hass.data.pop(DOMAIN, None)
            _LOGGER.info("All Felicity Solar instances unloaded; services removed")
        else:
            _LOGGER.info("Felicity Solar integration entry unloaded successfully")
    else:
        _LOGGER.warning("Failed to unload Felicity Solar integration")
    return unload_ok
