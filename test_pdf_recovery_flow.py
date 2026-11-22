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


class RecordingLogger:
    def __init__(self):
        self.calls = []

    def info(self, *args, **kwargs):
        self.calls.append(("info", args, kwargs))

    def warning(self, *args, **kwargs):
        self.calls.append(("warning", args, kwargs))

    def error(self, *args, **kwargs):
        self.calls.append(("error", args, kwargs))

    def exception(self, *args, **kwargs):
        self.calls.append(("exception", args, kwargs))


class ContextStub:
    def __init__(self, value=None):
        self.value = value

    def __enter__(self):
        return self.value if self.value is not None else self

    def __exit__(self, *args):
        return None


def make_streamlit_stub(access_token="token"):
    calls = []
    return SimpleNamespace(
        calls=calls,
        session_state=AttrDict(active_access_token=access_token),
        query_params={"purchase_id": "p_123"},
        success=lambda value, **kwargs: calls.append(("success", value)),
        info=lambda value, **kwargs: calls.append(("info", value)),
        warning=lambda value, **kwargs: calls.append(("warning", value)),
        error=lambda value, **kwargs: calls.append(("error", value)),
        download_button=lambda **kwargs: calls.append(("download", kwargs)),
        markdown=lambda *args, **kwargs: calls.append(("markdown", args, kwargs)),
        columns=lambda spec: [SimpleNamespace(__enter__=lambda self: self, __exit__=lambda *args: None) for _ in range(len(spec))],
        stop=lambda: (_ for _ in ()).throw(StopCalled()),
    )


def make_review_form_streamlit_stub():
    calls = []
    session_state = AttrDict(
        active_access_token="token",
        ga4_form_displayed_purchase_ids=set(),
        review_context="existing-context",
        review_fortune={"existing": "fortune"},
        review_fortune_purchase_id="existing-purchase",
        review_pdf_bytes=b"existing-pdf",
        review_pdf_generated_purchase_id="existing-purchase",
        review_purchase_consumed=set(),
    )

    placeholder = ContextStub()
    placeholder.empty = lambda: calls.append(("placeholder_empty", None))
    placeholder.button = lambda *args, **kwargs: True

    previous_pdf = SimpleNamespace(getvalue=lambda: b"previous-pdf")

    def file_uploader(*args, **kwargs):
        if kwargs.get("key") == "review_previous_pdf":
            return previous_pdf
        return []

    def selectbox(label, options, index=0, **kwargs):
        key = kwargs.get("key")
        if key == "review_birth_year":
            return 2000
        if key == "review_birth_month":
            return 1
        if key == "review_birth_day":
            return 1
        return options[index]

    return SimpleNamespace(
        calls=calls,
        session_state=session_state,
        query_params={},
        caption=lambda value, **kwargs: calls.append(("caption", value)),
        markdown=lambda *args, **kwargs: calls.append(("markdown", args, kwargs)),
        file_uploader=file_uploader,
        text_input=lambda *args, **kwargs: "テスト",
        text_area=lambda *args, **kwargs: "近況メモ",
        selectbox=selectbox,
        radio=lambda *args, **kwargs: "不明",
        columns=lambda spec: [ContextStub() for _ in range(spec if isinstance(spec, int) else len(spec))],
        empty=lambda: placeholder,
        button=lambda *args, **kwargs: True,
        spinner=lambda *args, **kwargs: ContextStub(),
        error=lambda value, **kwargs: calls.append(("error", value)),
        info=lambda value, **kwargs: calls.append(("info", value)),
        success=lambda value, **kwargs: calls.append(("success", value)),
        warning=lambda value, **kwargs: calls.append(("warning", value)),
        download_button=lambda **kwargs: calls.append(("download", kwargs)),
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
        "pdf_generated_at": datetime.datetime.now(datetime.timezone.utc),
        "pdf_expires_at": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
        "pdf_sha256": app.sha256_pdf(b"pdf-bytes"),
        "pdf_artifact_version": "v1",
    }
    record.update(updates)
    return record


def stub_recovery_render_helpers(monkeypatch):
    monkeypatch.setattr(app, "scroll_completion_screen_to_top", lambda: None)
    monkeypatch.setattr(app, "render_form_gap", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "render_header", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "render_completion_screen", lambda *args, **kwargs: None)


@pytest.mark.parametrize("product_type", [app.PRODUCT_TYPE_REGULAR, app.PRODUCT_TYPE_REVIEW])
def test_pdf_recovery_completion_notice_shows_for_ready_recovery_purchase(monkeypatch, product_type):
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: True)

    app.render_pdf_recovery_completion_notice(make_recovery_purchase(product_type=product_type))

    info_calls = [call for call in streamlit_stub.calls if call[0] == "info"]
    assert len(info_calls) == 1
    notice = info_calls[0][1]
    assert "鑑定結果のPDFは" in notice
    assert "決済完了から7日間" in notice
    assert "このページから再ダウンロードできます" in notice
    assert "再取得期限を過ぎるとダウンロードできなくなります" in notice
    assert "このページのURLは第三者と共有しないでください" not in notice


@pytest.mark.parametrize(
    "record",
    [
        {"purchase_id": "p_legacy", "used_flag": True},
        make_recovery_purchase(pdf_status=None),
        make_recovery_purchase(pdf_object_path=""),
        make_recovery_purchase(pdf_sha256=""),
        make_recovery_purchase(pdf_artifact_version=""),
    ],
)
def test_pdf_recovery_completion_notice_hides_without_ready_metadata(monkeypatch, record):
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: True)

    app.render_pdf_recovery_completion_notice(record)

    assert not [call for call in streamlit_stub.calls if call[0] == "info"]


def test_pdf_recovery_completion_notice_hides_when_recovery_disabled(monkeypatch):
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: False)

    app.render_pdf_recovery_completion_notice(make_recovery_purchase())

    assert not [call for call in streamlit_stub.calls if call[0] == "info"]


def test_prepare_pdf_recovery_metadata_is_disabled_when_env_missing(monkeypatch):
    monkeypatch.delenv("PDF_RECOVERY_BUCKET", raising=False)
    monkeypatch.setattr(
        app,
        "upload_pdf_for_recovery",
        lambda **kwargs: pytest.fail("upload should not run when env is missing"),
    )
    logger = RecordingLogger()

    assert app.prepare_pdf_recovery_metadata("p_123", b"pdf", logger) is None
    assert any(call[0] == "warning" and call[1][0] == "pdf_recovery_disabled_bucket_unset" for call in logger.calls)


def test_regular_generation_uploads_before_consuming_when_recovery_enabled(monkeypatch):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")
    metadata = {
        "pdf_status": "ready",
        "pdf_object_path": "pdf-recovery/p_123/artifact.pdf",
        "pdf_generated_at": datetime.datetime.now(datetime.timezone.utc),
        "pdf_expires_at": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
        "pdf_sha256": "a" * 64,
        "pdf_artifact_version": "v1",
    }
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED,
    )
    monkeypatch.setattr(app, "APP_ENV", "production")
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: True)
    monkeypatch.setattr(app, "release_purchase_generation_claim", lambda purchase_id, logger: calls.append("release"))
    monkeypatch.setattr(app, "call_gemini_fortune", lambda value: calls.append("gemini") or {"miko_intro": "result"})
    monkeypatch.setattr(app, "generate_miko_letter_pdf", lambda user_name, value: calls.append("pdf") or b"pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append("upload") or metadata)
    monkeypatch.setattr(
        app,
        "persist_pdf_recovery_metadata_before_consume",
        lambda purchase_id, pdf_metadata, logger: calls.append(("metadata", pdf_metadata)) or app.PdfMetadataSaveResult(app.PdfMetadataSaveStatus.SAVED if pdf_metadata else app.PdfMetadataSaveStatus.NOT_REQUIRED),
    )
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger, pdf_metadata=None: calls.append(("consume", pdf_metadata)) or True,
    )

    completed = app.generate_regular_fortune_pdf_and_consume(payload, "p_123", SimpleNamespace())

    assert completed == ({"miko_intro": "result"}, b"pdf", metadata)
    assert calls == ["claim", "gemini", "pdf", "upload", ("metadata", metadata), ("consume", metadata)]


@pytest.mark.parametrize(
    ("app_env", "bucket_value"),
    [
        ("production", None),
        ("prod", None),
        ("PRODUCTION", None),
        (" prod ", None),
        ("production", ""),
        ("production", "   "),
    ],
)
def test_regular_generation_production_missing_bucket_fails_before_claim(monkeypatch, app_env, bucket_value):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")
    logger = RecordingLogger()

    monkeypatch.setattr(app, "APP_ENV", app_env)
    if bucket_value is None:
        monkeypatch.delenv("PDF_RECOVERY_BUCKET", raising=False)
    else:
        monkeypatch.setenv("PDF_RECOVERY_BUCKET", bucket_value)
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda purchase_id, logger: calls.append("claim") or pytest.fail("claim should not run"),
    )
    monkeypatch.setattr(
        app,
        "release_purchase_generation_claim",
        lambda purchase_id, logger: calls.append("release") or pytest.fail("release should not run"),
    )
    monkeypatch.setattr(app, "call_gemini_fortune", lambda value: calls.append("gemini") or {"miko_intro": "result"})
    monkeypatch.setattr(app, "generate_miko_letter_pdf", lambda user_name, value: calls.append("pdf") or b"pdf")
    monkeypatch.setattr(app, "consume_purchase", lambda *args, **kwargs: calls.append("consume") or True)
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)

    completed = app.generate_regular_fortune_pdf_and_consume(payload, "p_123", logger)

    assert completed is None
    assert calls == []
    assert streamlit_stub.session_state.generation_claim_status == "configuration_error"
    assert any(call[0] == "error" and call[1][0] == "pdf_recovery_configuration_missing" for call in logger.calls)


def test_regular_generation_production_missing_bucket_does_not_release(monkeypatch):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")

    monkeypatch.setattr(app, "APP_ENV", "production")
    monkeypatch.delenv("PDF_RECOVERY_BUCKET", raising=False)
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda purchase_id, logger: calls.append("claim") or pytest.fail("claim should not run"),
    )
    monkeypatch.setattr(
        app,
        "release_purchase_generation_claim",
        lambda purchase_id, logger: calls.append("release") or pytest.fail("release should not run"),
    )
    monkeypatch.setattr(app, "consume_purchase", lambda *args, **kwargs: calls.append("consume") or True)
    monkeypatch.setattr(app, "st", make_streamlit_stub())

    assert app.generate_regular_fortune_pdf_and_consume(payload, "p_123", RecordingLogger()) is None

    assert calls == []


@pytest.mark.parametrize("app_env", ["staging", "development", "local"])
def test_regular_generation_non_production_missing_bucket_preserves_fallback_consume(monkeypatch, app_env):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")
    monkeypatch.setattr(app, "APP_ENV", app_env)
    monkeypatch.delenv("PDF_RECOVERY_BUCKET", raising=False)
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED,
    )
    monkeypatch.setattr(app, "release_purchase_generation_claim", lambda purchase_id, logger: calls.append("release"))
    monkeypatch.setattr(app, "call_gemini_fortune", lambda value: calls.append("gemini") or {"miko_intro": "result"})
    monkeypatch.setattr(app, "generate_miko_letter_pdf", lambda user_name, value: calls.append("pdf") or b"pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append("fallback") or None)
    monkeypatch.setattr(
        app,
        "persist_pdf_recovery_metadata_before_consume",
        lambda purchase_id, pdf_metadata, logger: calls.append(("metadata", pdf_metadata)) or app.PdfMetadataSaveResult(app.PdfMetadataSaveStatus.SAVED if pdf_metadata else app.PdfMetadataSaveStatus.NOT_REQUIRED),
    )
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger, pdf_metadata=None: calls.append(("consume", pdf_metadata)) or True,
    )

    completed = app.generate_regular_fortune_pdf_and_consume(payload, "p_123", RecordingLogger())

    assert completed == ({"miko_intro": "result"}, b"pdf", None)
    assert calls == ["claim", "gemini", "pdf", "fallback", ("metadata", None), ("consume", None)]


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


def test_release_generation_claim_retries_after_first_failure(monkeypatch):
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app.time, "sleep", lambda seconds: None)
    calls = []

    def flaky_release(purchase_id, access_token):
        calls.append((purchase_id, access_token))
        if len(calls) == 1:
            raise RuntimeError("temporary firestore failure")
        return True

    monkeypatch.setattr(app, "release_generation_claim_transaction", flaky_release)
    logger = RecordingLogger()

    assert app.release_purchase_generation_claim("p_123", logger) is True
    assert calls == [("p_123", "token"), ("p_123", "token")]
    assert any(call[0] == "warning" and call[1][0] == "purchase_generation_claim_release_retry" for call in logger.calls)
    assert any(call[0] == "info" and call[1][0] == "purchase_generation_claim_released" for call in logger.calls)


def test_release_generation_claim_all_retries_fail_blocks_success(monkeypatch):
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(app, "release_generation_claim_transaction", lambda purchase_id, access_token: False)
    logger = RecordingLogger()

    assert app.release_purchase_generation_claim("p_123", logger) is False
    with pytest.raises(app.GenerationReleaseError):
        app.release_generation_claim_after_failure("p_123", logger)
    assert any(call[0] == "error" and call[1][0] == "generation_release_failed" for call in logger.calls)


def test_upload_failure_with_release_failure_does_not_consume_or_succeed(monkeypatch):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")
    monkeypatch.setattr(app, "claim_purchase_generation", lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED)
    monkeypatch.setattr(app, "call_gemini_fortune", lambda value: calls.append("gemini") or {"miko_intro": "result"})
    monkeypatch.setattr(app, "generate_miko_letter_pdf", lambda user_name, value: calls.append("pdf") or b"pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append("upload") or (_ for _ in ()).throw(app.PdfStorageError("upload failed")))
    monkeypatch.setattr(app, "release_purchase_generation_claim", lambda purchase_id, logger: calls.append("release") or False)
    monkeypatch.setattr(app, "consume_purchase", lambda *args, **kwargs: calls.append("consume") or True)

    with pytest.raises(app.GenerationReleaseError):
        app.generate_regular_fortune_pdf_and_consume(payload, "p_123", RecordingLogger())

    assert calls == ["claim", "gemini", "pdf", "upload", "release"]


def test_consume_failure_leaves_purchase_unused_and_does_not_reuse_orphan_object(monkeypatch):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")
    metadata = {
        "pdf_status": "ready",
        "pdf_object_path": "pdf-recovery/p_123/orphan.pdf",
        "pdf_generated_at": datetime.datetime.now(datetime.timezone.utc),
        "pdf_expires_at": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
        "pdf_sha256": "a" * 64,
        "pdf_artifact_version": "v1",
    }
    monkeypatch.setattr(app, "claim_purchase_generation", lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED)
    monkeypatch.setattr(app, "call_gemini_fortune", lambda value: calls.append("gemini") or {"miko_intro": "result"})
    monkeypatch.setattr(app, "generate_miko_letter_pdf", lambda user_name, value: calls.append("pdf") or b"pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append(("upload", metadata["pdf_object_path"])) or metadata)
    monkeypatch.setattr(
        app,
        "persist_pdf_recovery_metadata_before_consume",
        lambda purchase_id, pdf_metadata, logger: calls.append(("metadata", pdf_metadata)) or app.PdfMetadataSaveResult(app.PdfMetadataSaveStatus.SAVED if pdf_metadata else app.PdfMetadataSaveStatus.NOT_REQUIRED),
    )
    monkeypatch.setattr(app, "consume_purchase", lambda purchase_id, logger, pdf_metadata=None: calls.append(("consume", pdf_metadata)) or False)
    monkeypatch.setattr(app, "release_purchase_generation_claim", lambda purchase_id, logger: calls.append("release") or True)

    completed = app.generate_regular_fortune_pdf_and_consume(payload, "p_123", RecordingLogger())

    assert completed is None
    assert calls == [
        "claim",
        "gemini",
        "pdf",
        ("upload", "pdf-recovery/p_123/orphan.pdf"),
        ("metadata", metadata),
        ("consume", metadata),
    ]


def test_regular_generation_persists_metadata_before_consume(monkeypatch):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")
    metadata = {
        "pdf_status": "ready",
        "pdf_object_path": "pdf-recovery/p_123/artifact.pdf",
        "pdf_generated_at": datetime.datetime.now(datetime.timezone.utc),
        "pdf_expires_at": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
        "pdf_sha256": "a" * 64,
        "pdf_artifact_version": "v1",
    }
    monkeypatch.setattr(app, "claim_purchase_generation", lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED)
    monkeypatch.setattr(app, "release_purchase_generation_claim", lambda purchase_id, logger: calls.append("release") or True)
    monkeypatch.setattr(app, "call_gemini_fortune", lambda value: calls.append("gemini") or {"miko_intro": "result"})
    monkeypatch.setattr(app, "generate_miko_letter_pdf", lambda user_name, value: calls.append("pdf") or b"pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append("upload") or metadata)
    monkeypatch.setattr(app, "persist_pdf_recovery_metadata_before_consume", lambda purchase_id, pdf_metadata, logger: calls.append("metadata") or app.PdfMetadataSaveResult(app.PdfMetadataSaveStatus.SAVED if pdf_metadata else app.PdfMetadataSaveStatus.NOT_REQUIRED))
    monkeypatch.setattr(app, "consume_purchase", lambda purchase_id, logger, pdf_metadata=None: calls.append("consume") or True)

    assert app.generate_regular_fortune_pdf_and_consume(payload, "p_123", RecordingLogger()) == (
        {"miko_intro": "result"},
        b"pdf",
        metadata,
    )
    assert calls == ["claim", "gemini", "pdf", "upload", "metadata", "consume"]


@pytest.mark.parametrize("save_status", [app.PdfMetadataSaveStatus.NOT_SAVED, app.PdfMetadataSaveStatus.UNKNOWN])
def test_regular_generation_stops_after_preconsume_metadata_failure(monkeypatch, save_status):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")
    metadata = {
        "pdf_status": "ready",
        "pdf_object_path": "pdf-recovery/p_123/artifact.pdf",
        "pdf_generated_at": datetime.datetime.now(datetime.timezone.utc),
        "pdf_expires_at": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
        "pdf_sha256": "a" * 64,
        "pdf_artifact_version": "v1",
    }
    monkeypatch.setattr(app, "claim_purchase_generation", lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED)
    monkeypatch.setattr(app, "release_purchase_generation_claim", lambda purchase_id, logger: calls.append("release") or True)
    monkeypatch.setattr(app, "call_gemini_fortune", lambda value: calls.append("gemini") or {"miko_intro": "result"})
    monkeypatch.setattr(app, "generate_miko_letter_pdf", lambda user_name, value: calls.append("pdf") or b"pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append("upload") or metadata)
    monkeypatch.setattr(app, "persist_pdf_recovery_metadata_before_consume", lambda purchase_id, pdf_metadata, logger: calls.append("metadata") or app.PdfMetadataSaveResult(save_status))
    monkeypatch.setattr(app, "consume_purchase", lambda *args, **kwargs: calls.append("consume") or True)

    assert app.generate_regular_fortune_pdf_and_consume(payload, "p_123", RecordingLogger()) is None
    assert calls == ["claim", "gemini", "pdf", "upload", "metadata"]


def test_interrupted_ready_purchase_finalizes_with_consume_only(monkeypatch):
    calls = []
    streamlit_stub = make_streamlit_stub(access_token="token")
    monkeypatch.setattr(app, "st", streamlit_stub)
    record = make_recovery_purchase(
        used_flag=False,
        generation_processing=True,
        pdf_generated_at=datetime.datetime.now(datetime.timezone.utc),
    )
    monkeypatch.setattr(
        app,
        "can_finalize_interrupted_pdf_generation",
        lambda active_purchase, access_token: calls.append(("check", access_token)) or True,
    )
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger, **kwargs: calls.append(("consume", kwargs)) or True,
    )
    monkeypatch.setattr(app, "get_purchase_record", lambda purchase_id: dict(record, used_flag=True, generation_processing=False))
    verified_pdf = app.VerifiedRecoveryPdf(
        record["purchase_id"], app.get_recovery_pdf_metadata_snapshot(record), b"pdf-bytes"
    )
    monkeypatch.setattr(app, "verify_stored_pdf_for_recovery", lambda purchase, token, logger: verified_pdf)
    verified_pdf_out = []

    finalized = app.finalize_interrupted_pdf_generation_if_ready(
        record, RecordingLogger(), verified_pdf_out=verified_pdf_out
    )

    assert verified_pdf_out == [verified_pdf]
    assert finalized["used_flag"] is True
    assert finalized["generation_processing"] is False
    assert calls == [
        ("check", "token"),
        (
            "consume",
            {
                "require_ready_pdf_metadata": True,
                "require_generation_processing": True,
                "expected_pdf_metadata": {
                    "pdf_status": record["pdf_status"],
                    "pdf_generated_at": record["pdf_generated_at"],
                    "pdf_object_path": record["pdf_object_path"],
                    "pdf_expires_at": record["pdf_expires_at"],
                    "pdf_sha256": record["pdf_sha256"],
                    "pdf_artifact_version": record["pdf_artifact_version"],
                },
            },
        ),
    ]


def test_recovery_download_works_from_active_token_and_empty_pdf_session(monkeypatch):
    streamlit_stub = make_streamlit_stub(access_token="token")
    streamlit_stub.session_state = AttrDict(active_access_token="token", fortune_pdf_bytes=None)
    streamlit_stub.query_params = {"purchase_id": "p_123"}
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


@pytest.mark.parametrize("pdf_sha256", [None, "", "not-a-sha256"])
def test_recovery_rejects_missing_empty_or_invalid_sha256(monkeypatch, pdf_sha256):
    streamlit_stub = make_streamlit_stub()
    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda object_path: pytest.fail("should not read GCS"))
    stub_recovery_render_helpers(monkeypatch)

    handled = app.render_pdf_recovery_screen(make_recovery_purchase(pdf_sha256=pdf_sha256), RecordingLogger())

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
    assert app.render_pdf_recovery_screen(make_recovery_purchase(generation_processing=None), RecordingLogger()) is True
    missing_processing = make_recovery_purchase()
    missing_processing.pop("generation_processing")
    assert app.render_pdf_recovery_screen(missing_processing, RecordingLogger()) is True
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


def test_review_generation_uploads_before_consuming_when_recovery_enabled(monkeypatch):
    calls = []
    review_context = {"review_context": {"current_inputs": {}}}
    review_fortune = {"intro": "result"}
    metadata = {
        "pdf_status": "ready",
        "pdf_object_path": "pdf-recovery/p_review/artifact.pdf",
        "pdf_generated_at": datetime.datetime.now(datetime.timezone.utc),
        "pdf_expires_at": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
        "pdf_sha256": "a" * 64,
        "pdf_artifact_version": "v1",
    }
    monkeypatch.setattr(app, "APP_ENV", "production")
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: True)
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED,
    )
    monkeypatch.setattr(app, "release_purchase_generation_claim", lambda purchase_id, logger: calls.append("release") or True)
    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda pdf_bytes, analysis: calls.append("summary") or {"summary_success": True, "previous_summary": {"summary": "previous"}},
    )
    monkeypatch.setattr(app, "build_review_context", lambda **kwargs: calls.append("context") or review_context)
    monkeypatch.setattr(app, "call_gemini_review_fortune", lambda **kwargs: calls.append("fortune") or {"fortune_success": True, "review_fortune": review_fortune})
    monkeypatch.setattr(app, "generate_review_fortune_pdf", lambda **kwargs: calls.append("pdf") or b"review-pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append("upload") or metadata)
    monkeypatch.setattr(
        app,
        "persist_pdf_recovery_metadata_before_consume",
        lambda purchase_id, pdf_metadata, logger: calls.append(("metadata", pdf_metadata)) or app.PdfMetadataSaveResult(app.PdfMetadataSaveStatus.SAVED if pdf_metadata else app.PdfMetadataSaveStatus.NOT_REQUIRED),
    )
    monkeypatch.setattr(app, "consume_purchase", lambda purchase_id, logger, pdf_metadata=None: calls.append(("consume", pdf_metadata)) or True)

    completed = app.generate_review_fortune_pdf_and_consume(
        uploaded_pdf_bytes=b"previous-pdf",
        pdf_analysis={"is_valid_previous_pdf": True},
        current_inputs={},
        current_private_inputs={},
        image_parts=[],
        purchase_id="p_review",
        logger=RecordingLogger(),
    )

    assert completed["status"] == "success"
    assert calls == [
        "claim",
        "summary",
        "context",
        "fortune",
        "pdf",
        "upload",
        ("metadata", metadata),
        ("consume", metadata),
    ]


@pytest.mark.parametrize(
    ("app_env", "bucket_value"),
    [
        ("production", None),
        ("prod", None),
        ("PRODUCTION", None),
        (" prod ", None),
        ("production", ""),
        ("production", "   "),
    ],
)
def test_review_generation_production_missing_bucket_fails_before_claim(monkeypatch, app_env, bucket_value):
    calls = []
    logger = RecordingLogger()

    monkeypatch.setattr(app, "APP_ENV", app_env)
    if bucket_value is None:
        monkeypatch.delenv("PDF_RECOVERY_BUCKET", raising=False)
    else:
        monkeypatch.setenv("PDF_RECOVERY_BUCKET", bucket_value)
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda purchase_id, logger: calls.append("claim") or pytest.fail("claim should not run"),
    )
    monkeypatch.setattr(
        app,
        "release_purchase_generation_claim",
        lambda purchase_id, logger: calls.append("release") or pytest.fail("release should not run"),
    )
    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda *args, **kwargs: calls.append("summary") or {"summary_success": True},
    )
    monkeypatch.setattr(app, "generate_review_fortune_pdf", lambda **kwargs: calls.append("pdf") or b"review-pdf")
    monkeypatch.setattr(app, "consume_purchase", lambda *args, **kwargs: calls.append("consume") or True)

    completed = app.generate_review_fortune_pdf_and_consume(
        uploaded_pdf_bytes=b"previous-pdf",
        pdf_analysis={"is_valid_previous_pdf": True},
        current_inputs={},
        current_private_inputs={},
        image_parts=[],
        purchase_id="p_review",
        logger=logger,
    )

    assert completed == {"status": "configuration_error"}
    assert calls == []
    assert any(call[0] == "error" and call[1][0] == "pdf_recovery_configuration_missing" for call in logger.calls)


@pytest.mark.parametrize("app_env", ["staging", "development", "local"])
def test_review_generation_non_production_missing_bucket_preserves_fallback_consume(monkeypatch, app_env):
    calls = []
    review_context = {"review_context": {"current_inputs": {}}}
    review_fortune = {"intro": "result"}

    monkeypatch.setattr(app, "APP_ENV", app_env)
    monkeypatch.delenv("PDF_RECOVERY_BUCKET", raising=False)
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED,
    )
    monkeypatch.setattr(app, "release_purchase_generation_claim", lambda purchase_id, logger: calls.append("release") or True)
    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda pdf_bytes, analysis: calls.append("summary") or {"summary_success": True, "previous_summary": {"summary": "previous"}},
    )
    monkeypatch.setattr(app, "build_review_context", lambda **kwargs: calls.append("context") or review_context)
    monkeypatch.setattr(app, "call_gemini_review_fortune", lambda **kwargs: calls.append("fortune") or {"fortune_success": True, "review_fortune": review_fortune})
    monkeypatch.setattr(app, "generate_review_fortune_pdf", lambda **kwargs: calls.append("pdf") or b"review-pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append("fallback") or None)
    monkeypatch.setattr(app, "consume_purchase", lambda purchase_id, logger, pdf_metadata=None: calls.append(("consume", pdf_metadata)) or True)

    completed = app.generate_review_fortune_pdf_and_consume(
        uploaded_pdf_bytes=b"previous-pdf",
        pdf_analysis={"is_valid_previous_pdf": True},
        current_inputs={},
        current_private_inputs={},
        image_parts=[],
        purchase_id="p_review",
        logger=RecordingLogger(),
    )

    assert completed["status"] == "success"
    assert calls == [
        "claim",
        "summary",
        "context",
        "fortune",
        "pdf",
        "fallback",
        ("consume", None),
    ]


def test_review_form_configuration_error_does_not_write_success_session_state(monkeypatch):
    streamlit_stub = make_review_form_streamlit_stub()
    logger = RecordingLogger()
    purchase = {
        "purchase_id": "p_review",
        "payment_status": "paid",
        "used_flag": False,
        "token_expires_at": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
        "product_type": app.PRODUCT_TYPE_REVIEW,
    }

    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(app, "render_form_gap", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "track_ga4_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "track_purchase_ga4_event_once", lambda *args, **kwargs: True)
    monkeypatch.setattr(app, "get_purchase_record", lambda purchase_id: purchase)
    monkeypatch.setattr(app, "validate_review_inputs", lambda **kwargs: [])
    monkeypatch.setattr(
        app,
        "validate_review_pdf_content",
        lambda pdf_bytes: {"is_valid_previous_pdf": True, "previous_reading_date": "2026-01-01"},
    )
    monkeypatch.setattr(app, "build_image_parts", lambda normalized_images: [])
    monkeypatch.setattr(
        app,
        "generate_review_fortune_pdf_and_consume",
        lambda **kwargs: {"status": "configuration_error"},
    )

    app.render_review_fortune_form(purchase, logger)

    assert ("success", "前回PDFの確認と要約が完了しました。") not in streamlit_stub.calls
    assert streamlit_stub.session_state.review_context is None
    assert streamlit_stub.session_state.review_fortune is None
    assert streamlit_stub.session_state.review_fortune_purchase_id is None
    assert streamlit_stub.session_state.review_pdf_bytes is None
    assert streamlit_stub.session_state.review_pdf_generated_purchase_id is None
    assert "p_review" not in streamlit_stub.session_state.review_purchase_consumed
    assert any(
        call[0] == "error" and "PDF保存設定に不備" in call[1]
        for call in streamlit_stub.calls
    )


# Save-result and request-scoped PDF safety contracts.
import copy
from datetime import datetime as RecoveryDatetime, timedelta, timezone
from services import firestore_service as fs
CONTRACT_NOW = RecoveryDatetime(2026,11,21,12,0,tzinfo=timezone.utc)
CONTRACT_PDF_BYTES = b"pdf-bytes"

@pytest.fixture
def recovery_contract_context(monkeypatch):
    streamlit = make_streamlit_stub("token")
    monkeypatch.setattr(app, "st", streamlit)
    monkeypatch.setattr(app, "utc_now", lambda: CONTRACT_NOW)
    monkeypatch.setattr(fs, "_now_utc", lambda: CONTRACT_NOW)
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: True)
    stub_recovery_render_helpers(monkeypatch)
    return streamlit, RecordingLogger()


def contract_purchase(product="regular", state="processing", **updates):
    record = make_recovery_purchase(
        product_type=product,
        used_flag=state == "used",
        generation_processing=state == "processing",
        checkout_completed_at=CONTRACT_NOW - timedelta(days=1),
        generation_processing_started_at=CONTRACT_NOW - timedelta(minutes=30),
        token_expires_at=CONTRACT_NOW + timedelta(hours=1),
        pdf_generated_at=CONTRACT_NOW - timedelta(minutes=15),
        pdf_expires_at=CONTRACT_NOW + timedelta(days=6),
    )
    record.update(updates)
    return record


def contract_raise_timeout(*args, **kwargs):
    raise TimeoutError("synthetic write response lost")


def contract_no_call(*args, **kwargs):
    pytest.fail("Unexpected call outside the explicitly stubbed path")


@pytest.mark.parametrize("status", list(app.PdfMetadataSaveStatus))
def test_metadata_result_forbids_truthiness(status):
    with pytest.raises(TypeError, match="explicitly"):
        bool(app.PdfMetadataSaveResult(status))


def test_no_metadata_has_distinct_not_required_contract(monkeypatch, recovery_contract_context):
    monkeypatch.setattr(app, "save_pdf_recovery_metadata_transaction", contract_no_call)
    monkeypatch.setattr(app, "get_purchase_record", contract_no_call)
    result = app.persist_pdf_recovery_metadata_before_consume("p_123", None, recovery_contract_context[1])
    assert result.status is app.PdfMetadataSaveStatus.NOT_REQUIRED
    assert result.purchase is None


@pytest.mark.parametrize("saved,expected", [
    (True, app.PdfMetadataSaveStatus.SAVED),
    (False, app.PdfMetadataSaveStatus.NOT_SAVED),
    (None, app.PdfMetadataSaveStatus.NOT_SAVED),
])
def test_direct_save_result_is_explicit_and_does_not_read_or_release(monkeypatch, recovery_contract_context, saved, expected):
    calls = []
    record = contract_purchase()
    metadata = app.get_recovery_pdf_metadata_snapshot(record)
    monkeypatch.setattr(
        app, "save_pdf_recovery_metadata_transaction",
        lambda pid, token, candidate: calls.append((pid, token, candidate)) or saved,
    )
    monkeypatch.setattr(app, "get_purchase_record", contract_no_call)
    monkeypatch.setattr(app, "release_generation_claim_after_failure", contract_no_call)
    monkeypatch.setattr(app, "consume_purchase", contract_no_call)
    result = app.persist_pdf_recovery_metadata_before_consume("p_123", metadata, recovery_contract_context[1])
    assert result.status is expected
    assert result.purchase is None
    assert calls == [("p_123", "token", metadata)]


@pytest.mark.parametrize("product", ["regular", "review"])
@pytest.mark.parametrize("state", ["processing", "idle", "used"])
def test_commit_response_loss_can_resolve_only_from_identical_valid_purchase(monkeypatch, recovery_contract_context, product, state):
    record = contract_purchase(product, state)
    metadata = app.get_recovery_pdf_metadata_snapshot(record)
    monkeypatch.setattr(app, "save_pdf_recovery_metadata_transaction", contract_raise_timeout)
    monkeypatch.setattr(app, "get_purchase_record", lambda pid: copy.deepcopy(record))
    monkeypatch.setattr(app, "release_generation_claim_after_failure", contract_no_call)
    monkeypatch.setattr(app, "consume_purchase", contract_no_call)
    result = app.persist_pdf_recovery_metadata_before_consume("p_123", metadata, recovery_contract_context[1])
    assert result.status is app.PdfMetadataSaveStatus.SAVED
    assert result.purchase == record


@pytest.mark.parametrize("field,value", [
    ("pdf_status", "pending"),
    ("pdf_object_path", "pdf-recovery/p_123/other.pdf"),
    ("pdf_generated_at", CONTRACT_NOW - timedelta(minutes=14)),
    ("pdf_expires_at", CONTRACT_NOW + timedelta(days=5)),
    ("pdf_sha256", "b" * 64),
    ("pdf_artifact_version", "v2"),
])
def test_readback_must_match_every_attempted_metadata_field(monkeypatch, recovery_contract_context, field, value):
    record = contract_purchase()
    metadata = app.get_recovery_pdf_metadata_snapshot(record)
    record[field] = value
    monkeypatch.setattr(app, "save_pdf_recovery_metadata_transaction", contract_raise_timeout)
    monkeypatch.setattr(app, "get_purchase_record", lambda pid: record)
    monkeypatch.setattr(app, "release_generation_claim_after_failure", contract_no_call)
    monkeypatch.setattr(app, "consume_purchase", contract_no_call)
    result = app.persist_pdf_recovery_metadata_before_consume("p_123", metadata, recovery_contract_context[1])
    assert result.status is app.PdfMetadataSaveStatus.UNKNOWN
    assert result.purchase is None


@pytest.mark.parametrize("changes", [
    {"payment_status": "pending"},
    {"access_token_hash": app.hashlib.sha256(b"other-synthetic-token").hexdigest()},
    {"pdf_expires_at": CONTRACT_NOW},
    {"generation_processing_started_at": None},
    {"generation_processing_started_at": CONTRACT_NOW + timedelta(days=7)},
    {"generation_processing": None},
    {"purchase_id": "p_other_synthetic"},
])
def test_invalid_readback_purchase_never_resolves_unknown(monkeypatch, recovery_contract_context, changes):
    record = contract_purchase(**changes)
    metadata = app.get_recovery_pdf_metadata_snapshot(record)
    monkeypatch.setattr(app, "save_pdf_recovery_metadata_transaction", contract_raise_timeout)
    monkeypatch.setattr(app, "get_purchase_record", lambda pid: record)
    monkeypatch.setattr(app, "release_generation_claim_after_failure", contract_no_call)
    monkeypatch.setattr(app, "consume_purchase", contract_no_call)
    result = app.persist_pdf_recovery_metadata_before_consume("p_123", metadata, recovery_contract_context[1])
    assert result.status is app.PdfMetadataSaveStatus.UNKNOWN


@pytest.mark.parametrize("readback", ["absent", "metadata_absent", "timeout"])
def test_ambiguous_readback_keeps_unknown_and_never_unlocks(monkeypatch, recovery_contract_context, readback):
    record = contract_purchase()
    metadata = app.get_recovery_pdf_metadata_snapshot(record)
    monkeypatch.setattr(app, "save_pdf_recovery_metadata_transaction", contract_raise_timeout)
    if readback == "timeout":
        monkeypatch.setattr(app, "get_purchase_record", contract_raise_timeout)
    else:
        result = None if readback == "absent" else {
            key: value for key, value in record.items() if key not in app.PDF_METADATA_FIELDS
        }
        monkeypatch.setattr(app, "get_purchase_record", lambda pid: result)
    monkeypatch.setattr(app, "release_generation_claim_after_failure", contract_no_call)
    monkeypatch.setattr(app, "consume_purchase", contract_no_call)
    saved = app.persist_pdf_recovery_metadata_before_consume("p_123", metadata, recovery_contract_context[1])
    assert saved.status is app.PdfMetadataSaveStatus.UNKNOWN
    assert saved.purchase is None


@pytest.mark.parametrize("product", ["regular", "review"])
@pytest.mark.parametrize("state", ["processing", "idle", "used"])
def test_verifier_uses_real_eligibility_and_returns_bound_bytes(monkeypatch, recovery_contract_context, product, state):
    record = contract_purchase(product, state)
    calls = []
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda path: calls.append(path) or CONTRACT_PDF_BYTES)
    verified = app.verify_stored_pdf_for_recovery(record, "token", recovery_contract_context[1])
    assert verified is not None
    assert verified.purchase_id == "p_123"
    assert verified.metadata == app.get_recovery_pdf_metadata_snapshot(record)
    assert verified.pdf_bytes == CONTRACT_PDF_BYTES
    assert calls == [record["pdf_object_path"]]


@pytest.mark.parametrize("error", [FileNotFoundError, TimeoutError, PermissionError, app.PdfStorageConfigError])
@pytest.mark.parametrize("state", ["processing", "idle"])
def test_t08_verification_read_failure_never_consumes(monkeypatch, recovery_contract_context, error, state):
    record = contract_purchase(state=state)
    calls = []
    def fail_read(path):
        calls.append(path)
        raise error("synthetic storage failure")
    monkeypatch.setattr(app, "read_pdf_for_recovery", fail_read)
    monkeypatch.setattr(app, "consume_purchase", contract_no_call)
    monkeypatch.setattr(app, "consume_idle_pdf_purchase_transaction", contract_no_call)
    monkeypatch.setattr(app, "get_purchase_record", contract_no_call)
    before = copy.deepcopy(record)
    assert (app.finalize_idle_pdf_generation_if_ready if state == "idle" else app.finalize_interrupted_pdf_generation_if_ready)(record, recovery_contract_context[1]) is None
    assert record == before
    assert calls == [record["pdf_object_path"]]


@pytest.mark.parametrize("data", [b"tampered", None])
@pytest.mark.parametrize("state", ["processing", "idle"])
def test_verifier_rejects_hash_or_type_mismatch_without_consumption(monkeypatch, recovery_contract_context, data, state):
    record = contract_purchase(state=state)
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda path: data)
    monkeypatch.setattr(app, "consume_purchase", contract_no_call)
    monkeypatch.setattr(app, "consume_idle_pdf_purchase_transaction", contract_no_call)
    assert (app.finalize_idle_pdf_generation_if_ready if state == "idle" else app.finalize_interrupted_pdf_generation_if_ready)(record, recovery_contract_context[1]) is None
    assert record["used_flag"] is False


@pytest.mark.parametrize("changes", [
    {"payment_status": "pending"},
    {"access_token_hash": app.hashlib.sha256(b"other-token").hexdigest()},
    {"pdf_expires_at": CONTRACT_NOW},
    {"pdf_sha256": "invalid"},
])
def test_verifier_rejects_ineligible_record_before_gcs(monkeypatch, recovery_contract_context, changes):
    monkeypatch.setattr(app, "read_pdf_for_recovery", contract_no_call)
    record = contract_purchase(**changes)
    assert app.verify_stored_pdf_for_recovery(record, "token", recovery_contract_context[1]) is None


@pytest.mark.parametrize("change", ["token", "path", "generated_at", "expiry", "hash", "version", "used"])
def test_already_used_readback_never_returns_bytes_if_purchase_changes_during_verification(monkeypatch, recovery_contract_context, change):
    record = contract_purchase(state="used")
    fresh = copy.deepcopy(record)
    metadata = app.get_recovery_pdf_metadata_snapshot(record)
    mapping = {
        "token": ("access_token_hash", app.hashlib.sha256(b"changed-token").hexdigest()),
        "path": ("pdf_object_path", "pdf-recovery/p_123/changed.pdf"),
        "generated_at": ("pdf_generated_at", CONTRACT_NOW - timedelta(minutes=14)),
        "expiry": ("pdf_expires_at", CONTRACT_NOW + timedelta(days=5)),
        "hash": ("pdf_sha256", "b" * 64),
        "version": ("pdf_artifact_version", "v2"),
        "used": ("used_flag", False),
    }
    def read(path):
        key, value = mapping[change]
        fresh[key] = value
        return CONTRACT_PDF_BYTES
    monkeypatch.setattr(app, "read_pdf_for_recovery", read)
    monkeypatch.setattr(app, "get_purchase_record", lambda pid: fresh)
    monkeypatch.setattr(app, "consume_purchase", contract_no_call)
    monkeypatch.setattr(app, "consume_idle_pdf_purchase_transaction", contract_no_call)
    saved = app.PdfMetadataSaveResult(app.PdfMetadataSaveStatus.SAVED, record)
    assert app.finish_generation_after_metadata_save("p_123", saved, b"unchecked", metadata, recovery_contract_context[1]) is None


def test_already_used_readback_downloads_without_session_cache_or_second_consume(monkeypatch, recovery_contract_context):
    record = contract_purchase(state="used")
    metadata = app.get_recovery_pdf_metadata_snapshot(record)
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda path: CONTRACT_PDF_BYTES)
    monkeypatch.setattr(app, "get_purchase_record", lambda pid: copy.deepcopy(record))
    monkeypatch.setattr(app, "consume_purchase", contract_no_call)
    monkeypatch.setattr(app, "consume_idle_pdf_purchase_transaction", contract_no_call)
    saved = app.PdfMetadataSaveResult(app.PdfMetadataSaveStatus.SAVED, record)
    assert app.finish_generation_after_metadata_save("p_123", saved, b"unchecked", metadata, recovery_contract_context[1]) is None
    assert recovery_contract_context[0].session_state.generation_claim_status == "recovery_completed"
    assert [call[1]["data"] for call in recovery_contract_context[0].calls if call[0] == "download"] == [CONTRACT_PDF_BYTES]
    assert not any(key in recovery_contract_context[0].session_state for key in ("fortune_pdf_bytes","review_pdf_bytes"))


@pytest.mark.parametrize("mismatch", ["purchase_id", "metadata"])
def test_render_ignores_verified_bytes_for_other_binding_and_falls_back_to_existing_read(monkeypatch, recovery_contract_context, mismatch):
    record = contract_purchase(state="used")
    metadata = app.get_recovery_pdf_metadata_snapshot(record)
    verified = app.VerifiedRecoveryPdf(
        "p_other" if mismatch == "purchase_id" else "p_123",
        dict(metadata, pdf_artifact_version="old") if mismatch == "metadata" else metadata,
        b"wrong cached bytes",
    )
    reads = []
    monkeypatch.setattr(app, "read_pdf_for_recovery", lambda path: reads.append(path) or CONTRACT_PDF_BYTES)
    assert app.render_pdf_recovery_screen(record, recovery_contract_context[1], verified_pdf=verified) is True
    downloads = [call for call in recovery_contract_context[0].calls if call[0] == "download"]
    assert reads == [record["pdf_object_path"]]
    assert len(downloads) == 1 and downloads[0][1]["data"] == CONTRACT_PDF_BYTES


def test_render_reuses_current_request_verified_bytes_without_second_gcs_read(monkeypatch, recovery_contract_context):
    record = contract_purchase(state="used")
    verified = app.VerifiedRecoveryPdf("p_123", app.get_recovery_pdf_metadata_snapshot(record), CONTRACT_PDF_BYTES)
    monkeypatch.setattr(app, "read_pdf_for_recovery", contract_no_call)
    assert app.render_pdf_recovery_screen(record, recovery_contract_context[1], verified_pdf=verified) is True
    assert [call[1]["data"] for call in recovery_contract_context[0].calls if call[0] == "download"] == [CONTRACT_PDF_BYTES]


def test_render_keeps_auth_guard_even_with_matching_verified_bytes(monkeypatch, recovery_contract_context):
    record = contract_purchase(state="used")
    verified = app.VerifiedRecoveryPdf("p_123", app.get_recovery_pdf_metadata_snapshot(record), CONTRACT_PDF_BYTES)
    recovery_contract_context[0].session_state.active_access_token = "wrong-token"
    monkeypatch.setattr(app, "read_pdf_for_recovery", contract_no_call)
    assert app.render_pdf_recovery_screen(record, recovery_contract_context[1], verified_pdf=verified) is True
    assert not [call for call in recovery_contract_context[0].calls if call[0] == "download"]


@pytest.mark.parametrize("state", ["processing", "idle"])
@pytest.mark.parametrize("product", ["regular", "review"])
def test_recovery_finalizer_reads_and_verifies_before_consume(monkeypatch, recovery_contract_context, state, product):
    record = contract_purchase(product, state)
    fresh = copy.deepcopy(record)
    calls = []
    def read(path):
        assert record["used_flag"] is False
        calls.append("read")
        return CONTRACT_PDF_BYTES
    def consume(*args, **kwargs):
        assert calls == ["read"]
        expected = args[2] if state == "idle" else kwargs["expected_pdf_metadata"]
        assert expected == app.get_recovery_pdf_metadata_snapshot(record)
        calls.append("consume")
        fresh.update(used_flag=True, generation_processing=False)
        return True
    def refresh(pid):
        calls.append("refresh")
        return fresh
    monkeypatch.setattr(app, "read_pdf_for_recovery", read)
    monkeypatch.setattr(app, "consume_purchase", consume if state == "processing" else contract_no_call)
    monkeypatch.setattr(app, "consume_idle_pdf_purchase_transaction", consume if state == "idle" else contract_no_call)
    monkeypatch.setattr(app, "get_purchase_record", refresh)
    verified = []
    finalize = app.finalize_idle_pdf_generation_if_ready if state == "idle" else app.finalize_interrupted_pdf_generation_if_ready
    assert finalize(record, recovery_contract_context[1], verified_pdf_out=verified) == fresh
    assert calls == ["read", "consume", "refresh"]
    assert len(verified) == 1 and verified[0].pdf_bytes == CONTRACT_PDF_BYTES
