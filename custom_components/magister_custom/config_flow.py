"""Config flow for the Magister integration."""

from __future__ import annotations

import logging
import re

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .auth import MagisterAuthError, MagisterClient, MagisterTOTPFailed, MagisterTOTPRequired
from .const import CONF_PASSWORD, CONF_SCHOOL, CONF_TOTP_SECRET, CONF_USERNAME, DOMAIN

_LOGGER = logging.getLogger(__name__)

_STEP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCHOOL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_TOTP_SECRET, default=""): str,
    }
)


def _sanitize_school(raw: str) -> str:
    """Normalise user input to a bare Magister subdomain.

    Accepts any of these formats:
      "ovozaanstad"
      "ovo zaanstad"           → "ovozaanstad"  (spaces removed)
      "ovozaanstad.magister.net"
      "https://ovozaanstad.magister.net"
    """
    s = raw.strip().lower()
    # Strip URL scheme
    s = re.sub(r"^https?://", "", s)
    # If the user entered the full hostname, extract the subdomain part
    m = re.match(r"([^./]+)\.magister\.net.*", s)
    if m:
        s = m.group(1)
    # Remove any remaining spaces (e.g. "ovo zaanstad" → "ovozaanstad")
    s = s.replace(" ", "")
    return s


async def _validate(school: str, username: str, password: str, totp_secret: str | None) -> None:
    """Try to authenticate; raise ValueError with a translatable key on failure."""
    client = MagisterClient(
        school=school,
        username=username,
        password=password,
        totp_secret=totp_secret or None,
    )
    try:
        async with aiohttp.ClientSession() as session:
            await client.authenticate(session)
    except MagisterTOTPRequired:
        raise ValueError("totp_required")
    except MagisterTOTPFailed:
        raise ValueError("totp_failed")
    except MagisterAuthError:
        raise ValueError("invalid_auth")
    except (aiohttp.ClientError, OSError):
        raise ValueError("cannot_connect")
    except Exception as err:
        # e.g. aiohttp.InvalidURL (ValueError) on a malformed school name
        _LOGGER.debug("Unexpected error in _validate: %s", err)
        raise ValueError("cannot_connect") from err


class MagisterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Magister."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Initial step: collect credentials and validate them."""
        errors: dict[str, str] = {}

        if user_input is not None:
            school = _sanitize_school(user_input[CONF_SCHOOL])
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD]
            totp_secret = (user_input.get(CONF_TOTP_SECRET) or "").strip() or None

            try:
                await _validate(school, username, password, totp_secret)
            except ValueError as err:
                errors["base"] = str(err)
            except Exception:
                _LOGGER.exception("Unexpected error during Magister validation")
                errors["base"] = "unknown"
            else:
                unique_id = f"{school}_{username}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Magister – {school}",
                    data={
                        CONF_SCHOOL: school,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_TOTP_SECRET: totp_secret,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_STEP_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict | None = None) -> FlowResult:
        """Reauth entry point – redirects to the confirm step."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict | None = None
    ) -> FlowResult:
        """Prompt for new password (and optionally new TOTP secret)."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            new_password = user_input[CONF_PASSWORD]
            totp_secret = (
                user_input.get(CONF_TOTP_SECRET)
                or entry.data.get(CONF_TOTP_SECRET)
                or ""
            ).strip() or None

            try:
                await _validate(
                    entry.data[CONF_SCHOOL],
                    entry.data[CONF_USERNAME],
                    new_password,
                    totp_secret,
                )
            except ValueError as err:
                errors["base"] = str(err)
            except Exception:
                _LOGGER.exception("Unexpected error during Magister reauth")
                errors["base"] = "unknown"
            else:
                new_data = {**entry.data, CONF_PASSWORD: new_password}
                if totp_secret:
                    new_data[CONF_TOTP_SECRET] = totp_secret
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_TOTP_SECRET, default=""): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> MagisterOptionsFlow:
        return MagisterOptionsFlow(config_entry)


class MagisterOptionsFlow(config_entries.OptionsFlow):
    """Options flow: only exposes the poll interval."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "poll_interval",
                        default=self._entry.options.get("poll_interval", 15),
                    ): vol.All(int, vol.Range(min=5, max=1440)),
                }
            ),
        )
