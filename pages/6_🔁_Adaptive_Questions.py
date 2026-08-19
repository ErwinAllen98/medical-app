"""Layers 9-10 — the second learning cycle: new questions, adaptive difficulty."""

from __future__ import annotations

import streamlit as st

from secondbrain import adaptive, diagnostics
from secondbrain.llm import LLMError
from secondbrain.taxonomy import COGNITIVE_LEVELS
from secondbrain.ui import clear_bridge, empty_state, get_store, llm_bridge, page

page(
    "Adaptive re-questioning",
    "Did you learn the concept, or memorise the answer? New formulations only — boundary cases, "
    "exceptions, look-alikes and clinical application, aimed at the weakest cognitive layer.",
    "🔁",
)

store = get_store()
kus = store.list_kus()
if not kus:
    empty_state("No knowledge units yet.")
    st.stop()

profile = diagnostics.build_profile(store)
plans = {p.ku_id: p for p in store.list_plans("OPEN")}

# Weak units first
ordered = sorted(kus, key=lambda k: (profile.by_id(k.id).priority if profile.by_id(k.id) else 0), reverse=True)
labels = {}
for k in ordered:
    u = profile.by_id(k.id)
    flag = "🔴" if u and u.is_weak else ("✅" if k.status == "MASTERED" else "⚪️")
    labels[k.id] = f"{flag} {k.label}"

ku_id = st.selectbox("Knowledge unit", list(labels), format_func=lambda i: labels[i])
ku = store.get_ku(ku_id)
unit = profile.by_id(ku_id)

c1, c2, c3 = st.columns(3)
c1.metric("Attempts", unit.attempts if unit else 0)
c2.metric("Failure rate", f"{unit.failure_rate:.0%}" if unit else "—")
c3.metric("Existing formulations", len(store.list_cards(ku_id, include_retired=True)))

suggested = adaptive.next_level(unit, plans.get(ku_id)) if unit else 1
st.markdown("#### Adaptive difficulty")
st.caption(
    "The system climbs only when the layer below holds: poor performance falls back to source and "
    "basic recall; strong performance moves on to discrimination, then clinical reasoning."
)
if unit and unit.level_pass_rate:
    cols = st.columns(len(COGNITIVE_LEVELS))
    for i, (lvl, info) in enumerate(COGNITIVE_LEVELS.items()):
        rate = unit.level_pass_rate.get(lvl)
        cols[i].metric(f"L{lvl}", f"{rate:.0%}" if rate is not None else "—", help=info["goal"])

level = st.select_slider(
    "Target cognitive level for the new questions",
    options=list(COGNITIVE_LEVELS),
    value=suggested,
    format_func=lambda l: COGNITIVE_LEVELS[l]["label"],
)
if level == suggested:
    st.caption(f"✔︎ This is the level the diagnosis recommends.")

diag = [d.error_type for d in store.list_diagnoses(ku_id, unresolved_only=True)]
default_errors = diag or ([h["error_type"] for h in unit.error_hypotheses[:2]] if unit else [])
errors = st.multiselect(
    "Weakness to attack", sorted(set(default_errors + list(diag))) or default_errors,
    default=default_errors,
)
n_items = st.slider("How many new items", 2, 8, 4)
language = st.selectbox(
    "Language",
    ["English question, English answer",
     "Persian question, English answer (bilingual)",
     "Persian question, Persian answer"],
)

generation = adaptive.next_generation(store, ku_id)
prompt = adaptive.build_requestion_prompt(store, ku, level, errors, n_items=n_items, language=language)

st.markdown("#### Generate the next cycle")
st.caption(
    f"Generation {generation}. Every question already used is listed inside the prompt as forbidden, "
    "so the system cannot simply re-ask what you memorised."
)
raw = llm_bridge(prompt, key=f"requestion_{ku_id}_{generation}", provider="gemini",
                 label="Write new questions with Gemini")

if raw:
    try:
        cards = adaptive.parse_requestion(raw, ku, generation=generation)
    except LLMError as exc:
        st.error(f"Could not read the response: {exc}")
        cards = []

    if not cards:
        st.warning("No usable item found in the response.")
    else:
        st.success(f"{len(cards)} new items ready.")
        for card in cards:
            angle = next((t.split("::")[1] for t in card.tags if t.startswith("angle::")), "")
            st.markdown(
                f"<div class='sb-card'><span class='sb-tag'>L{card.cognitive_level}</span>"
                f"<span class='sb-tag'>{card.error_target or 'general'}</span>"
                + (f"<span class='sb-tag'>{angle}</span>" if angle else "")
                + f"<br><b>{card.question}</b><br>{card.answer}"
                + (f"<br><span class='sb-muted'>{card.explanation}</span>" if card.explanation else "")
                + "</div>",
                unsafe_allow_html=True,
            )
        if st.button("Add to the Second Brain (then push to Anki)", type="primary"):
            for card in cards:
                store.upsert_card(card)
            store.set_ku_status(ku_id, "CONSOLIDATING")
            store.log_event("requestion", {"ku_id": ku_id, "generation": generation, "cards": len(cards)})
            clear_bridge(f"requestion_{ku_id}_{generation}")
            st.success("Saved. Open the Anki page to transfer them.")
            st.rerun()

with st.expander("Questions already used for this unit"):
    for card in store.list_cards(ku_id, include_retired=True):
        st.markdown(f"- `gen {card.generation}` `L{card.cognitive_level}` {card.question}")
