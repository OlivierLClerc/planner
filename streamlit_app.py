from __future__ import annotations

import html
from datetime import date, timedelta

import streamlit as st

from planner.calendar_component import render_calendar
from planner.database import (
    DEFAULT_DB_PATH,
    ParticipantLimitError,
    PlannerError,
    PlannerRepository,
    SecretCodeError,
    ValidationError,
    resolve_database_target,
)
from planner.services import (
    STATUS_DESCRIPTIONS,
    STATUS_LABELS,
    build_calendar_payload,
    compute_top_dates,
    extract_event_slug,
    format_date_range_fr,
    format_long_date_fr,
    merge_vote_overrides,
    summarize_color_scale_text,
    summarize_participants_text,
    total_days,
    update_pending_votes,
)


def current_theme_type() -> str:
    theme = getattr(st.context, "theme", None)
    theme_type = getattr(theme, "type", None)
    return "dark" if theme_type == "dark" else "light"


def build_app_style(theme_type: str) -> str:
    is_dark = theme_type == "dark"
    palette = {
        "app_background": (
            "radial-gradient(circle at top left, rgba(238, 137, 89, 0.14), transparent 26%),"
            "radial-gradient(circle at 85% 15%, rgba(76, 154, 119, 0.14), transparent 24%),"
            "linear-gradient(180deg, #0f1512 0%, #151d18 100%)"
            if is_dark
            else "radial-gradient(circle at top left, rgba(216, 224, 228, 0.34), transparent 28%),"
            "radial-gradient(circle at 85% 15%, rgba(145, 177, 162, 0.14), transparent 24%),"
            "linear-gradient(180deg, #f5f7f8 0%, #eef3f1 100%)"
        ),
        "panel_border": "rgba(222, 232, 225, 0.10)" if is_dark else "rgba(23, 53, 39, 0.08)",
        "panel_background": (
            "radial-gradient(circle at top left, rgba(236, 143, 86, 0.16), transparent 28%),"
            "linear-gradient(145deg, rgba(24, 31, 27, 0.96), rgba(18, 25, 21, 0.96))"
            if is_dark
            else "radial-gradient(circle at top left, rgba(221, 229, 225, 0.72), transparent 30%),"
            "linear-gradient(145deg, rgba(250, 251, 252, 0.96), rgba(241, 245, 243, 0.96))"
        ),
        "panel_shadow": "0 20px 34px rgba(0, 0, 0, 0.24)" if is_dark else "0 20px 34px rgba(23, 53, 39, 0.06)",
        "kicker": "rgba(224, 234, 227, 0.68)" if is_dark else "rgba(23, 53, 39, 0.6)",
        "title": "#f3efe8" if is_dark else "#173527",
        "text": "rgba(233, 240, 235, 0.84)" if is_dark else "rgba(23, 53, 39, 0.78)",
        "summary_background": "rgba(25, 34, 28, 0.92)" if is_dark else "rgba(255, 252, 246, 0.9)",
        "summary_rank": "rgba(224, 234, 227, 0.62)" if is_dark else "rgba(23, 53, 39, 0.56)",
        "note": "rgba(231, 239, 233, 0.76)" if is_dark else "rgba(23, 53, 39, 0.72)",
    }

    return f"""
<style>
  [data-testid="stAppViewContainer"] {{
    background: {palette["app_background"]};
  }}

  [data-testid="stHeader"] {{
    background: transparent;
  }}

  .hero-panel {{
    padding: 1.35rem 1.45rem;
    border: 1px solid {palette["panel_border"]};
    border-radius: 28px;
    background: {palette["panel_background"]};
    box-shadow: {palette["panel_shadow"]};
  }}

  .hero-kicker {{
    margin-bottom: 0.4rem;
    color: {palette["kicker"]};
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}

  .hero-title {{
    margin: 0;
    color: {palette["title"]};
    font-size: 2.15rem;
    line-height: 1.1;
  }}

  .hero-subtitle {{
    margin: 0.65rem 0 0;
    color: {palette["text"]};
    font-size: 1rem;
    line-height: 1.55;
  }}

  .summary-card {{
    padding: 1rem 1.05rem;
    border: 1px solid {palette["panel_border"]};
    border-radius: 22px;
    background: {palette["summary_background"]};
  }}

  .summary-rank {{
    color: {palette["summary_rank"]};
    font-size: 0.74rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}

  .summary-date {{
    margin-top: 0.25rem;
    font-size: 1rem;
    font-weight: 700;
    color: {palette["title"]};
  }}

  .summary-meta {{
    margin-top: 0.45rem;
    color: {palette["text"]};
    font-size: 0.88rem;
    line-height: 1.5;
  }}

  .soft-note {{
    color: {palette["note"]};
    font-size: 0.94rem;
    line-height: 1.55;
  }}
</style>
"""


@st.cache_resource(show_spinner=False)
def get_repository() -> PlannerRepository:
    try:
        database_target = resolve_database_target(secrets=st.secrets)
    except Exception:
        database_target = DEFAULT_DB_PATH
    repo = PlannerRepository(database_target)
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


def pending_vote_store() -> dict[str, dict[str, int]]:
    return st.session_state.setdefault("pending_votes", {})


def pending_vote_key(event_slug: str, participant_id: int) -> str:
    return f"{event_slug}:{participant_id}"


def get_pending_votes(event_slug: str, participant_id: int) -> dict[str, int]:
    key = pending_vote_key(event_slug, participant_id)
    store = pending_vote_store()
    return store.setdefault(key, {})


def clear_pending_votes(event_slug: str, participant_id: int) -> None:
    pending_vote_store().pop(pending_vote_key(event_slug, participant_id), None)


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
          <div class="hero-kicker">Sondage partagé</div>
          <h1 class="hero-title">Trouvons nos dates communes.</h1>
          <p class="hero-subtitle">
            Créez un calendrier, partagez le lien, puis laissez chaque ami voter
            jour par jour avec trois niveaux de disponibilité.
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
        st.subheader("Créer un nouveau sondage")
        st.caption("Un seul organisateur crée le sondage. Les participants se connectent ensuite avec un nom et un code secret.")
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
                placeholder="Choisissez un code simple à retenir",
            )
            start_col, end_col = st.columns(2)
            with start_col:
                start_date = st.date_input(
                    "Date de début",
                    value=today + timedelta(days=7),
                    format="DD/MM/YYYY",
                )
            with end_col:
                end_date = st.date_input(
                    "Date de fin",
                    value=today + timedelta(days=37),
                    format="DD/MM/YYYY",
                )
            participant_mode = st.radio(
                "Nombre de participants attendu",
                options=["Fixe", "Inconnu"],
                horizontal=True,
            )
            if participant_mode == "Fixe":
                participant_limit = int(
                    st.number_input(
                        "Nombre maximum de participants",
                        min_value=1,
                        max_value=200,
                        value=10,
                        step=1,
                    )
                )
            else:
                participant_limit = 0
                st.caption(
                    "Le nombre de participants reste ouvert. "
                    "L'intensité des couleurs s'adaptera au nombre actuel de participants."
                )

            submitted = st.form_submit_button("Créer le sondage", use_container_width=True)

        if submitted:
            try:
                event = repo.create_event(
                    title=title,
                    description=description,
                    start_date=start_date,
                    end_date=end_date,
                    organizer_name=organizer_name,
                    organizer_code=organizer_code,
                    participant_limit=participant_limit,
                )
                organizer_participant = repo.register_or_login_participant(
                    event,
                    display_name=organizer_name,
                    secret_code=organizer_code,
                )
            except ValidationError as error:
                st.error(str(error))
            else:
                set_logged_participant(event.slug, organizer_participant.id)
                flash(f"Sondage créé : {event.title}")
                set_event_slug(event.slug)
                st.rerun()

    with right_column:
        st.subheader("Ouvrir un sondage existant")
        st.caption("Collez le lien partage complet ou seulement le code du sondage.")
        with st.form("open_event_form", clear_on_submit=False):
            slug_input = st.text_input(
                "Code du sondage",
                placeholder="reunion-biannuelle ou /?event=reunion-biannuelle",
            )
            go_to_event = st.form_submit_button("Ouvrir", use_container_width=True)

        if go_to_event:
            slug = extract_event_slug(slug_input)
            event = repo.get_event_by_slug(slug)
            if event is None:
                st.error("Aucun sondage ne correspond a ce code.")
            else:
                set_event_slug(event.slug)
                st.rerun()

        st.markdown(
            """
            <div class="summary-card">
              <div class="summary-rank">Comment ça marche</div>
              <div class="summary-meta">
                1. Créez un sondage avec une plage de dates.<br/>
                2. Partagez le lien avec les participants.<br/>
                3. Chaque ami vote avec 0, 1 ou 2, puis vous repérez vite les meilleures dates.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def resolve_logged_participant(
    repo: PlannerRepository,
    event_slug: str,
    event_id: int,
    *,
    connection=None,
):
    participant_id = get_logged_participant_id(event_slug)
    if participant_id is None:
        return None

    participant = repo.get_participant_by_id(event_id, participant_id, connection=connection)
    if participant is None:
        logout_participant(event_slug)
    return participant


def render_top_dates(summaries) -> None:
    st.subheader("Meilleures dates")
    top_dates = compute_top_dates(summaries, limit=5)
    if not top_dates or all(summary.score == 0 for summary in top_dates):
        st.info("Aucune disponibilité positive pour l'instant.")
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
                    Peut-être: {summary.maybe_count}<br/>
                    Score collectif: {round(summary.score * 100)}%
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_event(repo: PlannerRepository, event_slug: str) -> None:
    with repo.connect() as connection:
        event = repo.get_event_by_slug(event_slug, connection=connection)
        if event is None:
            st.error("Le sondage demande n'existe pas.")
            if st.button("Retour a l'accueil", use_container_width=True):
                set_event_slug(None)
                st.rerun()
            return

        participant_count = repo.get_participant_count(event.id, connection=connection)
        participants = repo.list_participants(event.id, connection=connection)
        summaries = repo.get_day_summaries(
            event,
            participant_count=participant_count,
            connection=connection,
        )
        participant = resolve_logged_participant(
            repo,
            event.slug,
            event.id,
            connection=connection,
        )
        saved_votes = (
            repo.get_participant_availability(event.id, participant.id, connection=connection)
            if participant is not None
            else {}
        )

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
        if st.button("Créer un autre sondage", use_container_width=True):
            set_event_slug(None)
            st.rerun()
    with share_col:
        st.code(f"/?event={event.slug}", language=None)
        st.caption(f"Vous pouvez aussi saisir simplement ce code : {event.slug}")

    metric_col_1, metric_col_2, metric_col_3 = st.columns(3)
    metric_col_1.metric("Période", format_date_range_fr(event.start_date, event.end_date))
    metric_col_2.metric("Participants", summarize_participants_text(participant_count, event.participant_limit))
    metric_col_3.metric("Jours proposés", str(total_days(event)))
    st.caption(summarize_color_scale_text(participant_count, event.participant_limit))

    if participant is None:
        st.subheader("Rejoindre ce sondage")
        st.caption(
            "Entrez votre nom et votre code secret avant d'ouvrir le calendrier. "
            "Si votre nom existe déjà, utilisez le même code secret pour retrouver vos votes."
        )
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
                flash(f"Connexion réussie pour {participant.display_name}")
                st.rerun()

        st.info(
            "Le calendrier apparaîtra après la connexion."
        )
        return
    else:
        with st.expander("Participants inscrits", expanded=False):
            if participants:
                st.write(", ".join(participant_item.display_name for participant_item in participants))
            else:
                st.caption("Aucun participant pour le moment.")

        info_col, logout_col = st.columns((0.72, 0.28))
        with info_col:
            st.success(f"Connecté en tant que {participant.display_name}")
            active_status = st.radio(
                "Statut à appliquer",
                options=[0, 1, 2],
                format_func=lambda status: STATUS_LABELS[status],
                horizontal=True,
            )
            st.caption(STATUS_DESCRIPTIONS[active_status])
            st.caption("Cliquez sur une date ou glissez sur plusieurs jours, puis sauvegardez.")
        with logout_col:
            st.write("")
            st.write("")
            if st.button("Changer de participant", use_container_width=True):
                clear_pending_votes(event.slug, participant.id)
                logout_participant(event.slug)
                st.rerun()
        pending_votes = get_pending_votes(event.slug, participant.id)
        current_votes = merge_vote_overrides(saved_votes, pending_votes)

    st.markdown(
        '<p class="soft-note">Fond rouge = peu de disponibilités, fond vert = beaucoup de disponibilités. '
        'Les modifications restent en brouillon jusqu’au bouton "Sauvegarder les choix".</p>',
        unsafe_allow_html=True,
    )

    payload = build_calendar_payload(
        event=event,
        participant_count=participant_count,
        theme_type=current_theme_type(),
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
            next_pending_votes = update_pending_votes(
                saved_votes=saved_votes,
                pending_votes=pending_votes,
                dates=selected_dates,
                status=status_value,
            )
            pending_vote_store()[pending_vote_key(event.slug, participant.id)] = next_pending_votes
            st.rerun()

    if participant is not None:
        draft_count = len(pending_votes)
        if draft_count:
            st.warning(
                f"{draft_count} jour(s) modifié(s) en attente. "
                "Les couleurs collectives seront mises à jour après sauvegarde."
            )
        else:
            st.caption("Aucune modification en attente.")

        if st.button(
            "Sauvegarder les choix",
            use_container_width=True,
            disabled=draft_count == 0,
        ):
            grouped_dates: dict[int, list[str]] = {}
            for iso_day, status_value in pending_votes.items():
                grouped_dates.setdefault(int(status_value), []).append(iso_day)

            for status_value, iso_days in grouped_dates.items():
                repo.update_participant_availability(
                    event,
                    participant.id,
                    dates=iso_days,
                    status=status_value,
                )

            clear_pending_votes(event.slug, participant.id)
            flash("Choix sauvegardés.")
            st.rerun()

    st.write("")
    render_top_dates(summaries)


def main() -> None:
    st.set_page_config(
        page_title="Dispo entre amis",
        layout="wide",
    )
    st.markdown(build_app_style(current_theme_type()), unsafe_allow_html=True)

    try:
        repo = get_repository()
    except PlannerError as error:
        st.error(str(error))
        st.info(
            "Si vous etes sur Streamlit Cloud, ajoutez DATABASE_URL dans les secrets de l'application. "
            "En local, utilisez .env."
        )
        st.stop()
    event_slug = current_event_slug()

    if event_slug:
        render_event(repo, event_slug)
    else:
        render_home(repo)


if __name__ == "__main__":
    main()
