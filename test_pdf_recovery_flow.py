import datetime
from types import SimpleNamespace

import pytest

import app


class AttrDict(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class StopCalled(RuntimeError):
    pass


def make_streamlit_stub(access_token="token"):
    calls = []
    return SimpleNamespace(
        calls=calls,
        session_state=AttrDict(active_access_token=access_token),
        query_params={"purchase_id": "p_123", "access_token": access_token},
        success=lambda value, **kwargs: calls.append(("success", value)),
        warning=lambda value, **kwargs: calls.append(("warning", value)),
        error=lambda value, **kwargs: calls.append(("error", value)),
        download_button=lambda **kwargs: calls.append(("download", kwargs)),
        markdown=lambda *args, **kwargs: calls.append(("markdown", args, kwargs)),
        columns=lambda spec: [SimpleNamespace(__enter__=lambda self: self, __exit__=lambda *args: None) for _ in range(len(spec))],
        stop=lambda: (_ for _ in ()).throw(StopCalled()),
    )


def make_recovery_purchase(**updates):
    record = {
        "purchase_id": "p_123",
        "payment_status": "paid",
        "used_flag": True,
        "generation_processing": False,
        "access_token_hash": app.hashlib.sha256(b"token").hexdigest(),
        "pdf_status": "ready",
        "pdf_object_path": "pdf-recovery/p_123/artifact.pdf",
        "pdf_expires_at": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
        "pdf_sha256": app.sha256_pdf(b"pdf-bytes"),
    }
    record.update(updates)
    return record


def stub_recovery_render_helpers(monkeypatch):
    monkeypatch.setattr(app, "scroll_completion_screen_to_top", lambda: None)
    monkeypatch.setattr(app, "render_form_gap", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "render_header", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "render_completion_screen", lambda *args, **kwargs: None)


def test_prepare_pdf_recovery_metadata_is_disabled_when_env_missing(monkeypatch):
    monkeypatch.delenv("PDF_RECOVERY_BUCKET", raising=False)
    monkeypatch.setattr(
        app,
        "upload_pdf_for_recovery",
        lambda **kwargs: pytest.fail("upload should not run when env is missing"),
    )

    assert app.prepare_pdf_recovery_metadata("p_123", b"pdf", SimpleNamespace(info=lambda *args, **kwargs: None)) is None


def test_regular_generation_uploads_before_consuming_when_recovery_enabled(monkeypatch):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")
    monkeypatch.setattr(app, "claim_purchase_generation", lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED)
    monkeypatch.setattr(app, "release_purchase_generation_claim", lambda purchase_id, logger: calls.append("release"))
    monkeypatch.setattr(app, "call_gemini_fortune", lambda value: calls.append("gemini") or {"miko_intro": "result"})
    monkeypatch.setattr(app, "generate_miko_letter_pdf", lambda user_name, value: calls.append("pdf") or b"pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append("upload") or {"pdf_status": "ready"})
    monkeypatch.setattr(app, "consume_purchase", lambda purchase_id, logger, pdf_metadata=None: calls.append(("consume", pdf_metadata)) or True)

    completed = app.generate_regular_fortune_pdf_and_consume(payload, "p_123", SimpleNamespace())

    assert completed == ({"miko_intro": "result"}, b"pdf")
    assert calls == ["claim", "gemini", "pdf", "upload", ("consume", {"pdf_status": "ready"})]


def test_regular_generation_releases_claim_and_does_not_consume_when_upload_fails(monkeypatch):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")
    monkeypatch.setattr(app, "claim_purchase_generation", lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED)
    monkeypatch.setattr(app, "release_purchase_generation_claim", lambda purchase_id, logger: calls.append("release"))
    monkeypatch.setattr(app, "call_gemini_fortune", lambda value: calls.append("gemini") or {"miko_intro": "result"})
    monkeypatch.setattr(app, "generate_miko_letter_pdf", lambda user_name, value: calls.append("pdf") or b"pdf")

    def fail_upload(purchase_id, pdf_data, logger):
        calls.append("upload")
        raise app.PdfStorageError("upload failed")

    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", fail_upload)
    monkeypatch.setattr(app, "consume_purchase", lambda *args, **kwargs: calls.append("consume") or True)

    with pytest.raises(app.PdfStorageError):
        app.generate_regular_fortune_pdf_and_consume(payload, "p_123", SimpleNamespace())

    assert calls == ["claim", "gemini", "pdf", "upload", "release"]


def test_recovery_download_works_from_url_token_and_empty_pdf_session(monkeypatch):
    streamlit_stub = make_streamlit_stub(access_token="token")
    streamlit_stub.session_state = AttrDict(active_access_token=None, fortune_pdf_bytes=None)
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: True)
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda object_path: b"pdf-bytes")
    stub_recovery_render_helpers(monkeypatch)

    handled = app.render_pdf_recovery_screen(make_recovery_purchase(), SimpleNamespace(info=lambda *args, **kwargs: None))

    assert handled is True
    download_calls = [call for call in streamlit_stub.calls if call[0] == "download"]
    assert len(download_calls) == 1
    assert download_calls[0][1]["data"] == b"pdf-bytes"
    assert download_calls[0][1]["file_name"] == "ryujin_uranai.pdf"


def test_recovery_rejects_token_mismatch(monkeypatch):
    streamlit_stub = make_streamlit_stub(access_token="wrong-token")
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda object_path: pytest.fail("should not read GCS"))
    stub_recovery_render_helpers(monkeypatch)

    handled = app.render_pdf_recovery_screen(make_recovery_purchase(), SimpleNamespace(info=lambda *args, **kwargs: None))

    assert handled is True
    assert not [call for call in streamlit_stub.calls if call[0] == "download"]


def test_recovery_rejects_expired_pdf(monkeypatch):
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda object_path: pytest.fail("should not read GCS"))
    stub_recovery_render_helpers(monkeypatch)
    logger = SimpleNamespace(info=lambda *args, **kwargs: streamlit_stub.calls.append(("log_info", args, kwargs)))

    handled = app.render_pdf_recovery_screen(
        make_recovery_purchase(pdf_expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)),
        logger,
    )

    assert handled is True
    assert not [call for call in streamlit_stub.calls if call[0] == "download"]


def test_recovery_legacy_purchase_returns_false():
    assert app.render_pdf_recovery_screen(
        {"purchase_id": "p_legacy", "used_flag": True},
        SimpleNamespace(),
    ) is False


def test_recovery_used_false_and_processing_true_are_not_downloadable(monkeypatch):
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda object_path: pytest.fail("should not read GCS"))
    stub_recovery_render_helpers(monkeypatch)

    assert app.render_pdf_recovery_screen(make_recovery_purchase(used_flag=False), SimpleNamespace(info=lambda *args, **kwargs: None)) is True
    assert app.render_pdf_recovery_screen(make_recovery_purchase(generation_processing=True), SimpleNamespace(info=lambda *args, **kwargs: None)) is True
    assert not [call for call in streamlit_stub.calls if call[0] == "download"]


def test_recovery_object_missing_fails_safely(monkeypatch):
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: True)
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda object_path: (_ for _ in ()).throw(FileNotFoundError()))
    stub_recovery_render_helpers(monkeypatch)
    logger = SimpleNamespace(exception=lambda *args, **kwargs: streamlit_stub.calls.append(("log_exception", args, kwargs)))

    handled = app.render_pdf_recovery_screen(make_recovery_purchase(), logger)

    assert handled is True
    assert not [call for call in streamlit_stub.calls if call[0] == "download"]


def test_recovery_hash_mismatch_fails_safely(monkeypatch):
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: True)
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda object_path: b"tampered")
    stub_recovery_render_helpers(monkeypatch)
    logger = SimpleNamespace(error=lambda *args, **kwargs: streamlit_stub.calls.append(("log_error", args, kwargs)))

    handled = app.render_pdf_recovery_screen(make_recovery_purchase(), logger)

    assert handled is True
    assert not [call for call in streamlit_stub.calls if call[0] == "download"]
