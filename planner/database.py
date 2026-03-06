from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Sequence


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "planner.db"
PBKDF2_ITERATIONS = 200_000


class PlannerError(Exception):
    """Base error for repository operations."""


class ValidationError(PlannerError):
    """Raised when user input is invalid."""


class SecretCodeError(PlannerError):
    """Raised when a participant secret code is invalid."""


class ParticipantLimitError(PlannerError):
    """Raised when a poll has reached its participant limit."""


@dataclass(frozen=True)
class Event:
    id: int
    slug: str
    title: str
    description: str
    start_date: date
    end_date: date
    participant_limit: int
    organizer_name: str
    created_at: str


@dataclass(frozen=True)
class Participant:
    id: int
    event_id: int
    display_name: str
    created_at: str


@dataclass(frozen=True)
class DaySummary:
    day: date
    available_count: int
    maybe_count: int
    score: float
    available_names: tuple[str, ...]
    maybe_names: tuple[str, ...]


def iterate_dates(start_date: date, end_date: date) -> Iterator[date]:
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def normalize_person_name(raw_value: str) -> str:
    collapsed = " ".join(unicodedata.normalize("NFKC", raw_value).split())
    return collapsed.casefold()


def clean_person_name(raw_value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", raw_value).split())


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug or "sondage"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_secret(secret: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"{PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_secret(secret: str, encoded_secret: str) -> bool:
    try:
        iterations_str, salt_hex, digest_hex = encoded_secret.split("$", maxsplit=2)
        iterations = int(iterations_str)
    except ValueError:
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        bytes.fromhex(salt_hex),
        iterations,
    )
    return hmac.compare_digest(candidate.hex(), digest_hex)


class PlannerRepository:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    participant_limit INTEGER NOT NULL DEFAULT 10,
                    organizer_name TEXT NOT NULL,
                    organizer_code_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS participants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    display_name TEXT NOT NULL,
                    display_name_normalized TEXT NOT NULL,
                    secret_code_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(event_id, display_name_normalized),
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS availabilities (
                    event_id INTEGER NOT NULL,
                    participant_id INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    status INTEGER NOT NULL CHECK(status IN (0, 1, 2)),
                    PRIMARY KEY(event_id, participant_id, date),
                    FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                    FOREIGN KEY(participant_id) REFERENCES participants(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_availabilities_event_date
                    ON availabilities (event_id, date);
                """
            )
            connection.commit()

    def create_event(
        self,
        *,
        title: str,
        description: str,
        start_date: date,
        end_date: date,
        organizer_name: str,
        organizer_code: str,
        participant_limit: int = 10,
    ) -> Event:
        title = title.strip()
        description = description.strip()
        organizer_name = clean_person_name(organizer_name)
        organizer_code = organizer_code.strip()

        if not title:
            raise ValidationError("Le titre du sondage est obligatoire.")
        if not organizer_name:
            raise ValidationError("Le nom de l'organisateur est obligatoire.")
        if not organizer_code:
            raise ValidationError("Le code organisateur est obligatoire.")
        if end_date < start_date:
            raise ValidationError("La date de fin doit etre apres la date de debut.")
        if participant_limit < 1:
            raise ValidationError("Le nombre maximum de participants doit etre positif.")

        with self._connect() as connection:
            slug = self._build_unique_slug(connection, title)
            created_at = utc_timestamp()
            cursor = connection.execute(
                """
                INSERT INTO events (
                    slug,
                    title,
                    description,
                    start_date,
                    end_date,
                    participant_limit,
                    organizer_name,
                    organizer_code_hash,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    slug,
                    title,
                    description,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    participant_limit,
                    organizer_name,
                    hash_secret(organizer_code),
                    created_at,
                ),
            )
            event_id = int(cursor.lastrowid)
            connection.commit()

        event = self.get_event_by_id(event_id)
        if event is None:
            raise PlannerError("Impossible de relire le sondage apres sa creation.")
        return event

    def get_event_by_id(self, event_id: int) -> Event | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
        return self._event_from_row(row) if row else None

    def get_event_by_slug(self, slug: str) -> Event | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE slug = ?",
                (slug,),
            ).fetchone()
        return self._event_from_row(row) if row else None

    def register_or_login_participant(
        self,
        event: Event,
        *,
        display_name: str,
        secret_code: str,
    ) -> Participant:
        display_name = clean_person_name(display_name)
        normalized_name = normalize_person_name(display_name)
        secret_code = secret_code.strip()

        if not display_name:
            raise ValidationError("Le prenom ou pseudo du participant est obligatoire.")
        if not secret_code:
            raise ValidationError("Le code secret du participant est obligatoire.")

        with self._connect() as connection:
            existing_row = connection.execute(
                """
                SELECT * FROM participants
                WHERE event_id = ? AND display_name_normalized = ?
                """,
                (event.id, normalized_name),
            ).fetchone()

            if existing_row is not None:
                if not verify_secret(secret_code, existing_row["secret_code_hash"]):
                    raise SecretCodeError(
                        "Ce nom est deja utilise sur ce sondage et le code secret ne correspond pas."
                    )
                return self._participant_from_row(existing_row)

            participant_count = self.get_participant_count(event.id, connection=connection)
            if participant_count >= event.participant_limit:
                raise ParticipantLimitError(
                    "Ce sondage a deja atteint la limite de 10 participants."
                )

            created_at = utc_timestamp()
            cursor = connection.execute(
                """
                INSERT INTO participants (
                    event_id,
                    display_name,
                    display_name_normalized,
                    secret_code_hash,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    display_name,
                    normalized_name,
                    hash_secret(secret_code),
                    created_at,
                ),
            )
            participant_id = int(cursor.lastrowid)

            availability_rows = [
                (event.id, participant_id, day.isoformat(), 0)
                for day in iterate_dates(event.start_date, event.end_date)
            ]
            connection.executemany(
                """
                INSERT INTO availabilities (event_id, participant_id, date, status)
                VALUES (?, ?, ?, ?)
                """,
                availability_rows,
            )
            connection.commit()

        participant = self.get_participant_by_id(event.id, participant_id)
        if participant is None:
            raise PlannerError("Impossible de relire le participant apres son inscription.")
        return participant

    def get_participant_by_id(self, event_id: int, participant_id: int) -> Participant | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM participants
                WHERE event_id = ? AND id = ?
                """,
                (event_id, participant_id),
            ).fetchone()
        return self._participant_from_row(row) if row else None

    def list_participants(self, event_id: int) -> list[Participant]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM participants
                WHERE event_id = ?
                ORDER BY display_name_normalized ASC
                """,
                (event_id,),
            ).fetchall()
        return [self._participant_from_row(row) for row in rows]

    def get_participant_count(
        self,
        event_id: int,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> int:
        should_close = connection is None
        if connection is None:
            connection = self._open_connection()

        try:
            count = connection.execute(
                "SELECT COUNT(*) FROM participants WHERE event_id = ?",
                (event_id,),
            ).fetchone()[0]
            return int(count)
        finally:
            if should_close:
                connection.close()

    def get_participant_availability(
        self,
        event_id: int,
        participant_id: int,
    ) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT date, status
                FROM availabilities
                WHERE event_id = ? AND participant_id = ?
                ORDER BY date ASC
                """,
                (event_id, participant_id),
            ).fetchall()
        return {row["date"]: int(row["status"]) for row in rows}

    def update_participant_availability(
        self,
        event: Event,
        participant_id: int,
        *,
        dates: Sequence[str | date],
        status: int,
    ) -> int:
        if status not in {0, 1, 2}:
            raise ValidationError("Le statut doit etre 0, 1 ou 2.")

        valid_dates = {
            coerced_day.isoformat()
            for raw_day in dates
            for coerced_day in [self._coerce_date(raw_day)]
            if event.start_date <= coerced_day <= event.end_date
        }
        if not valid_dates:
            return 0

        with self._connect() as connection:
            cursor = connection.executemany(
                """
                UPDATE availabilities
                SET status = ?
                WHERE event_id = ? AND participant_id = ? AND date = ?
                """,
                [
                    (status, event.id, participant_id, iso_day)
                    for iso_day in sorted(valid_dates)
                ],
            )
            connection.commit()
            return cursor.rowcount

    def get_day_summaries(self, event: Event) -> list[DaySummary]:
        day_map: dict[str, dict[str, object]] = {
            day.isoformat(): {
                "day": day,
                "available_names": [],
                "maybe_names": [],
            }
            for day in iterate_dates(event.start_date, event.end_date)
        }

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT a.date, a.status, p.display_name
                FROM availabilities a
                JOIN participants p ON p.id = a.participant_id
                WHERE a.event_id = ? AND a.status IN (1, 2)
                ORDER BY a.date ASC, p.display_name_normalized ASC
                """,
                (event.id,),
            ).fetchall()

        for row in rows:
            bucket = day_map[row["date"]]
            if int(row["status"]) == 2:
                bucket["available_names"].append(row["display_name"])
            else:
                bucket["maybe_names"].append(row["display_name"])

        summaries: list[DaySummary] = []
        for iso_day, values in day_map.items():
            available_names = tuple(values["available_names"])
            maybe_names = tuple(values["maybe_names"])
            score = min(
                (2 * len(available_names) + len(maybe_names))
                / float(2 * event.participant_limit),
                1.0,
            )
            summaries.append(
                DaySummary(
                    day=date.fromisoformat(iso_day),
                    available_count=len(available_names),
                    maybe_count=len(maybe_names),
                    score=score,
                    available_names=available_names,
                    maybe_names=maybe_names,
                )
            )
        return summaries

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = self._open_connection()
        try:
            yield connection
        finally:
            connection.close()

    def _open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _build_unique_slug(self, connection: sqlite3.Connection, title: str) -> str:
        base_slug = slugify(title)
        candidate = base_slug
        suffix = 2

        while connection.execute(
            "SELECT 1 FROM events WHERE slug = ?",
            (candidate,),
        ).fetchone():
            candidate = f"{base_slug}-{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _coerce_date(raw_value: str | date) -> date:
        if isinstance(raw_value, date):
            return raw_value
        return date.fromisoformat(raw_value)

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> Event:
        return Event(
            id=int(row["id"]),
            slug=str(row["slug"]),
            title=str(row["title"]),
            description=str(row["description"]),
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
            participant_limit=int(row["participant_limit"]),
            organizer_name=str(row["organizer_name"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _participant_from_row(row: sqlite3.Row) -> Participant:
        return Participant(
            id=int(row["id"]),
            event_id=int(row["event_id"]),
            display_name=str(row["display_name"]),
            created_at=str(row["created_at"]),
        )

