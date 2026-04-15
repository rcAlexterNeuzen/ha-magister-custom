"""Calendar platform for Magister.

Creates one CalendarEntity per student showing their lesson schedule.
The coordinator pre-fetches a 5-week window (1 week back, 4 weeks ahead);
async_get_events filters within that window.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import Appointment, MagisterCoordinator, MagisterData, StudentData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: MagisterCoordinator = hass.data[DOMAIN][entry.entry_id]

    data: MagisterData = coordinator.data
    entities = [
        MagisterCalendar(coordinator, student_name)
        for student_name in data.students
    ]
    async_add_entities(entities, update_before_add=False)


def _apt_to_event(apt: Appointment) -> CalendarEvent:
    summary = apt.subject or "Afspraak"
    if apt.is_cancelled:
        summary = f"[UITVAL] {summary}"
    description_parts = [apt.description] if apt.description else []
    if apt.is_homework:
        description_parts.insert(0, "HUISWERK")

    return CalendarEvent(
        start=apt.start,
        end=apt.end,
        summary=summary,
        location=apt.location or None,
        description="\n".join(description_parts) or None,
    )


class MagisterCalendar(CoordinatorEntity[MagisterCoordinator], CalendarEntity):
    """Calendar entity showing a student's Magister schedule."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: MagisterCoordinator, student_name: str) -> None:
        super().__init__(coordinator)
        self._student_name = student_name
        slug = student_name.lower().replace(" ", "_").replace("-", "_")
        self._attr_name = f"Magister {student_name} rooster"
        self._attr_unique_id = f"magister_{coordinator.entry.entry_id}_{slug}_calendar"

    @property
    def _student(self) -> StudentData | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.students.get(self._student_name)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._student is not None

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next event."""
        s = self._student
        if s is None:
            return None
        now = datetime.now(tz=timezone.utc)
        # Current event: an appointment that has started but not yet ended
        for apt in s.appointments:
            if apt.start and apt.end and apt.start <= now <= apt.end and not apt.is_cancelled:
                return _apt_to_event(apt)
        # Next event
        if s.next_appointment:
            return _apt_to_event(s.next_appointment)
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events within the requested date range from coordinator data."""
        s = self._student
        if s is None:
            return []

        events: list[CalendarEvent] = []
        for apt in s.appointments:
            if apt.start is None or apt.end is None:
                continue
            # Include appointment if it overlaps with [start_date, end_date]
            if apt.end >= start_date and apt.start <= end_date:
                events.append(_apt_to_event(apt))

        return events

    @property
    def device_info(self) -> dict[str, Any]:
        slug = self._student_name.lower().replace(" ", "_").replace("-", "_")
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.entry.entry_id}_{slug}")},
            "name": f"Magister – {self._student_name}",
            "manufacturer": "Magister",
            "model": "Schoolinformatie",
        }
