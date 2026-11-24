"""Local announcement endpoint configuration."""
import voluptuous as vol
from homeassistant import config_entries
from .backend import valid_url
from .const import DOMAIN, DEFAULT_URL, DEFAULT_TIMEOUT


class NestAnnouncementsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        errors = {}
        if user_input is not None:
            if not valid_url(user_input["url"]):
                errors["url"] = "invalid_url"
            else:
                return self.async_create_entry(title="Nest Hello announcements", data=user_input)
        return self.async_show_form(
            step_id="user", errors=errors,
            data_schema=vol.Schema({
                vol.Required("url", default=DEFAULT_URL): str,
                vol.Required("timeout", default=DEFAULT_TIMEOUT): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
            }),
        )
