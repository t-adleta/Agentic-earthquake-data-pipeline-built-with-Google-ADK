"""Upload files to cloud object storage (Google Cloud Storage or AWS S3)."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from . import config


def _content_type(path: Path) -> str:
    if path.suffix == ".geojson":
        return "application/geo+json"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def upload_file(local_path: Path, key: str) -> str:
    """Upload one file and return its cloud URI (gs://... or s3://...)."""
    if not config.BUCKET_NAME:
        raise RuntimeError("BUCKET_NAME is not set. Copy .env.example to .env and fill it in.")
    key = f"{config.BUCKET_PREFIX}/{key}" if config.BUCKET_PREFIX else key
    ctype = _content_type(local_path)

    if config.STORAGE_BACKEND == "gcs":
        from google.cloud import storage  # imported here so S3 users don't need GCP auth
        blob = storage.Client().bucket(config.BUCKET_NAME).blob(key)
        blob.upload_from_filename(str(local_path), content_type=ctype)
        return f"gs://{config.BUCKET_NAME}/{key}"

    if config.STORAGE_BACKEND == "s3":
        import boto3
        boto3.client("s3").upload_file(str(local_path), config.BUCKET_NAME, key,
                                       ExtraArgs={"ContentType": ctype})
        return f"s3://{config.BUCKET_NAME}/{key}"

    raise RuntimeError(f"Unknown STORAGE_BACKEND '{config.STORAGE_BACKEND}'. Use 'gcs' or 's3'.")
