"""Storage for the untouched originals (S3 interface; RustFS now).

The original is the evidence: the Kobo form exactly as received, the call
report and its recording, the uploaded file. It is saved before anything is
processed and never changed, so any case can be re-assessed from it later.

The app uses the standard S3 interface (boto3), so RustFS can be replaced by
SeaweedFS or a paid store (for example Amazon S3) by changing .env only.

Keys (file names in the store):
    field/<case_uuid>.json
    helpline/<report_id>.json      and helpline/<recording file>
    uploads/<upload_id>/<file>
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from config import STORAGE_ACCESS_KEY, STORAGE_BUCKET, STORAGE_SECRET_KEY, STORAGE_URL

CONTENT_TYPES = {".json": "application/json", ".pdf": "application/pdf",
                 ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 ".m4a": "audio/mp4", ".mp4": "video/mp4"}


# 1. CONNECT
@lru_cache(maxsize=1)
def client():
    """One S3 client for the whole program."""
    return boto3.client(
        "s3", endpoint_url=STORAGE_URL,
        aws_access_key_id=STORAGE_ACCESS_KEY, aws_secret_access_key=STORAGE_SECRET_KEY,
        region_name="us-east-1",                                  # required by boto3; ignored by RustFS
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
    )


def ensure_bucket(bucket: str = STORAGE_BUCKET) -> None:
    """Create the bucket (the top-level folder) if it does not exist yet."""
    try:
        client().head_bucket(Bucket=bucket)
    except ClientError:
        client().create_bucket(Bucket=bucket)


# 2. SAVE
def save_bytes(key: str, data: bytes, bucket: str = STORAGE_BUCKET) -> str:
    """Save an original. Returns its key, which is stored with the case."""
    content_type = CONTENT_TYPES.get(Path(key).suffix.lower(), "application/octet-stream")
    client().put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    return key


def save_json(key: str, record: dict[str, Any], bucket: str = STORAGE_BUCKET) -> str:
    """Save a form or call report exactly as received, as JSON."""
    return save_bytes(key, json.dumps(record, ensure_ascii=False, indent=1).encode("utf-8"), bucket)


def save_file(key: str, path: str | Path, bucket: str = STORAGE_BUCKET) -> str:
    """Save a file (recording, document, sheet) byte for byte."""
    return save_bytes(key, Path(path).read_bytes(), bucket)


# 3. READ
def read_bytes(key: str, bucket: str = STORAGE_BUCKET) -> bytes:
    """The original, exactly as it was saved."""
    return client().get_object(Bucket=bucket, Key=key)["Body"].read()


def read_json(key: str, bucket: str = STORAGE_BUCKET) -> dict[str, Any]:
    return json.loads(read_bytes(key, bucket))


def exists(key: str, bucket: str = STORAGE_BUCKET) -> bool:
    try:
        client().head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


# 4. A TEMPORARY COPY FOR PROCESSING
def download_to(key: str, folder: str | Path, bucket: str = STORAGE_BUCKET) -> Path:
    """Copy an original into a folder (for Whisper or a document reader) and return its path.
    The original in storage is untouched; the caller deletes the folder afterwards."""
    path = Path(folder) / Path(key).name
    path.write_bytes(read_bytes(key, bucket))
    return path
