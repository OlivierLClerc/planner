from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import streamlit as st


ASSET_DIR = Path(__file__).resolve().parent / "assets"


@lru_cache(maxsize=1)
def _calendar_renderer():
    if not hasattr(st, "components") or not hasattr(st.components, "v2"):
        raise RuntimeError(
            "Cette application demande une version recente de Streamlit avec st.components.v2."
        )

    html = (ASSET_DIR / "calendar_component.html").read_text(encoding="utf-8")
    css = (ASSET_DIR / "calendar_component.css").read_text(encoding="utf-8")
    js = (ASSET_DIR / "calendar_component.mjs").read_text(encoding="utf-8")
    return st.components.v2.component(
        "availability_calendar_component",
        html=html,
        css=css,
        js=js,
    )


def render_calendar(*, payload: dict[str, object], key: str) -> dict[str, object] | None:
    renderer = _calendar_renderer()
    result = renderer(
        data=payload,
        key=key,
        width="stretch",
        height="content",
        on_save_batch_change=lambda: None,
    )
    return getattr(result, "save_batch", None)
