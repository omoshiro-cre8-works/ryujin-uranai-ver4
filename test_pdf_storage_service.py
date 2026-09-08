import datetime
import re

import pytest

from services import pdf_storage_service


class FakeBlob:
    def __init__(self):
        self.content_type = None
        self.custom_time = None
        self.uploaded = None
        self.upload_kwargs = None
        self.download_bytes = b"stored-pdf"

    def upload_from_string(self, data, **kwargs):
        self.uploaded = data
        self.upload_kwargs = kwargs

    def download_as_bytes(self):
        return self.download_bytes


class FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, object_path):
        blob = self.blobs.setdefault(object_path, FakeBlob())
        self.last_object_path = object_path
        return blob


class FakeStorageClient:
    def __init__(self):
        self.bucket_ref = FakeBucket()
        self.bucket_name = None

    def bucket(self, bucket_name):
        self.bucket_name = bucket_name
        return self.bucket_ref


def test_upload_pdf_sets_custom_time_hash_non_pii_path_and_precondition(monkeypatch):
    client = FakeStorageClient()
    completed_at = datetime.datetime(2026, 1, 2, 3, 4, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(pdf_storage_service.secrets, "token_urlsafe", lambda size: "random_artifact")

    stored = pdf_storage_service.upload_pdf_for_recovery(
        purchase_id="p_123",
        pdf_bytes=b"pdf-bytes",
        checkout_completed_at=completed_at,
        client=client,
        bucket_name="bucket-test",
    )

    assert client.bucket_name == "bucket-test"
    assert stored.object_path == "pdf-recovery/p_123/random_artifact.pdf"
    assert re.fullmatch(r"pdf-recovery/p_123/[^/]+\.pdf", stored.object_path)
    assert "user" not in stored.object_path.lower()
    assert stored.sha256 == pdf_storage_service.sha256_pdf(b"pdf-bytes")
    assert stored.expires_at == completed_at + datetime.timedelta(days=7)
    blob = client.bucket_ref.blobs[stored.object_path]
    assert blob.uploaded == b"pdf-bytes"
    assert blob.custom_time == completed_at
    assert blob.upload_kwargs["if_generation_match"] == 0
    assert blob.upload_kwargs["content_type"] == "application/pdf"


def test_upload_pdf_requires_checkout_completed_at_when_enabled():
    with pytest.raises(pdf_storage_service.PdfStorageConfigError):
        pdf_storage_service.upload_pdf_for_recovery(
            purchase_id="p_123",
            pdf_bytes=b"pdf",
            checkout_completed_at=None,
            client=FakeStorageClient(),
            bucket_name="bucket-test",
        )


def test_upload_pdf_requires_bucket(monkeypatch):
    monkeypatch.delenv("PDF_RECOVERY_BUCKET", raising=False)

    with pytest.raises(pdf_storage_service.PdfStorageConfigError):
        pdf_storage_service.upload_pdf_for_recovery(
            purchase_id="p_123",
            pdf_bytes=b"pdf",
            checkout_completed_at=datetime.datetime.now(datetime.timezone.utc),
            client=FakeStorageClient(),
        )


def test_read_pdf_uses_configured_private_bucket():
    client = FakeStorageClient()
    bucket = client.bucket("bucket-test")
    bucket.blob("pdf-recovery/p_123/a.pdf").download_bytes = b"stored"

    data = pdf_storage_service.read_pdf_for_recovery(
        "pdf-recovery/p_123/a.pdf",
        client=client,
        bucket_name="bucket-test",
    )

    assert data == b"stored"
