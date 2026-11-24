"""Nest Doorbell Announcements: native HA actions over a replaceable provider."""
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .backend import AnnouncementBackend
from .const import DOMAIN


async def async_setup(hass, config):
    hass.data.setdefault(DOMAIN, {})

    def get_backend():
        entries = hass.data[DOMAIN]
        if not entries:
            raise HomeAssistantError("Nest Doorbell Announcements is not configured or loaded")
        return next(iter(entries.values()))

    async def play(call):
        result = await get_backend().play()
        if call.return_response:
            return result
        if not result["ok"]:
            raise HomeAssistantError("Announcement failed: " + result["reason"])
        return None

    async def status(call):
        backend = get_backend()
        return {"provider": "local_http_relay", "busy": backend.lock.locked(),
                "last_result": dict(backend.last_result),
                "audible_playback_verified": False}

    hass.services.async_register(DOMAIN, "play", play, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, "status", status, supports_response=SupportsResponse.ONLY)
    return True


async def async_setup_entry(hass, entry):
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = AnnouncementBackend(
        async_get_clientsession(hass), entry.data["url"], entry.data["timeout"])
    return True


async def async_unload_entry(hass, entry):
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
