from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from planner.database import (
    ParticipantLimitError,
    PlannerRepository,
    SecretCodeError,
)
from planner.services import compute_top_dates, format_long_date_fr


class PlannerRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "planner.db"
        self.repo = PlannerRepository(self.db_path)
        self.repo.init_db()
        self.event = self.repo.create_event(
            title="Week-end en Bretagne",
            description="Un test pour les amis.",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 3),
            organizer_name="Camille",
            organizer_code="organisateur",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_event_slug_is_unique(self) -> None:
        second_event = self.repo.create_event(
            title="Week-end en Bretagne",
            description="Suite",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 3),
            organizer_name="Camille",
            organizer_code="organisateur",
        )

        self.assertEqual(self.event.slug, "week-end-en-bretagne")
        self.assertEqual(second_event.slug, "week-end-en-bretagne-2")

    def test_register_participant_initializes_default_votes(self) -> None:
        participant = self.repo.register_or_login_participant(
            self.event,
            display_name="Alex",
            secret_code="secret",
        )
        votes = self.repo.get_participant_availability(self.event.id, participant.id)

        self.assertEqual(votes, {
            "2026-05-01": 0,
            "2026-05-02": 0,
            "2026-05-03": 0,
        })

    def test_existing_participant_requires_matching_secret(self) -> None:
        alex = self.repo.register_or_login_participant(
            self.event,
            display_name="Alex",
            secret_code="secret",
        )
        alex_again = self.repo.register_or_login_participant(
            self.event,
            display_name="alex",
            secret_code="secret",
        )

        self.assertEqual(alex.id, alex_again.id)

        with self.assertRaises(SecretCodeError):
            self.repo.register_or_login_participant(
                self.event,
                display_name="ALEX",
                secret_code="mauvais",
            )

    def test_participant_limit_is_enforced(self) -> None:
        for index in range(10):
            self.repo.register_or_login_participant(
                self.event,
                display_name=f"Participant {index}",
                secret_code=f"code-{index}",
            )

        with self.assertRaises(ParticipantLimitError):
            self.repo.register_or_login_participant(
                self.event,
                display_name="Participant 11",
                secret_code="code-11",
            )

    def test_aggregates_and_top_dates_follow_weighted_sorting(self) -> None:
        alice = self.repo.register_or_login_participant(
            self.event,
            display_name="Alice",
            secret_code="alice",
        )
        bob = self.repo.register_or_login_participant(
            self.event,
            display_name="Bob",
            secret_code="bob",
        )
        clara = self.repo.register_or_login_participant(
            self.event,
            display_name="Clara",
            secret_code="clara",
        )

        self.repo.update_participant_availability(
            self.event,
            alice.id,
            dates=["2026-05-01", "2026-05-02"],
            status=2,
        )
        self.repo.update_participant_availability(
            self.event,
            bob.id,
            dates=["2026-05-01"],
            status=2,
        )
        self.repo.update_participant_availability(
            self.event,
            clara.id,
            dates=["2026-05-02"],
            status=1,
        )

        summaries = self.repo.get_day_summaries(self.event)
        by_day = {summary.day.isoformat(): summary for summary in summaries}

        self.assertEqual(by_day["2026-05-01"].available_count, 2)
        self.assertEqual(by_day["2026-05-01"].maybe_count, 0)
        self.assertAlmostEqual(by_day["2026-05-01"].score, 0.2)
        self.assertEqual(by_day["2026-05-02"].available_count, 1)
        self.assertEqual(by_day["2026-05-02"].maybe_count, 1)

        top_dates = compute_top_dates(summaries, limit=2)
        self.assertEqual([summary.day.isoformat() for summary in top_dates], [
            "2026-05-01",
            "2026-05-02",
        ])

    def test_format_long_date_fr(self) -> None:
        self.assertEqual(format_long_date_fr(date(2026, 5, 1)), "vendredi 1 mai 2026")


if __name__ == "__main__":
    unittest.main()

