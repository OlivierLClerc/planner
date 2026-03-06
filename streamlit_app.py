from __future__ import annotations

import html
from datetime import date, timedelta

import streamlit as st

from planner.calendar_component import render_calendar
from planner.database import (
    DEFAULT_DB_PATH,
    ParticipantLimitError,
    PlannerRepository,
    SecretCodeError,
    ValidationError,
)
from planner.services import (
    STATUS_DESCRIPTIONS,
    STATUS_LABELS,
    build_calendar_payload,
    compute_top_dates,
    format_date_range_fr,
    format_long_date_fr,
    summarize_participants_text,
    total_days,
)


APP_STYLE = """
<style>
  [data-testid="stAppViewContainer"] {
    background:
      radial-gradient(circle at top left, rgba(243, 211, 150, 0.24), transparent 26%),
      radial-gradient(circle at 85% 15%, rgba(110, 182, 143, 0.12), transparent 24%),
      linear-gradient(180deg, #f8f5ef 0%, #f3f6f1 100%);
  }

  [data-testid="stHeader"] {
    background: transparent;
  }

  .hero-panel {
    padding: 1.35rem 1.45rem;
    border: 1px solid rgba(23, 53, 39, 0.08);
    border-radius: 28px;
    background:
      radial-gradient(circle at top left, rgba(255, 224, 169, 0.55), transparent 28%),
      linear-gradient(145deg, rgba(255, 251, 244, 0.96), rgba(239, 247, 241, 0.96));
    box-shadow: 0 20px 34px rgba(23, 53, 39, 0.06);
  }

  .hero-kicker {
    margin-bottom: 0.4rem;
    color: rgba(23, 53, 39, 0.6);
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .hero-title {
    margin: 0;
    color: #173527;
    font-size: 2.15rem;
    line-height: 1.1;
  }

  .hero-subtitle {
    margin: 0.65rem 0 0;
    color: rgba(23, 53, 39, 0.78);
    font-size: 1rem;
    line-height: 1.55;
  }

  .summary-card {
    padding: 1rem 1.05rem;
    border: 1px solid rgba(23, 53, 39, 0.08);
    border-radius: 22px;
    background: rgba(255, 252, 246, 0.9);
  }

  .summary-rank {
    color: rgba(23, 53, 39, 0.56);
    font-size: 0.74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .summary-date {
    margin-top: 0.25rem;
    font-size: 1rem;
    font-weight: 700;
    color: #173527;
  }

  .summary-meta {
    margin-top: 0.45rem;
    color: rgba(23, 53, 39, 0.78);
    font-size: 0.88rem;
    line-height: 1.5;
  }

  .soft-note {
    color: rgba(23, 53, 39, 0.72);
    font-size: 0.94rem;
    line-height: 1.55;
  }
</style>
"""


@st.cache_resource(show_spinner=False)
def get_repository() -> PlannerRepository:
    repo = PlannerRepository(DEFAULT_DB_PATH)
    repo.init_db()
    return repo


def current_event_slug() -> str:
    raw_value = st.query_params.get("event", "")
    if isinstance(raw_value, list):
        raw_value = raw_value[-1] if raw_value else ""
    return str(raw_value).strip()


def set_event_slug(slug: str | None) -> None:
    st.query_params.clear()
    if slug:
        st.query_params["event"] = slug


def auth_store() -> dict[str, int]:
    return st.session_state.setdefault("participant_auth", {})


def get_logged_participant_id(slug: str) -> int | None:
    return auth_store().get(slug)


def set_logged_participant(slug: str, participant_id: int) -> None:
    auth_store()[slug] = participant_id


def logout_participant(slug: str) -> None:
    auth_store().pop(slug, None)


def flash(message: str) -> None:
    st.session_state["flash_message"] = message


def show_flash() -> None:
    message = st.session_state.pop("flash_message", None)
    if message:
        st.success(message)


def render_summary_cards() -> None:
    st.markdown(
        """
        <div class="hero-panel">
          <div class="hero-kicker">Sondage partage</div>
          <h1 class="hero-title">Trouvez nos dates communes.</h1>
          <p class="hero-subtitle">
            Creez un calendrier, partagez le lien, puis laissez chaque ami voter
            jour par jour avec trois niveaux de disponibilite.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_home(repo: PlannerRepository) -> None:
    render_summary_cards()
    st.write("")

    left_column, right_column = st.columns((1.2, 0.8), gap="large")
    today = date.today()

    with left_column:
        st.subheader("Creer un nouveau sondage")
        st.caption("Un seul organisateur cree le sondage. Les participants se connectent ensuite avec un nom et un code secret.")
        with st.form("create_event_form", clear_on_submit=False):
            title = st.text_input("Titre du sondage", placeholder="Week-end en Bretagne")
            description = st.text_area(
                "Description (optionnel)",
                placeholder="Ex: on cherche 4 jours entre mai et juin.",
                height=120,
            )
            organizer_name = st.text_input("Nom de l'organisateur", placeholder="Camille")
            organizer_code = st.text_input(
                "Code organisateur",
                type="password",
                placeholder="Choisissez un code simple a retenir",
            )
            start_col, end_col = st.columns(2)
            with start_col:
                start_date = st.date_input(
                    "Date de debut",
                    value=today + timedelta(days=7),
                    format="DD/MM/YYYY",
                )
            with end_col:
                end_date = st.date_input(
                    "Date de fin",
                    value=today + timedelta(days=37),
                    format="DD/MM/YYYY",
                )

            submitted = st.form_submit_button("Creer le sondage", use_container_width=True)

        if submitted:
            try:
                event = repo.create_event(
                    title=title,
                    description=description,
                    start_date=start_date,
                    end_date=end_date,
                    organizer_name=organizer_name,
                    organizer_code=organizer_code,
                )
            except ValidationError as error:
                st.error(str(error))
            else:
                flash(f"Sondage cree: {event.title}")
                set_event_slug(event.slug)
                st.rerun()

    with right_column:
        st.subheader("Ouvrir un sondage existant")
        with st.form("open_event_form", clear_on_submit=False):
            slug = st.text_input("Code du sondage", placeholder="week-end-en-bretagne")
            go_to_event = st.form_submit_button("Ouvrir", use_container_width=True)

        if go_to_event:
            event = repo.get_event_by_slug(slug.strip())
            if event is None:
                st.error("Aucun sondage ne correspond a ce code.")
            else:
                set_event_slug(event.slug)
                st.rerun()

        st.markdown(
            """
            <div class="summary-card">
              <div class="summary-rank">Comment ca marche</div>
              <div class="summary-meta">
                1. Creez un sondage avec une plage de dates.<br/>
                2. Partagez le lien genere par le slug.<br/>
                3. Chaque ami vote avec 0, 1 ou 2.<br/>
                4. Le calendrier montre les meilleures dates en un coup d'oeil.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def resolve_logged_participant(repo: PlannerRepository, event_slug: str, event_id: int):
    participant_id = get_logged_participant_id(event_slug)
    if participant_id is None:
        return None

    participant = repo.get_participant_by_id(event_id, participant_id)
    if participant is None:
        logout_participant(event_slug)
    return participant


def render_top_dates(summaries) -> None:
    st.subheader("Meilleures dates")
    top_dates = compute_top_dates(summaries, limit=5)
    if not top_dates or all(summary.score == 0 for summary in top_dates):
        st.info("Aucune disponibilite positive pour l'instant.")
        return

    columns = st.columns(min(len(top_dates), 3))
    for index, summary in enumerate(top_dates, start=1):
        column = columns[(index - 1) % len(columns)]
        with column:
            st.markdown(
                f"""
                <div class="summary-card">
                  <div class="summary-rank">Choix {index}</div>
                  <div class="summary-date">{format_long_date_fr(summary.day)}</div>
                  <div class="summary-meta">
                    Disponibles: {summary.available_count}<br/>
                    Peut-etre: {summary.maybe_count}<br/>
                    Score collectif: {round(summary.score * 100)}%
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_event(repo: PlannerRepository, event_slug: str) -> None:
    event = repo.get_event_by_slug(event_slug)
    if event is None:
        st.error("Le sondage demande n'existe pas.")
        if st.button("Retour a l'accueil", use_container_width=True):
            set_event_slug(None)
            st.rerun()
        return

    participant_count = repo.get_participant_count(event.id)
    participants = repo.list_participants(event.id)
    summaries = repo.get_day_summaries(event)
    participant = resolve_logged_participant(repo, event.slug, event.id)

    safe_title = html.escape(event.title)
    safe_description = html.escape(
        event.description
        or "Partagez le lien, puis laissez chacun voter directement dans le calendrier."
    )

    st.markdown(
        f"""
        <div class="hero-panel">
          <div class="hero-kicker">Sondage actif</div>
          <h1 class="hero-title">{safe_title}</h1>
          <p class="hero-subtitle">{safe_description}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    show_flash()

    action_col, share_col = st.columns((0.35, 0.65), gap="large")
    with action_col:
        if st.button("Creer un autre sondage", use_container_width=True):
            set_event_slug(None)
            st.rerun()
    with share_col:
        st.code(f"/?event={event.slug}", language=None)

    metric_col_1, metric_col_2, metric_col_3 = st.columns(3)
    metric_col_1.metric("Periode", format_date_range_fr(event.start_date, event.end_date))
    metric_col_2.metric("Participants", summarize_participants_text(participant_count, event.participant_limit))
    metric_col_3.metric("Jours proposes", str(total_days(event)))

    with st.expander("Participants inscrits", expanded=False):
        if participants:
            st.write(", ".join(participant_item.display_name for participant_item in participants))
        else:
            st.caption("Aucun participant pour le moment.")

    if participant is None:
        st.info(
            "Vous pouvez deja survoler les dates pour voir qui est disponible. "
            "Connectez-vous avec un nom et un code secret pour voter."
        )
        active_status = 2
        current_votes: dict[str, int] = {}
    else:
        info_col, logout_col = st.columns((0.72, 0.28))
        with info_col:
            st.success(f"Connecte en tant que {participant.display_name}")
            active_status = st.radio(
                "Statut a appliquer",
                options=[0, 1, 2],
                format_func=lambda status: STATUS_LABELS[status],
                horizontal=True,
            )
            st.caption(STATUS_DESCRIPTIONS[active_status])
        with logout_col:
            st.write("")
            st.write("")
            if st.button("Changer de participant", use_container_width=True):
                logout_participant(event.slug)
                st.rerun()
        current_votes = repo.get_participant_availability(event.id, participant.id)

    st.markdown(
        '<p class="soft-note">Fond plus intense = plus de disponibilites collectives. '
        'Liseret orange = votre vote "peut-etre", liseret vert = votre vote "disponible".</p>',
        unsafe_allow_html=True,
    )

    payload = build_calendar_payload(
        event=event,
        current_votes=current_votes,
        summaries=summaries,
        active_status=active_status,
        read_only=participant is None,
    )
    vote_batch = render_calendar(
        payload=payload,
        key=f"calendar_{event.slug}_{participant.id if participant else 'public'}",
    )

    if participant is not None and vote_batch:
        selected_dates = vote_batch.get("dates") or []
        status_value = int(vote_batch.get("status", active_status))
        if selected_dates:
            repo.update_participant_availability(
                event,
                participant.id,
                dates=selected_dates,
                status=status_value,
            )
            st.rerun()

    st.write("")
    render_top_dates(summaries)

    if participant is None:
        st.subheader("Voter sur ce sondage")
        st.caption("Si votre nom existe deja, entrez le meme code secret pour retrouver vos votes.")
        with st.form("participant_login_form", clear_on_submit=False):
            display_name = st.text_input("Votre nom", placeholder="Alex")
            secret_code = st.text_input(
                "Votre code secret",
                type="password",
                placeholder="Un code simple pour rouvrir vos votes",
            )
            join = st.form_submit_button("Entrer dans le calendrier", use_container_width=True)

        if join:
            try:
                participant = repo.register_or_login_participant(
                    event,
                    display_name=display_name,
                    secret_code=secret_code,
                )
            except (ValidationError, SecretCodeError, ParticipantLimitError) as error:
                st.error(str(error))
            else:
                set_logged_participant(event.slug, participant.id)
                flash(f"Connexion reussie pour {participant.display_name}")
                st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="Dispo entre amis",
        layout="wide",
    )
    st.markdown(APP_STYLE, unsafe_allow_html=True)

    repo = get_repository()
    event_slug = current_event_slug()

    if event_slug:
        render_event(repo, event_slug)
    else:
        render_home(repo)


if __name__ == "__main__":
    main()
