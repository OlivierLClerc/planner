from __future__ import annotations

from datetime import date
from typing import Iterable, Mapping
from urllib.parse import parse_qs, urlparse

from planner.database import DaySummary, Event


FRENCH_WEEKDAYS = [
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
]

FRENCH_MONTHS = [
    "janvier",
    "fevrier",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "septembre",
    "octobre",
    "novembre",
    "decembre",
]

STATUS_LABELS = {
    0: "Indisponible",
    1: "Peut-etre",
    2: "Disponible",
}

STATUS_DESCRIPTIONS = {
    0: "Je ne peux pas venir",
    1: "Je peux peut-etre, il faut poser un jour",
    2: "Je suis disponible",
}


def format_long_date_fr(value: date) -> str:
    weekday = FRENCH_WEEKDAYS[value.weekday()]
    month = FRENCH_MONTHS[value.month - 1]
    return f"{weekday} {value.day} {month} {value.year}"


def format_short_date_fr(value: date) -> str:
    month = FRENCH_MONTHS[value.month - 1]
    return f"{value.day} {month} {value.year}"


def format_date_range_fr(start_date: date, end_date: date) -> str:
    return f"Du {format_short_date_fr(start_date)} au {format_short_date_fr(end_date)}"


def extract_event_slug(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""

    parse_candidates = [value]
    if value.startswith("?"):
        parse_candidates.append(f"https://placeholder.local/{value}")
    elif value.startswith("/"):
        parse_candidates.append(f"https://placeholder.local{value}")
    elif "://" not in value and "=" in value:
        parse_candidates.append(f"https://placeholder.local/?{value}")

    for candidate in parse_candidates:
        parsed = urlparse(candidate)
        event_values = parse_qs(parsed.query).get("event")
        if event_values:
            return event_values[-1].strip().strip("/")

    parsed = urlparse(value)
    path_value = parsed.path or value
    return path_value.strip().strip("/")


def merge_vote_overrides(
    saved_votes: Mapping[str, int],
    pending_votes: Mapping[str, int],
) -> dict[str, int]:
    merged = dict(saved_votes)
    merged.update({iso_day: int(status) for iso_day, status in pending_votes.items()})
    return merged


def update_pending_votes(
    *,
    saved_votes: Mapping[str, int],
    pending_votes: Mapping[str, int],
    dates: Iterable[str],
    status: int,
) -> dict[str, int]:
    updated_votes = dict(pending_votes)
    for iso_day in dates:
        if int(saved_votes.get(iso_day, 0)) == int(status):
            updated_votes.pop(iso_day, None)
        else:
            updated_votes[iso_day] = int(status)
    return updated_votes


def build_calendar_payload(
    *,
    event: Event,
    participant_count: int,
    current_votes: dict[str, int],
    summaries: Iterable[DaySummary],
    active_status: int,
    read_only: bool,
) -> dict[str, object]:
    aggregates: dict[str, dict[str, object]] = {}
    for summary in summaries:
        iso_day = summary.day.isoformat()
        aggregates[iso_day] = {
            "date": iso_day,
            "availableCount": summary.available_count,
            "maybeCount": summary.maybe_count,
            "score": summary.score,
            "availableNames": list(summary.available_names),
            "maybeNames": list(summary.maybe_names),
        }

    return {
        "startDate": event.start_date.isoformat(),
        "endDate": event.end_date.isoformat(),
        "locale": "fr-FR",
        "participantLimit": event.participant_limit,
        "effectiveParticipantLimit": (
            event.participant_limit if event.participant_limit > 0 else max(participant_count, 1)
        ),
        "activeStatus": active_status,
        "activeStatusLabel": STATUS_LABELS[active_status],
        "currentVotes": current_votes,
        "aggregates": aggregates,
        "readOnly": read_only,
    }


def compute_top_dates(
    summaries: Iterable[DaySummary],
    *,
    limit: int = 5,
) -> list[DaySummary]:
    return sorted(
        summaries,
        key=lambda summary: (
            -summary.score,
            -summary.available_count,
            summary.day,
        ),
    )[:limit]


def summarize_participants_text(participant_count: int, participant_limit: int) -> str:
    if participant_limit <= 0:
        return f"{participant_count} / inconnu"
    return f"{participant_count} / {participant_limit} participants"


def summarize_color_scale_text(participant_count: int, participant_limit: int) -> str:
    if participant_limit > 0:
        return f"Echelle fixee sur {participant_limit} participant(s)"
    effective_limit = max(participant_count, 1)
    return f"Echelle adaptee au nombre actuel de participants: {effective_limit}"


def total_days(event: Event) -> int:
    return (event.end_date - event.start_date).days + 1
