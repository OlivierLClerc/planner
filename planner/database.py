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
from typing import Any, Iterator, Mapping, Sequence


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "planner.db"
PBKDF2_ITERATIONS = 200_000
POSTGRES_URL_PREFIXES = ("postgres://", "postgresql://")


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

    @property
    def has_fixed_participant_limit(self) -> bool:
        return self.participant_limit > 0


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


def load_local_env_file(env_path: Path | str = ".env") -> None:
    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def resolve_database_target(
    *,
    secrets: Mapping[str, object] | None = None,
    env_var_name: str = "DATABASE_URL",
) -> Path | str:
    load_local_env_file()

    env_value = os.environ.get(env_var_name, "").strip()
    if env_value:
        return env_value

    if secrets is not None:
        try:
            secret_value = secrets.get(env_var_name, "")
        except Exception:
            secret_value = ""
        if isinstance(secret_value, str) and secret_value.strip():
            return secret_value.strip()

    return DEFAULT_DB_PATH


class PlannerRepository:
    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.database_target = db_path
        self.backend = self._detect_backend(db_path)
        self.db_path = Path(db_path) if self.backend == "sqlite" else None

    def init_db(self) -> None:
        if self.backend == "sqlite" and self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            for statement in self._schema_statements():
                self._execute(connection, statement)
            connection.commit()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        with self._connect() as connection:
            yield connection

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
        if participant_limit < 0:
            raise ValidationError("Le nombre maximum de participants doit etre positif.")

        with self._connect() as connection:
            slug = self._build_unique_slug(connection, title)
            created_at = utc_timestamp()
            event_id = self._insert_and_get_id(
                connection,
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
            connection.commit()

        event = self.get_event_by_id(event_id)
        if event is None:
            raise PlannerError("Impossible de relire le sondage apres sa creation.")
        return event

    def get_event_by_id(
        self,
        event_id: int,
        *,
        connection: Any | None = None,
    ) -> Event | None:
        should_close = connection is None
        if connection is None:
            connection = self._open_connection()

        try:
            row = self._execute(
                connection,
                "SELECT * FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
        finally:
            if should_close:
                connection.close()
        return self._event_from_row(row) if row else None

    def get_event_by_slug(
        self,
        slug: str,
        *,
        connection: Any | None = None,
    ) -> Event | None:
        should_close = connection is None
        if connection is None:
            connection = self._open_connection()

        try:
            row = self._execute(
                connection,
                "SELECT * FROM events WHERE slug = ?",
                (slug,),
            ).fetchone()
        finally:
            if should_close:
                connection.close()
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
            existing_row = self._execute(
                connection,
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
            if event.participant_limit > 0 and participant_count >= event.participant_limit:
                raise ParticipantLimitError(
                    f"Ce sondage a deja atteint la limite de {event.participant_limit} participants."
                )

            created_at = utc_timestamp()
            participant_id = self._insert_and_get_id(
                connection,
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

            availability_rows = [
                (event.id, participant_id, day.isoformat(), 0)
                for day in iterate_dates(event.start_date, event.end_date)
            ]
            self._executemany(
                connection,
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

    def get_participant_by_id(
        self,
        event_id: int,
        participant_id: int,
        *,
        connection: Any | None = None,
    ) -> Participant | None:
        should_close = connection is None
        if connection is None:
            connection = self._open_connection()

        try:
            row = self._execute(
                connection,
                """
                SELECT * FROM participants
                WHERE event_id = ? AND id = ?
                """,
                (event_id, participant_id),
            ).fetchone()
        finally:
            if should_close:
                connection.close()
        return self._participant_from_row(row) if row else None

    def list_participants(
        self,
        event_id: int,
        *,
        connection: Any | None = None,
    ) -> list[Participant]:
        should_close = connection is None
        if connection is None:
            connection = self._open_connection()

        try:
            rows = self._execute(
                connection,
                """
                SELECT * FROM participants
                WHERE event_id = ?
                ORDER BY display_name_normalized ASC
                """,
                (event_id,),
            ).fetchall()
        finally:
            if should_close:
                connection.close()
        return [self._participant_from_row(row) for row in rows]

    def get_participant_count(
        self,
        event_id: int,
        *,
        connection: Any | None = None,
    ) -> int:
        should_close = connection is None
        if connection is None:
            connection = self._open_connection()

        try:
            row = self._execute(
                connection,
                "SELECT COUNT(*) AS total FROM participants WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            return int(self._read_scalar(row, key="total"))
        finally:
            if should_close:
                connection.close()

    def get_participant_availability(
        self,
        event_id: int,
        participant_id: int,
        *,
        connection: Any | None = None,
    ) -> dict[str, int]:
        should_close = connection is None
        if connection is None:
            connection = self._open_connection()

        try:
            rows = self._execute(
                connection,
                """
                SELECT date, status
                FROM availabilities
                WHERE event_id = ? AND participant_id = ?
                ORDER BY date ASC
                """,
                (event_id, participant_id),
            ).fetchall()
        finally:
            if should_close:
                connection.close()
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
            cursor = self._executemany(
                connection,
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

    def get_day_summaries(
        self,
        event: Event,
        *,
        participant_count: int | None = None,
        connection: Any | None = None,
    ) -> list[DaySummary]:
        day_map: dict[str, dict[str, object]] = {
            day.isoformat(): {
                "day": day,
                "available_names": [],
                "maybe_names": [],
            }
            for day in iterate_dates(event.start_date, event.end_date)
        }

        should_close = connection is None
        if connection is None:
            connection = self._open_connection()

        try:
            if participant_count is None:
                participant_count = self.get_participant_count(event.id, connection=connection)
            rows = self._execute(
                connection,
                """
                SELECT a.date, a.status, p.display_name
                FROM availabilities a
                JOIN participants p ON p.id = a.participant_id
                WHERE a.event_id = ? AND a.status IN (1, 2)
                ORDER BY a.date ASC, p.display_name_normalized ASC
                """,
                (event.id,),
            ).fetchall()
        finally:
            if should_close:
                connection.close()

        for row in rows:
            bucket = day_map[row["date"]]
            if int(row["status"]) == 2:
                bucket["available_names"].append(row["display_name"])
            else:
                bucket["maybe_names"].append(row["display_name"])

        summaries: list[DaySummary] = []
        score_capacity = event.participant_limit if event.participant_limit > 0 else max(participant_count, 1)

        for iso_day, values in day_map.items():
            available_names = tuple(values["available_names"])
            maybe_names = tuple(values["maybe_names"])
            score = min(
                (2 * len(available_names) + len(maybe_names))
                / float(2 * score_capacity),
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
    def _connect(self) -> Iterator[Any]:
        connection = self._open_connection()
        try:
            yield connection
        finally:
            connection.close()

    def _open_connection(self) -> Any:
        if self.backend == "sqlite":
            if self.db_path is None:
                raise PlannerError("Chemin SQLite invalide.")
            connection = sqlite3.connect(self.db_path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection

        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:
            raise PlannerError(
                "Le support PostgreSQL demande psycopg. Installez les dependances du projet."
            ) from error

        try:
            return psycopg.connect(
                str(self.database_target),
                row_factory=dict_row,
            )
        except Exception as error:
            raise PlannerError(
                "Impossible de se connecter a PostgreSQL. "
                "Verifiez DATABASE_URL, le mot de passe, et utilisez bien l'URL Supabase "
                "du pooler de session sans les crochets du placeholder."
            ) from error

    def _build_unique_slug(self, connection: Any, title: str) -> str:
        base_slug = slugify(title)
        candidate = base_slug
        suffix = 2

        while self._execute(
            connection,
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
    def _event_from_row(row: Mapping[str, Any]) -> Event:
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
    def _participant_from_row(row: Mapping[str, Any]) -> Participant:
        return Participant(
            id=int(row["id"]),
            event_id=int(row["event_id"]),
            display_name=str(row["display_name"]),
            created_at=str(row["created_at"]),
        )

    @staticmethod
    def _detect_backend(db_path: Path | str) -> str:
        value = str(db_path).strip()
        if value.startswith(POSTGRES_URL_PREFIXES):
            return "postgres"
        return "sqlite"

    def _schema_statements(self) -> tuple[str, ...]:
        event_pk = (
            "BIGSERIAL PRIMARY KEY"
            if self.backend == "postgres"
            else "INTEGER PRIMARY KEY AUTOINCREMENT"
        )
        participant_pk = (
            "BIGSERIAL PRIMARY KEY"
            if self.backend == "postgres"
            else "INTEGER PRIMARY KEY AUTOINCREMENT"
        )
        reference_id_type = "BIGINT" if self.backend == "postgres" else "INTEGER"

        return (
            f"""
            CREATE TABLE IF NOT EXISTS events (
                id {event_pk},
                slug TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                participant_limit INTEGER NOT NULL DEFAULT 10,
                organizer_name TEXT NOT NULL,
                organizer_code_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS participants (
                id {participant_pk},
                event_id {reference_id_type} NOT NULL,
                display_name TEXT NOT NULL,
                display_name_normalized TEXT NOT NULL,
                secret_code_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(event_id, display_name_normalized),
                FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS availabilities (
                event_id {reference_id_type} NOT NULL,
                participant_id {reference_id_type} NOT NULL,
                date TEXT NOT NULL,
                status INTEGER NOT NULL CHECK(status IN (0, 1, 2)),
                PRIMARY KEY(event_id, participant_id, date),
                FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
                FOREIGN KEY(participant_id) REFERENCES participants(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_availabilities_event_date
                ON availabilities (event_id, date)
            """,
        )

    def _sql(self, query: str) -> str:
        if self.backend == "postgres":
            return query.replace("?", "%s")
        return query

    def _execute(
        self,
        connection: Any,
        query: str,
        params: Sequence[object] = (),
    ) -> Any:
        return connection.execute(self._sql(query), params)

    def _executemany(
        self,
        connection: Any,
        query: str,
        params_seq: Sequence[Sequence[object]],
    ) -> Any:
        sql = self._sql(query)
        if self.backend == "postgres":
            cursor = connection.cursor()
            cursor.executemany(sql, params_seq)
            return cursor
        return connection.executemany(sql, params_seq)

    def _insert_and_get_id(
        self,
        connection: Any,
        query: str,
        params: Sequence[object],
    ) -> int:
        if self.backend == "postgres":
            row = self._execute(connection, f"{query.strip()} RETURNING id", params).fetchone()
            return int(self._read_scalar(row, key="id"))

        cursor = self._execute(connection, query, params)
        return int(cursor.lastrowid)

    @staticmethod
    def _read_scalar(row: Any, *, key: str) -> object:
        if isinstance(row, Mapping):
            return row[key]
        return row[0]
