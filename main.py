"""
AI CARE ASSISTANT: THE API (FastAPI)

The front door of the system. Receives Kobo submissions, helpline reports
and uploads, saves the originals and queues the jobs for the worker.
Also lists open alerts and lets staff confirm them (for the dashboard),
and answers chat questions, streamed.

    Kobo / Streamlit -> FastAPI -> storage + Redis queue -> worker.py
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api import alerts, cases, chat, health, kobo, office

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

app = FastAPI(
    title="AI CARE Assistant",
    description="Early warning and case management for child protection organisations.",
    version="0.7",
)
app.include_router(health.router)
app.include_router(kobo.router)
app.include_router(office.router)
app.include_router(alerts.router)
app.include_router(chat.router)
app.include_router(cases.router)
