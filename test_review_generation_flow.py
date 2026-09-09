import datetime
from types import SimpleNamespace

import pytest

import app
from services.validation_service import validate_review_inputs


def allow_generation_claim(monkeypatch, calls):
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIMED,
    )


def track_generation_release(monkeypatch, calls):
    monkeypatch.setattr(
        app,
        "release_purchase_generation_claim",
        lambda purchase_id, logger: calls.append("release"),
    )


def make_review_inputs():
    return {
        "uploaded_pdf_bytes": b"previous-pdf",
        "pdf_analysis": {"is_valid_previous_pdf": True},
        "current_inputs": {
            "birth_place": "東京都",
            "birth_time_accuracy": "正確に分かる",
            "birth_time_text": "12:00",
            "selected_theme": "仕事",
            "review_theme": "仕事",
        },
        "current_private_inputs": {
            "user_name": "テストユーザー",
            "birth_date": "1990-01-01",
            "birth_place": "東京都",
            "birth_time_accuracy": "正確に分かる",
            "birth_time_text": "12:00",
            "review_theme": "仕事",
            "recent_note": "近況",
        },
        "image_parts": [],
        "purchase_id": "p_review_test",
        "logger": SimpleNamespace(),
    }


def make_pdf_metadata():
    generated_at = datetime.datetime.now(datetime.timezone.utc)
    return {
        "pdf_status": "ready",
        "pdf_object_path": "pdf-recovery/p_review_test/artifact.pdf",
        "pdf_generated_at": generated_at,
        "pdf_expires_at": generated_at + datetime.timedelta(days=7),
        "pdf_sha256": "a" * 64,
        "pdf_artifact_version": "v1",
    }


def test_review_generation_consumes_only_after_summary_fortune_and_pdf(monkeypatch):
    calls = []
    review_context = {"review_context": {"current_inputs": {}}}
    review_fortune = {"intro": "result"}
    allow_generation_claim(monkeypatch, calls)
    track_generation_release(monkeypatch, calls)

    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda pdf_bytes, analysis: calls.append("summary")
        or {"summary_success": True, "previous_summary": {"summary": "previous"}},
    )
    monkeypatch.setattr(
        app,
        "build_review_context",
        lambda **kwargs: calls.append("context") or review_context,
    )
    monkeypatch.setattr(
        app,
        "call_gemini_review_fortune",
        lambda **kwargs: calls.append("fortune")
        or {"fortune_success": True, "review_fortune": review_fortune},
    )
    monkeypatch.setattr(
        app,
        "generate_review_fortune_pdf",
        lambda **kwargs: calls.append("pdf") or b"pdf",
    )
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger: calls.append("consume") or True,
    )
    monkeypatch.setattr(
        app,
        "persist_pdf_recovery_metadata_before_consume",
        lambda purchase_id, pdf_metadata, logger: calls.append("metadata") or True,
    )

    completed = app.generate_review_fortune_pdf_and_consume(**make_review_inputs())

    assert completed == {
        "status": "success",
        "review_context": review_context,
        "review_fortune": review_fortune,
        "pdf_data": b"pdf",
        "pdf_metadata": None,
    }
    assert calls == ["claim", "summary", "context", "fortune", "pdf", "metadata", "consume"]


def test_review_generation_does_not_consume_when_summary_fails(monkeypatch):
    calls = []
    summary_result = {"summary_success": False}
    allow_generation_claim(monkeypatch, calls)
    track_generation_release(monkeypatch, calls)

    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda pdf_bytes, analysis: calls.append("summary") or summary_result,
    )
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger: calls.append("consume") or True,
    )

    completed = app.generate_review_fortune_pdf_and_consume(**make_review_inputs())

    assert completed == {
        "status": "summary_failed",
        "pdf_summary": summary_result,
    }
    assert calls == ["claim", "summary", "release"]


def test_review_generation_does_not_consume_when_fortune_fails(monkeypatch):
    calls = []
    fortune_result = {"fortune_success": False}
    allow_generation_claim(monkeypatch, calls)
    track_generation_release(monkeypatch, calls)

    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda pdf_bytes, analysis: calls.append("summary")
        or {"summary_success": True, "previous_summary": {}},
    )
    monkeypatch.setattr(
        app,
        "build_review_context",
        lambda **kwargs: calls.append("context") or {},
    )
    monkeypatch.setattr(
        app,
        "call_gemini_review_fortune",
        lambda **kwargs: calls.append("fortune") or fortune_result,
    )
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger: calls.append("consume") or True,
    )

    completed = app.generate_review_fortune_pdf_and_consume(**make_review_inputs())

    assert completed == {
        "status": "fortune_failed",
        "review_fortune_result": fortune_result,
    }
    assert calls == ["claim", "summary", "context", "fortune", "release"]


def test_review_generation_does_not_consume_when_pdf_fails(monkeypatch):
    calls = []
    allow_generation_claim(monkeypatch, calls)
    track_generation_release(monkeypatch, calls)

    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda pdf_bytes, analysis: calls.append("summary")
        or {"summary_success": True, "previous_summary": {}},
    )
    monkeypatch.setattr(
        app,
        "build_review_context",
        lambda **kwargs: calls.append("context") or {},
    )
    monkeypatch.setattr(
        app,
        "call_gemini_review_fortune",
        lambda **kwargs: calls.append("fortune")
        or {"fortune_success": True, "review_fortune": {}},
    )

    def fail_pdf(**kwargs):
        calls.append("pdf")
        raise RuntimeError("pdf failed")

    monkeypatch.setattr(app, "generate_review_fortune_pdf", fail_pdf)
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger: calls.append("consume") or True,
    )

    with pytest.raises(RuntimeError, match="pdf failed"):
        app.generate_review_fortune_pdf_and_consume(**make_review_inputs())

    assert calls == ["claim", "summary", "context", "fortune", "pdf", "release"]


def test_review_generation_returns_no_result_when_consume_fails(monkeypatch):
    calls = []
    allow_generation_claim(monkeypatch, calls)
    track_generation_release(monkeypatch, calls)

    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda pdf_bytes, analysis: calls.append("summary")
        or {"summary_success": True, "previous_summary": {}},
    )
    monkeypatch.setattr(
        app,
        "build_review_context",
        lambda **kwargs: calls.append("context") or {},
    )
    monkeypatch.setattr(
        app,
        "call_gemini_review_fortune",
        lambda **kwargs: calls.append("fortune")
        or {"fortune_success": True, "review_fortune": {}},
    )
    monkeypatch.setattr(
        app,
        "generate_review_fortune_pdf",
        lambda **kwargs: calls.append("pdf") or b"pdf",
    )
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger: calls.append("consume") or False,
    )
    monkeypatch.setattr(
        app,
        "persist_pdf_recovery_metadata_before_consume",
        lambda purchase_id, pdf_metadata, logger: calls.append("metadata") or True,
    )

    completed = app.generate_review_fortune_pdf_and_consume(**make_review_inputs())

    assert completed == {"status": "consume_failed"}
    assert calls == ["claim", "summary", "context", "fortune", "pdf", "metadata", "consume", "release"]


def test_review_generation_persists_metadata_before_consume(monkeypatch):
    calls = []
    metadata = make_pdf_metadata()
    allow_generation_claim(monkeypatch, calls)
    track_generation_release(monkeypatch, calls)
    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda pdf_bytes, analysis: calls.append("summary")
        or {"summary_success": True, "previous_summary": {}},
    )
    monkeypatch.setattr(app, "build_review_context", lambda **kwargs: calls.append("context") or {})
    monkeypatch.setattr(
        app,
        "call_gemini_review_fortune",
        lambda **kwargs: calls.append("fortune")
        or {"fortune_success": True, "review_fortune": {"intro": "result"}},
    )
    monkeypatch.setattr(app, "generate_review_fortune_pdf", lambda **kwargs: calls.append("pdf") or b"pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append("upload") or metadata)
    monkeypatch.setattr(app, "persist_pdf_recovery_metadata_before_consume", lambda purchase_id, pdf_metadata, logger: calls.append("metadata") or True)
    monkeypatch.setattr(app, "consume_purchase", lambda purchase_id, logger, pdf_metadata=None: calls.append("consume") or True)

    completed = app.generate_review_fortune_pdf_and_consume(**make_review_inputs())

    assert completed["status"] == "success"
    assert completed["pdf_metadata"] == metadata
    assert calls == ["claim", "summary", "context", "fortune", "pdf", "upload", "metadata", "consume"]


def test_review_generation_stops_after_preconsume_metadata_failure(monkeypatch):
    calls = []
    metadata = make_pdf_metadata()
    allow_generation_claim(monkeypatch, calls)
    track_generation_release(monkeypatch, calls)
    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda pdf_bytes, analysis: calls.append("summary")
        or {"summary_success": True, "previous_summary": {}},
    )
    monkeypatch.setattr(app, "build_review_context", lambda **kwargs: calls.append("context") or {})
    monkeypatch.setattr(
        app,
        "call_gemini_review_fortune",
        lambda **kwargs: calls.append("fortune")
        or {"fortune_success": True, "review_fortune": {"intro": "result"}},
    )
    monkeypatch.setattr(app, "generate_review_fortune_pdf", lambda **kwargs: calls.append("pdf") or b"pdf")
    monkeypatch.setattr(app, "prepare_pdf_recovery_metadata", lambda purchase_id, pdf_data, logger: calls.append("upload") or metadata)
    monkeypatch.setattr(app, "persist_pdf_recovery_metadata_before_consume", lambda purchase_id, pdf_metadata, logger: calls.append("metadata") or False)
    monkeypatch.setattr(app, "consume_purchase", lambda *args, **kwargs: calls.append("consume") or True)

    completed = app.generate_review_fortune_pdf_and_consume(**make_review_inputs())

    assert completed == {"status": "consume_failed"}
    assert calls == ["claim", "summary", "context", "fortune", "pdf", "upload", "metadata", "release"]


def test_review_generation_does_not_call_gemini_when_claim_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda purchase_id, logger: calls.append("claim") or app.GENERATION_CLAIM_PROCESSING,
    )
    track_generation_release(monkeypatch, calls)
    monkeypatch.setattr(
        app,
        "call_gemini_review_pdf_summary",
        lambda pdf_bytes, analysis: calls.append("summary") or {"summary_success": True},
    )

    completed = app.generate_review_fortune_pdf_and_consume(**make_review_inputs())

    assert completed == {
        "status": "claim_failed",
        "claim_status": app.GENERATION_CLAIM_PROCESSING,
    }
    assert calls == ["claim"]


def test_review_validation_requires_birth_place():
    uploaded_pdf = SimpleNamespace(
        name="previous.pdf",
        type="application/pdf",
        getvalue=lambda: b"%PDF-1.4 test",
    )
    uploaded_image = SimpleNamespace(name="palm.jpg", size=100)

    errors = validate_review_inputs(
        user_name="テスト ユーザー",
        birth_date_selected=True,
        birth_place="",
        review_theme="仕事運",
        uploaded_pdf=uploaded_pdf,
        uploaded_files=[uploaded_image],
        hand_sides=["左手"],
        review_memo="近況です。",
    )

    assert "出生地をご入力ください。" in errors


def test_review_validation_limits_birth_place_length():
    uploaded_pdf = SimpleNamespace(
        name="previous.pdf",
        type="application/pdf",
        getvalue=lambda: b"%PDF-1.4 test",
    )
    uploaded_image = SimpleNamespace(name="palm.jpg", size=100)

    errors = validate_review_inputs(
        user_name="テスト ユーザー",
        birth_date_selected=True,
        birth_place="東" * 101,
        review_theme="仕事運",
        uploaded_pdf=uploaded_pdf,
        uploaded_files=[uploaded_image],
        hand_sides=["左手"],
        review_memo="近況です。",
    )

    assert "出生地は100文字以内でご入力ください。" in errors
