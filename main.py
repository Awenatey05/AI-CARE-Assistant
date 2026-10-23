"""
AI CARE ASSISTANT: THE API (FastAPI)

The front door of the system. Receives Kobo submissions, helpline reports
and uploads, saves the originals and queues the jobs for the worker.

    Kobo / Streamlit -> FastAPI -> storage + Redis queue -> worker.py

Run from the project folder:
    uvicorn main:app --reload
Then open http://localhost:8000/docs to see and try every endpoint.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api import health, kobo, office

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

app = FastAPI(
    title="AI CARE Assistant",
    description="Early warning and case management for child protection organisations.",
    version="0.5",
)
app.include_router(health.router)
app.include_router(kobo.router)
app.include_router(office.router)
