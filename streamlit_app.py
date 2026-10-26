"""
AI CARE ASSISTANT: THE INTERFACE (Streamlit)

Three pages, as in the architecture: the region dashboard, uploads, and the chat.
Everything goes through the API (REST), with the API key; the page never reads
the database or the storage itself.

    browser -> Streamlit -> FastAPI -> Postgres, storage, Redis, the assistant
"""

from __future__ import annotations

import requests
import streamlit as st

from config import API_KEY, API_URL

# 1. PAGE CONFIGURATION
st.set_page_config(page_title="AI CARE Assistant", layout="wide")

REGIONS = {"ahafo": "Ahafo", "ashanti": "Ashanti", "bono": "Bono", "bono_east": "Bono East",
           "central": "Central", "eastern": "Eastern", "greater_accra": "Greater Accra",
           "north_east": "North East", "northern": "Northern", "oti": "Oti", "savannah": "Savannah",
           "upper_east": "Upper East", "upper_west": "Upper West", "volta": "Volta",
           "western": "Western", "western_north": "Western North"}
PAGES = ["Dashboard", "Uploads", "Chat"]


# 2. CALLING THE API
def api_get(path: str, **params):
    """GET from the API with the API key; the user's region is added when there is one."""
    if st.session_state.region:
        params["region"] = st.session_state.region
    response = requests.get(f"{API_URL}{path}", params=params, headers={"X-Api-Key": API_KEY}, timeout=60)
    response.raise_for_status()
    return response


def api_status() -> dict:
    """Which parts of the system are reachable (GET /health)."""
    try:
        return requests.get(f"{API_URL}/health", timeout=5).json()
    except requests.exceptions.RequestException:
        return {}


# 3. SESSION STATE
def initialise_session_state() -> None:
    """Everything the pages remember between clicks."""
    defaults = {"role": "Team leader / regional supervisor", "region": "northern",
                "messages": [], "conversation": None, "pending_approval": None}
    for name, value in defaults.items():
        if name not in st.session_state:
            st.session_state[name] = value


initialise_session_state()


# 4. SIDEBAR
with st.sidebar:
    st.title("AI CARE Assistant")

    st.session_state.role = st.radio("Role", ["Team leader / regional supervisor", "Super administrator"],
                                     index=0 if st.session_state.role.startswith("Team") else 1)
    if st.session_state.role.startswith("Team"):
        names = list(REGIONS)
        st.session_state.region = st.selectbox("Region", names,
                                               index=names.index(st.session_state.region or "northern"),
                                               format_func=REGIONS.get)
    else:
        st.session_state.region = None
        st.caption("All regions")

    page = st.radio("Page", PAGES)
    st.divider()

    status = api_status()
    if not status:
        st.error("The API is not reachable")
    else:
        for part in ("postgres", "redis", "storage", "ollama"):
            reachable = status.get(part)
            (st.success if reachable else st.error)(f"{part.capitalize()}: {'running' if reachable else 'not reachable'}")

    st.divider()
    if st.button("Clear chat", use_container_width=True):
        st.session_state.messages, st.session_state.conversation = [], None
        st.rerun()
    if st.button("Reset", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# 5. DASHBOARD
def dashboard_page() -> None:
    st.header("Dashboard")


# 6. UPLOADS
def uploads_page() -> None:
    st.header("Uploads")


# 7. CHAT
def chat_page() -> None:
    st.header("Chat")


# 8. MAIN
{"Dashboard": dashboard_page, "Uploads": uploads_page, "Chat": chat_page}[page]()
