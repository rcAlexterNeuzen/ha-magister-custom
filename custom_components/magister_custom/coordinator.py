"""Data coordinator for the Magister integration.

Fetches schedule (afspraken), grades (cijfers), and schedule changes
(roosterwijzigingen) for every student linked to the configured account.

Parent accounts:  GET /api/personen/{id}/kinderen  → list of children
Student accounts: fails with Fouttype → use own ID

Appointment fetch window: 1 week behind → 4 weeks ahead.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .auth import MagisterAuthError, MagisterClient, MagisterTOTPRequired
from .const import (
    CONF_PASSWORD,
    CONF_SCHOOL,
    CONF_TOTP_SECRET,
    CONF_USERNAME,
    DOMAIN,
    SCAN_INTERVAL_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

_INFO_TYPES = {0: "les", 1: "huiswerk", 2: "toets", 3: "proeftoets",
               4: "schoolexamen", 5: "mondeling", 6: "info", 7: "afwezig"}


def _info_label(t: Any) -> str:
    try:
        return _INFO_TYPES.get(int(t), str(t))
    except (TypeError, ValueError):
        return str(t)


def _parse_dt(ts: str | None) -> datetime | None:
    """Parse a Magister ISO-8601 timestamp into a timezone-aware datetime."""
    if not ts:
        return None
    try:
        # Truncate sub-second precision beyond 6 digits
        ts_clean = re.sub(r"(\.\d{6})\d+", r"\1", ts).rstrip("Z")
        dt = datetime.fromisoformat(ts_clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _fmt(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


@dataclass
class Appointment:
    """A single calendar appointment / lesson."""

    start: datetime
    end: datetime
    subject: str
    location: str
    description: str
    info_type: int
    is_homework: bool
    is_cancelled: bool  # status == 5

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": _fmt(self.start),
            "end": _fmt(self.end),
            "subject": self.subject,
            "location": self.location,
            "description": self.description,
            "type": _info_label(self.info_type),
            "is_homework": self.is_homework,
            "is_cancelled": self.is_cancelled,
        }


@dataclass
class Grade:
    """A single Magister grade entry."""

    subject: str
    description: str
    value: str
    weight: float | None
    entered_on: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "description": self.description,
            "value": self.value,
            "weight": self.weight,
            "entered_on": _fmt(self.entered_on),
        }


@dataclass
class ScheduleChange:
    """A roosterwijziging (schedule change / cancellation notice)."""

    start: datetime | None
    end: datetime | None
    subject: str
    location: str
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": _fmt(self.start),
            "end": _fmt(self.end),
            "subject": self.subject,
            "location": self.location,
            "description": self.description,
        }


@dataclass
class StudentData:
    """All data for one student."""

    name: str
    student_id: int
    appointments: list[Appointment] = field(default_factory=list)
    grades: list[Grade] = field(default_factory=list)
    schedule_changes: list[ScheduleChange] = field(default_factory=list)

    # Pre-computed convenience fields
    appointments_today: int = 0
    homework_count: int = 0
    next_appointment: Appointment | None = None

    def recompute(self) -> None:
        """Recompute derived fields from raw data."""
        now = datetime.now(tz=timezone.utc)
        today_str = date.today().isoformat()

        self.appointments_today = sum(
            1 for a in self.appointments
            if a.start and a.start.date().isoformat() == today_str and not a.is_cancelled
        )
        self.homework_count = sum(
            1 for a in self.appointments if a.is_homework and not a.is_cancelled
        )
        future = [a for a in self.appointments if a.start and a.start > now and not a.is_cancelled]
        self.next_appointment = min(future, key=lambda a: a.start) if future else None


@dataclass
class MagisterData:
    """Top-level data object returned by the coordinator."""

    students: dict[str, StudentData] = field(default_factory=dict)
    last_update: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class MagisterCoordinator(DataUpdateCoordinator[MagisterData]):
    """Coordinator that fetches Magister data on a regular interval."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data[CONF_SCHOOL]}_{entry.data[CONF_USERNAME]}",
            update_interval=timedelta(minutes=SCAN_INTERVAL_MINUTES),
        )
        self.entry = entry
        self._client = MagisterClient(
            school=entry.data[CONF_SCHOOL],
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
            totp_secret=entry.data.get(CONF_TOTP_SECRET) or None,
        )
        # Dedicated session for authentication (needs its own cookie jar)
        self._auth_session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _get_auth_session(self) -> aiohttp.ClientSession:
        """Return (or create) the dedicated auth session."""
        if self._auth_session is None or self._auth_session.closed:
            self._auth_session = aiohttp.ClientSession()
        return self._auth_session

    async def async_shutdown(self) -> None:
        """Close the auth session on teardown."""
        if self._auth_session and not self._auth_session.closed:
            await self._auth_session.close()
        await super().async_shutdown()

    # ------------------------------------------------------------------
    # DataUpdateCoordinator hook
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> MagisterData:
        """Fetch all data; re-authenticate once if the token has expired."""
        try:
            return await self._fetch_all()
        except MagisterAuthError:
            _LOGGER.debug("Token expired or missing – re-authenticating")
            try:
                await self._client.authenticate(self._get_auth_session())
            except MagisterTOTPRequired as err:
                raise UpdateFailed(
                    "2FA is required: configure a TOTP secret in the integration settings"
                ) from err
            except MagisterAuthError as err:
                raise UpdateFailed(f"Magister authentication failed: {err}") from err
            try:
                return await self._fetch_all()
            except Exception as err:
                raise UpdateFailed(f"Data fetch failed after re-auth: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Network error: {err}") from err

    # ------------------------------------------------------------------
    # Ensure authenticated (called by config_flow for validation)
    # ------------------------------------------------------------------

    async def async_ensure_authenticated(self) -> None:
        """Authenticate if not already done (used by config_flow validation)."""
        if not self._client.is_authenticated():
            await self._client.authenticate(self._get_auth_session())

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    async def _fetch_all(self) -> MagisterData:
        """Return full MagisterData; assumes token is valid."""
        if not self._client.is_authenticated():
            await self._client.authenticate(self._get_auth_session())

        api = async_get_clientsession(self.hass)

        # Get own account info
        account = await self._client.api_get(api, "account")
        own_id: int = account["Persoon"]["Id"]

        # Determine students (parent vs. student account)
        students_raw: list[dict] = []
        try:
            children = await self._client.api_get(api, "personen", own_id, "kinderen")
            if children.get("Fouttype"):
                # Student account – represent oneself as the single "student"
                p = account["Persoon"]
                students_raw = [{
                    "Id": own_id,
                    "Roepnaam": p.get("Roepnaam", ""),
                    "Achternaam": p.get("Achternaam", ""),
                }]
            else:
                students_raw = children.get("Items", [])
        except Exception:
            p = account["Persoon"]
            students_raw = [{
                "Id": own_id,
                "Roepnaam": p.get("Roepnaam", ""),
                "Achternaam": p.get("Achternaam", ""),
            }]

        data = MagisterData()
        for raw in students_raw:
            student = await self._fetch_student(api, raw)
            data.students[student.name] = student

        return data

    async def _fetch_student(
        self, session: aiohttp.ClientSession, raw: dict
    ) -> StudentData:
        """Fetch schedule, grades, and changes for one student."""
        student_id: int = raw["Id"]
        name = f"{raw.get('Roepnaam', '')} {raw.get('Achternaam', '')}".strip() or str(student_id)

        student = StudentData(name=name, student_id=student_id)

        # Date window for schedule: 1 week back → 4 weeks ahead
        today = date.today()
        date_from = (today - timedelta(weeks=1)).isoformat()
        date_to = (today + timedelta(weeks=4)).isoformat()
        schedule_params: dict[str, Any] = {"van": date_from, "tot": date_to}

        # Try to detect lesperiode from aanmeldingen for correct filtering
        try:
            lesperiode = await self._detect_lesperiode(session, student_id, today)
            if lesperiode:
                schedule_params["lesperiode"] = lesperiode
        except Exception as err:
            _LOGGER.debug("Could not detect lesperiode for %s: %s", name, err)

        # Appointments
        try:
            afspraken = await self._client.api_get(
                session, "personen", student_id, "afspraken", params=schedule_params
            )
            student.appointments = _parse_appointments(afspraken.get("Items", []))
        except Exception as err:
            _LOGGER.warning("Could not fetch appointments for %s: %s", name, err)

        # Schedule changes
        try:
            changes = await self._client.api_get(
                session,
                "personen",
                student_id,
                "roosterwijzigingen",
                params=schedule_params,
            )
            student.schedule_changes = _parse_schedule_changes(changes.get("Items", []))
        except Exception as err:
            _LOGGER.debug("Could not fetch schedule changes for %s: %s", name, err)

        # Latest grades (top 50)
        try:
            cijfers = await self._client.api_get(
                session,
                "personen",
                student_id,
                "cijfers",
                "laatste",
                params={"top": 50},
            )
            student.grades = _parse_grades(cijfers.get("items", []))
        except Exception as err:
            _LOGGER.warning("Could not fetch grades for %s: %s", name, err)

        student.recompute()
        return student

    async def _detect_lesperiode(
        self,
        session: aiohttp.ClientSession,
        student_id: int,
        today: date,
    ) -> str | None:
        """Return the school-year term identifier (lesperiode) for today."""
        aanmeldingen = await self._client.api_get(
            session, "personen", student_id, "aanmeldingen"
        )
        for item in aanmeldingen.get("Items", []):
            start_raw = item.get("Start") or item.get("Begin")
            end_raw = item.get("Eind") or item.get("Einde")
            if not start_raw or not end_raw:
                continue
            try:
                start_d = date.fromisoformat(start_raw[:10])
                end_d = date.fromisoformat(end_raw[:10])
            except ValueError:
                continue
            if start_d <= today <= end_d:
                omschrijving = item.get("Omschrijving", item.get("Lesperiode", ""))
                if omschrijving:
                    return omschrijving.split()[0]
        return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_appointments(items: list[dict]) -> list[Appointment]:
    result = []
    for item in items:
        start = _parse_dt(item.get("Start") or item.get("Datum"))
        end = _parse_dt(item.get("Einde") or item.get("Eind"))
        if start is None:
            continue
        if end is None:
            end = start + timedelta(hours=1)
        info_type = int(item.get("InfoType", 0) or 0)
        result.append(Appointment(
            start=start,
            end=end,
            subject=item.get("Vak", item.get("Omschrijving", "")),
            location=item.get("Lokatie", item.get("Lokaal", "")),
            description=item.get("Omschrijving", ""),
            info_type=info_type,
            is_homework=info_type == 1,
            is_cancelled=int(item.get("Status", 0) or 0) == 5,
        ))
    result.sort(key=lambda a: a.start)
    return result


def _parse_grades(items: list[dict]) -> list[Grade]:
    result = []
    for item in items:
        result.append(Grade(
            subject=item.get("vak", {}).get("code", item.get("Vak", {}).get("Code", "")),
            description=item.get("omschrijving", item.get("Omschrijving", "")),
            value=str(item.get("waarde", item.get("Waarde", ""))),
            weight=_safe_float(item.get("weegfactor", item.get("Weegfactor"))),
            entered_on=_parse_dt(item.get("ingevoerdOp", item.get("IngevoerdOp"))),
        ))
    return result


def _parse_schedule_changes(items: list[dict]) -> list[ScheduleChange]:
    result = []
    for item in items:
        result.append(ScheduleChange(
            start=_parse_dt(item.get("Start") or item.get("Datum")),
            end=_parse_dt(item.get("Eind") or item.get("Einde")),
            subject=item.get("Vak", item.get("Omschrijving", "")),
            location=item.get("Lokatie", item.get("Lokaal", "")),
            description=item.get("Omschrijving", ""),
        ))
    return result


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
