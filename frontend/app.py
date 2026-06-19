"""Streamlit UI for the Patient Journey Simulator (Phase 6).

A thin client over the FastAPI backend: it holds only UI state (the session id and
the transcript it is drawing) and talks to the API over HTTP. It never imports from
``src/`` (CLAUDE.md) — the backend is the single source of behaviour, so this file
is replaceable without touching the system.

Run with: ``streamlit run frontend/app.py`` (after the API is up on :8000).
"""

from __future__ import annotations

import os

import requests
import streamlit as st

# The API base is env-configurable so the same UI points at local or a deployed
# backend without code changes.
API_BASE = os.environ.get("PATIENT_SIM_API", "http://localhost:8000")

# Presenting complaints map to corpus categories the RAG generator understands.
SCENARIOS = {
    "Chest pain": "chest_pain",
    "Shortness of breath": "dyspnea",
    "Abdominal pain": "abdominal_pain",
    "Headache": "headache",
    "Leg swelling": "leg_swelling",
}

# Who the student is addressing — explicit, the way you turn to someone at the
# bedside. (The backend can classify, but the UI keeps addressing deliberate.)
RECIPIENTS = {"Patient": "patient", "Nurse": "nurse", "Family member": "family"}

# Generation and agent replies hit an LLM, so allow a generous request timeout.
_TIMEOUT = 120

st.set_page_config(page_title="Patient Journey Simulator", page_icon="🩺")


def _init_state() -> None:
    st.session_state.setdefault("session_id", None)
    st.session_state.setdefault("patient_name", None)
    st.session_state.setdefault("scenario_intro", None)
    st.session_state.setdefault("transcript", [])  # [{speaker, content, emotional_state?}]
    st.session_state.setdefault("report", None)  # the evaluation, once requested


def _start_session(scenario_type: str) -> None:
    """Create a session on the backend and reset the local transcript."""
    try:
        resp = requests.post(
            f"{API_BASE}/sessions", json={"scenario_type": scenario_type}, timeout=_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException:
        st.error("Could not start a scenario — is the API running? Please try again.")
        return
    data = resp.json()
    st.session_state.session_id = data["session_id"]
    st.session_state.patient_name = data["patient_name"]
    st.session_state.scenario_intro = data["scenario_intro"]
    st.session_state.transcript = []
    st.session_state.report = None


def _evaluate() -> None:
    """End the interview and fetch the judge's feedback."""
    try:
        resp = requests.post(
            f"{API_BASE}/sessions/{st.session_state.session_id}/evaluate", timeout=_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException:
        st.error("Could not generate feedback. Please try again.")
        return
    st.session_state.report = resp.json()


def _send_turn(content: str, addressed_to: str) -> None:
    """Send the student's message and append the reply, or surface a retry note."""
    st.session_state.transcript.append({"speaker": "student", "content": content})
    with st.chat_message("user"):
        st.write(content)
    try:
        resp = requests.post(
            f"{API_BASE}/sessions/{st.session_state.session_id}/turns",
            json={"content": content, "addressed_to": addressed_to},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException:
        # The backend persisted nothing on failure (D5), so drop the unanswered
        # message locally too and let the student simply ask again.
        st.session_state.transcript.pop()
        st.error("No reply came back. Please try again.")
        return
    data = resp.json()
    st.session_state.transcript.append(
        {
            "speaker": data["speaker"],
            "content": data["content"],
            "emotional_state": data["emotional_state"],
        }
    )
    with st.chat_message("assistant"):
        st.caption(f"{data['speaker'].capitalize()} · {data['emotional_state']}")
        st.write(data["content"])


_init_state()

with st.sidebar:
    st.header("New encounter")
    complaint = st.selectbox("Presenting complaint", list(SCENARIOS))
    if st.button("Start interview", type="primary"):
        _start_session(SCENARIOS[complaint])

    # End + grade the encounter, once one is under way.
    if st.session_state.session_id and st.session_state.transcript:
        st.divider()
        if st.button("End interview & get feedback"):
            _evaluate()

st.title("🩺 Patient Journey Simulator")

if not st.session_state.session_id:
    st.info("Pick a presenting complaint in the sidebar and click **Start interview**.")
    st.stop()

st.subheader(st.session_state.patient_name)
st.caption(st.session_state.scenario_intro)

# Once the interview has been graded, show the feedback above the transcript.
if st.session_state.report:
    report = st.session_state.report
    st.divider()
    st.metric("History-taking score", f"{report['score']:.0%}")
    covered_col, missed_col = st.columns(2)
    covered_col.markdown("**Asked about**")
    covered_col.write("\n".join(f"- {t}" for t in report["covered"]) or "—")
    missed_col.markdown("**Missed**")
    missed_col.write("\n".join(f"- {t}" for t in report["missed"]) or "—")
    st.info(report["clinical_reasoning_notes"])
    with st.expander("Full report"):
        st.text(report["full_report"])
    st.divider()

# Redraw the conversation so far from local state (the source of truth for the UI).
for turn in st.session_state.transcript:
    if turn["speaker"] == "student":
        with st.chat_message("user"):
            st.write(turn["content"])
    else:
        with st.chat_message("assistant"):
            label = turn["speaker"].capitalize()
            if turn.get("emotional_state"):
                label += f" · {turn['emotional_state']}"
            st.caption(label)
            st.write(turn["content"])

# Once graded, the interview is closed — the backend rejects further turns (409),
# so hide the input rather than let the student type into an error.
if st.session_state.report:
    st.success("This interview has ended. Start a new encounter from the sidebar.")
else:
    # "Talking to" renders just above the bottom-pinned input, matching a bedside turn.
    recipient = st.selectbox("Talking to", list(RECIPIENTS))
    if prompt := st.chat_input("Ask a question…"):
        _send_turn(prompt, RECIPIENTS[recipient])
