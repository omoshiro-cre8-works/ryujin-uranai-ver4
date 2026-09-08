from __future__ import annotations

import datetime
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud import storage

PDF_ARTIFACT_VERSION = "v1"
PDF_RECOVERY_DAYS = 7


class PdfStorageError(RuntimeError):
    pass


class PdfStorageConfigError(PdfStorageError):
    pass


@dataclass(frozen=True)
class StoredPdf:
    object_path: str
    sha256: str
    generated_at: datetime.datetime
    expires_at: datetime.datetime
    artifact_version: str = PDF_ARTIFACT_VERSION

    def firestore_metadata(self) -> dict[str, Any]:
        return {
            "pdf_status": "ready",
            "pdf_object_path": self.object_path,
            "pdf_generated_at": self.generated_at,
            "pdf_expires_at": self.expires_at,
            "pdf_sha256": self.sha256,
            "pdf_artifact_version": self.artifact_version,
        }


def get_pdf_recovery_bucket_name() -> str | None:
    bucket_name = os.getenv("PDF_RECOVERY_BUCKET", "").strip()
    return bucket_name or None


def is_pdf_recovery_enabled() -> bool:
    return get_pdf_recovery_bucket_name() is not None


def sha256_pdf(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


def normalize_datetime_utc(value: Any) -> datetime.datetime:
    if isinstance(value, str):
        try:
            value = datetime.datetime.fromisoformat(value)
        except ValueError as exc:
            raise PdfStorageConfigError("checkout_completed_at is not a valid datetime") from exc

    if not isinstance(value, datetime.datetime):
        raise PdfStorageConfigError("checkout_completed_at is required for PDF recovery storage")

    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def build_object_path(purchase_id: str, artifact_id: str | None = None) -> str:
    if not purchase_id:
        raise PdfStorageConfigError("purchase_id is required for PDF recovery storage")
    artifact_id = artifact_id or secrets.token_urlsafe(16)
    return f"pdf-recovery/{purchase_id}/{artifact_id}.pdf"


def upload_pdf_for_recovery(
    *,
    purchase_id: str,
    pdf_bytes: bytes,
    checkout_completed_at: Any,
    client: "storage.Client | None" = None,
    bucket_name: str | None = None,
) -> StoredPdf:
    bucket_name = bucket_name or get_pdf_recovery_bucket_name()
    if not bucket_name:
        raise PdfStorageConfigError("PDF_RECOVERY_BUCKET is not configured")

    completed_at = normalize_datetime_utc(checkout_completed_at)
    generated_at = datetime.datetime.now(datetime.timezone.utc)
    expires_at = completed_at + datetime.timedelta(days=PDF_RECOVERY_DAYS)
    object_path = build_object_path(purchase_id)
    digest = sha256_pdf(pdf_bytes)

    if client is None:
        from google.cloud import storage

        storage_client = storage.Client()
    else:
        storage_client = client
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(object_path)
    blob.content_type = "application/pdf"
    blob.custom_time = completed_at
    blob.upload_from_string(
        pdf_bytes,
        content_type="application/pdf",
        if_generation_match=0,
    )

    return StoredPdf(
        object_path=object_path,
        sha256=digest,
        generated_at=generated_at,
        expires_at=expires_at,
    )


def read_pdf_for_recovery(
    object_path: str,
    *,
    client: "storage.Client | None" = None,
    bucket_name: str | None = None,
) -> bytes:
    bucket_name = bucket_name or get_pdf_recovery_bucket_name()
    if not bucket_name:
        raise PdfStorageConfigError("PDF_RECOVERY_BUCKET is not configured")
    if not object_path:
        raise PdfStorageConfigError("pdf_object_path is required")

    if client is None:
        from google.cloud import storage

        storage_client = storage.Client()
    else:
        storage_client = client
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(object_path)
    return blob.download_as_bytes()
