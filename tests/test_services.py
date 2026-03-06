from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from planner.database import (
    ParticipantLimitError,
    PlannerRepository,
    SecretCodeError,
    load_local_env_file,
    resolve_database_target,
)
from planner.services import compute_top_dates, format_long_date_fr
from planner.services import (
    build_calendar_payload,
    extract_event_slug,
    merge_vote_overrides,
    summarize_color_scale_text,
    summarize_participants_text,
    update_pending_votes,
)


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

    def test_unknown_participant_limit_does_not_block_new_participants(self) -> None:
        event = self.repo.create_event(
            title="Dates ouvertes",
            description="Sans limite connue",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            organizer_name="Camille",
            organizer_code="organisateur",
            participant_limit=0,
        )

        for index in range(15):
            self.repo.register_or_login_participant(
                event,
                display_name=f"Libre {index}",
                secret_code=f"secret-{index}",
            )

        self.assertEqual(self.repo.get_participant_count(event.id), 15)

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

    def test_unknown_participant_limit_uses_current_participant_count_for_score(self) -> None:
        event = self.repo.create_event(
            title="Sans limite",
            description="Le score suit les participants presents",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            organizer_name="Camille",
            organizer_code="organisateur",
            participant_limit=0,
        )

        alice = self.repo.register_or_login_participant(
            event,
            display_name="Alice",
            secret_code="alice",
        )
        bob = self.repo.register_or_login_participant(
            event,
            display_name="Bob",
            secret_code="bob",
        )

        self.repo.update_participant_availability(
            event,
            alice.id,
            dates=["2026-07-01"],
            status=2,
        )
        self.repo.update_participant_availability(
            event,
            bob.id,
            dates=["2026-07-01"],
            status=2,
        )

        summaries = self.repo.get_day_summaries(event)
        self.assertAlmostEqual(summaries[0].score, 1.0)

    def test_extract_event_slug_accepts_raw_slug_and_shared_link(self) -> None:
        self.assertEqual(extract_event_slug("reunion-biannuelle"), "reunion-biannuelle")
        self.assertEqual(
            extract_event_slug("/?event=reunion-biannuelle"),
            "reunion-biannuelle",
        )
        self.assertEqual(
            extract_event_slug("https://planner.streamlit.app/?event=reunion-biannuelle"),
            "reunion-biannuelle",
        )
        self.assertEqual(
            extract_event_slug("?event=reunion-biannuelle"),
            "reunion-biannuelle",
        )

    def test_pending_votes_overlay_and_reset_when_matching_saved_value(self) -> None:
        saved_votes = {
            "2026-05-01": 0,
            "2026-05-02": 2,
        }
        pending_votes = update_pending_votes(
            saved_votes=saved_votes,
            pending_votes={},
            dates=["2026-05-01"],
            status=1,
        )

        self.assertEqual(pending_votes, {"2026-05-01": 1})
        self.assertEqual(
            merge_vote_overrides(saved_votes, pending_votes),
            {
                "2026-05-01": 1,
                "2026-05-02": 2,
            },
        )

        reverted_pending_votes = update_pending_votes(
            saved_votes=saved_votes,
            pending_votes=pending_votes,
            dates=["2026-05-01"],
            status=0,
        )
        self.assertEqual(reverted_pending_votes, {})

    def test_participant_and_color_scale_labels(self) -> None:
        self.assertEqual(summarize_participants_text(3, 10), "3 / 10 participants")
        self.assertEqual(summarize_participants_text(3, 0), "3 / inconnu")
        self.assertEqual(
            summarize_color_scale_text(3, 10),
            "Échelle fixée sur 10 participant(s)",
        )
        self.assertEqual(
            summarize_color_scale_text(3, 0),
            "Échelle adaptée au nombre actuel de participants : 3",
        )

    def test_build_calendar_payload_can_hide_group_aggregates(self) -> None:
        alice = self.repo.register_or_login_participant(
            self.event,
            display_name="Alice",
            secret_code="alice",
        )
        self.repo.update_participant_availability(
            self.event,
            alice.id,
            dates=["2026-05-01"],
            status=2,
        )

        summaries = self.repo.get_day_summaries(self.event)
        payload = build_calendar_payload(
            event=self.event,
            participant_count=1,
            theme_type="light",
            current_votes={"2026-05-01": 2},
            summaries=summaries,
            active_status=2,
            read_only=False,
            show_aggregates=False,
        )

        self.assertTrue(payload["maskOtherVotes"])
        self.assertEqual(payload["aggregates"]["2026-05-01"]["availableCount"], 0)
        self.assertEqual(payload["aggregates"]["2026-05-01"]["score"], 0)
        self.assertEqual(payload["aggregates"]["2026-05-01"]["availableNames"], [])


    def test_resolve_database_target_prefers_environment_variable(self) -> None:
        previous_value = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://example"
        try:
            self.assertEqual(resolve_database_target(), "postgresql://example")
        finally:
            if previous_value is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_value

    def test_load_local_env_file_populates_missing_variables_only(self) -> None:
        previous_db_value = os.environ.get("DATABASE_URL")
        previous_project_value = os.environ.get("PROJECT_URL")
        os.environ.pop("DATABASE_URL", None)
        os.environ["PROJECT_URL"] = "https://deja-present.example"

        env_path = Path(self.temp_dir.name) / ".env"
        env_path.write_text(
            "DATABASE_URL=postgresql://from-env-file\n"
            "PROJECT_URL=https://nouvelle-valeur.example\n",
            encoding="utf-8",
        )

        try:
            load_local_env_file(env_path)
            self.assertEqual(os.environ.get("DATABASE_URL"), "postgresql://from-env-file")
            self.assertEqual(os.environ.get("PROJECT_URL"), "https://deja-present.example")
        finally:
            if previous_db_value is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_db_value

            if previous_project_value is None:
                os.environ.pop("PROJECT_URL", None)
            else:
                os.environ["PROJECT_URL"] = previous_project_value


if __name__ == "__main__":
    unittest.main()
