"""Saving and reading originals in the real store (RustFS), in a separate test bucket that is emptied afterwards."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from app.services import storage

DATA = Path(__file__).resolve().parent.parent / "data"
BUCKET = "aicare-test"


@pytest.fixture
def bucket():
    try:
        storage.ensure_bucket(BUCKET)
    except (BotoCoreError, ClientError):
        pytest.skip("The S3 store is not running (docker compose up -d rustfs)")
    yield BUCKET
    s3 = storage.client()
    for item in s3.list_objects_v2(Bucket=BUCKET).get("Contents", []):
        s3.delete_object(Bucket=BUCKET, Key=item["Key"])
    s3.delete_bucket(Bucket=BUCKET)


def test_form_saved_exactly_as_received(bucket):
    form = {"case_uuid": "abc", "child/child_name": "Ama Mensah", "closing/closing_report": "Ɛ ü ç"}
    key = storage.save_json("field/abc.json", form, bucket=bucket)
    assert storage.read_json(key, bucket=bucket) == form


def test_recording_saved_byte_for_byte(bucket):
    recording = DATA / "recordings" / "HL-2025-0055.m4a"
    key = storage.save_file("helpline/HL-2025-0055.m4a", recording, bucket=bucket)
    assert hashlib.sha256(storage.read_bytes(key, bucket=bucket)).hexdigest() == \
        hashlib.sha256(recording.read_bytes()).hexdigest()


def test_exists(bucket):
    assert not storage.exists("uploads/none.pdf", bucket=bucket)
    storage.save_bytes("uploads/x.pdf", b"%PDF", bucket=bucket)
    assert storage.exists("uploads/x.pdf", bucket=bucket)
