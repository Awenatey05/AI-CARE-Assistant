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


def api_post(path: str, body: dict):
    """POST JSON to the API with the API key."""
    response = requests.post(f"{API_URL}{path}", json=body, headers={"X-Api-Key": API_KEY}, timeout=60)
    response.raise_for_status()
    return response


def api_post_form(path: str, fields: dict, files: dict | None = None):
    """POST a form (with files) to the API with the API key."""
    response = requests.post(f"{API_URL}{path}", data=fields, files=files, headers={"X-Api-Key": API_KEY}, timeout=300)
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
    if st.button("Clear chat", width="stretch"):
        st.session_state.messages, st.session_state.conversation = [], None
        st.rerun()
    if st.button("Reset", width="stretch"):
        st.session_state.clear()
        st.rerun()


# 5. DASHBOARD
BANDS = ["High", "Moderate", "Low", "No risk", "none"]


def dashboard_page() -> None:
    st.header("Dashboard")
    try:
        figures = api_get("/dashboard").json()
        alerts = api_get("/alerts").json()
    except requests.exceptions.RequestException as error:
        st.error(f"The dashboard is not available now: {error}")
        return

    by_band = figures["by_band"]["cases_by_band"]
    urgent = [a for a in alerts if a["priority"] == "urgent"]
    review = [a for a in alerts if a["priority"] == "review"]

    # The cards across the top
    cards = st.columns(5)
    cards[0].metric("Cases", figures["by_band"]["total_cases"])
    cards[1].metric("High risk", by_band.get("High", 0))
    cards[2].metric("Open urgent alerts", len(urgent))
    cards[3].metric("Review notices", len(review))
    cards[4].metric("Last Kobo submission", str(figures["last_kobo_submission"] or "none")[:10])

    # Cases by band, and by place
    left, right = st.columns(2)
    with left:
        st.subheader("Cases by band")
        st.bar_chart({("no band" if band == "none" else band): by_band.get(band, 0) for band in BANDS})
    with right:
        place = figures["by_place"]["count_by"]
        st.subheader(f"Cases by {place}")
        st.dataframe([{place.capitalize(): name, "Cases": n}
                      for name, n in figures["by_place"][f"cases_by_{place}"].items()],
                     hide_index=True, width="stretch")

    # Open alerts, urgent first, with a filter and Confirm
    st.subheader(f"Open alerts ({len(alerts)})")
    filters = st.columns(2)
    districts = sorted({a["district"] for a in alerts if a["district"]})
    district = filters[0].selectbox("District", ["All"] + districts)
    priority = filters[1].selectbox("Priority", ["All", "urgent", "review"])
    shown = [a for a in alerts if (district == "All" or a["district"] == district)
             and (priority == "All" or a["priority"] == priority)]
    st.dataframe([{"Reference": a["case_ref"], "Priority": a["priority"], "Level": a["escalation_level"],
                   "District": a["district"], "Band": a["band"] or "no band", "Reasons": ", ".join(a["reasons"]),
                   "Opened": str(a["created_at"])[:16]} for a in shown],
                 hide_index=True, width="stretch", height=300)
    if shown:
        with st.form("confirm"):
            choice = st.selectbox("Alert to confirm", shown,
                                  format_func=lambda a: f"{a['case_ref']} ({a['priority']}, level {a['escalation_level']})")
            name = st.text_input("Confirmed by (name and role)")
            if st.form_submit_button("Confirm"):
                if len(name.strip()) < 2:
                    st.warning("Write who is confirming the alert.")
                else:
                    try:
                        api_post(f"/alerts/{choice['id']}/confirm", {"confirmed_by": name})
                        st.success(f"Alert for {choice['case_ref']} confirmed.")
                        st.rerun()
                    except requests.exceptions.RequestException as error:
                        st.error(f"Could not confirm: {error}")

    # Kobo submissions needing follow-up
    follow_up = figures["kobo_follow_up"]
    st.subheader(f"Kobo submissions needing follow-up ({len(follow_up)})")
    if follow_up:
        st.dataframe([{"Reference": c["case_ref"], "Status": c["status"].replace("_", " "),
                       "District": c["district"], "Community": c["community"]} for c in follow_up],
                     hide_index=True, width="stretch")

    # One case
    st.subheader("Case")
    reference = st.text_input("Case reference", placeholder="NR-TML-GUM-0004-2025")
    if reference:
        show_case_view(reference.strip().upper())


def show_case_view(reference: str) -> None:
    """One case's assessment, and its original as it arrived."""
    try:
        case = api_get(f"/cases/{reference}").json()
    except requests.exceptions.HTTPError:
        st.warning("No case with this reference in your region.")
        return

    cards = st.columns(4)
    cards[0].metric("Band", case["band"] or "no band")
    cards[1].metric("Score", case["score"] if case["score"] is not None else "-")
    cards[2].metric("Status", case["status"].replace("_", " "))
    cards[3].metric("Channel", case["channel"])
    if case["urgent_reasons"]:
        st.error("Urgent: " + ", ".join(case["urgent_reasons"]))
    if case["summary"]:
        st.write(case["summary"])

    st.dataframe([{"Indicator": f"{i['indicator']}{i['subtype'] or ''} {i['name']}", "Found in": i["found_in"],
                   "Quote": i["quote"] or "(from the form answers)"} for i in case["indicators"]],
                 hide_index=True, width="stretch")
    with st.expander("Report (masked)"):
        st.write(case["report_masked"] or "No report text.")
    if case["phone_number_in_report"]:
        st.info("The report contains a phone number: open the original to see it.")
    if case["attachments"]:
        st.info("Files: " + ", ".join(case["attachments"]))

    if st.button("Open the original"):
        try:
            original = api_get(f"/cases/{reference}/original")
        except requests.exceptions.RequestException as error:
            st.error(f"The original is not available: {error}")
            return
        kind = original.headers.get("content-type", "")
        if kind.startswith("application/json"):
            st.json(original.json())
        elif kind.startswith("video"):
            st.video(original.content)
        elif kind.startswith("audio"):
            st.audio(original.content)
        else:
            st.download_button("Download the original", original.content, file_name=reference)
        if "call recording" in case["attachments"]:
            st.audio(api_get(f"/cases/{reference}/original", recording="true").content)


# 6. UPLOADS
CALLERS = ["the child", "a nurse", "teacher", "a community volunteer", "neighbour", "relative", "an anonymous caller"]
DOCUMENTS = {"medical_report": "Medical report", "school_referral_letter": "School referral letter",
             "office_intake_note": "Office intake note", "followup_visit_note": "Follow-up visit note",
             "case_conference_minutes": "Case conference minutes", "volunteer_statement": "Volunteer statement",
             "recorded_statement": "Recorded statement (video)",
             "school_attendance_register": "School attendance register (sheet)",
             "community_committee_log": "Community committee log (sheet)",
             "field_round_compilation": "Field round compilation (sheet)"}


def region_field(key: str) -> str:
    """The team leader's own region; the super administrator chooses one."""
    if st.session_state.region:
        st.text_input("Region", REGIONS[st.session_state.region], disabled=True, key=f"{key}_region_shown")
        return st.session_state.region
    return st.selectbox("Region", list(REGIONS), format_func=REGIONS.get, key=f"{key}_region")


def sent(response, what: str) -> None:
    body = response.json()
    reference = body.get("report_id") or body.get("upload_id")
    st.success(f"{what} received as {reference}. It is being assessed; it will appear on the dashboard shortly.")


def uploads_page() -> None:
    st.header("Uploads")
    call_tab, document_tab = st.tabs(["Helpline report", "Document, sheet or video"])

    with call_tab:
        with st.form("helpline", clear_on_submit=True):
            region = region_field("helpline")
            district = st.text_input("District")
            caller = st.selectbox("Who called", CALLERS)
            report = st.text_area("Report of the call", height=200)
            consent = st.checkbox("The caller agreed to the call being recorded")
            recording = st.file_uploader("Recording (only with the caller's consent)", type=["m4a", "mp3", "wav"])
            if st.form_submit_button("Send report"):
                if not district.strip() or len(report.strip()) < 20:
                    st.warning("Give the district and a report of at least 20 characters.")
                elif recording and not consent:
                    st.warning("A recording can only be sent with the caller's consent.")
                else:
                    files = {"recording": (recording.name, recording.getvalue())} if recording else None
                    try:
                        sent(api_post_form("/helpline", {"region": region, "district": district, "caller_type": caller,
                                                         "report_text": report, "consent_to_record": str(consent).lower()},
                                           files), "Report")
                    except requests.exceptions.HTTPError as error:
                        st.error(f"Not accepted: {error.response.json().get('detail', error)}")
                    except requests.exceptions.RequestException as error:
                        st.error(f"The report could not be sent now: {error}")

    with document_tab:
        with st.form("upload", clear_on_submit=True):
            region = region_field("upload")
            district = st.text_input("District")
            kind = st.selectbox("Type of document", list(DOCUMENTS), format_func=DOCUMENTS.get)
            child = st.text_input("Child's name (not needed for a sheet)")
            upload = st.file_uploader("File", type=["pdf", "docx", "xlsx", "mp4", "mov"])
            if st.form_submit_button("Upload"):
                if not district.strip() or upload is None:
                    st.warning("Give the district and choose a file.")
                else:
                    try:
                        sent(api_post_form("/uploads", {"region": region, "district": district, "document_type": kind,
                                                        "child_name": child},
                                           {"file": (upload.name, upload.getvalue())}), "Upload")
                    except requests.exceptions.HTTPError as error:
                        st.error(f"Not accepted: {error.response.json().get('detail', error)}")
                    except requests.exceptions.RequestException as error:
                        st.error(f"The file could not be sent now: {error}")


# 7. CHAT
def chat_page() -> None:
    st.header("Chat")


# 8. MAIN
{"Dashboard": dashboard_page, "Uploads": uploads_page, "Chat": chat_page}[page]()
