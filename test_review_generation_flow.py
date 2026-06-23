from types import SimpleNamespace

import pytest

import app


def make_review_inputs():
    return {
        "uploaded_pdf_bytes": b"previous-pdf",
        "pdf_analysis": {"is_valid_previous_pdf": True},
        "current_inputs": {"selected_theme": "仕事"},
        "current_private_inputs": {"user_name": "テストユーザー"},
        "image_parts": [],
        "purchase_id": "p_review_test",
        "logger": SimpleNamespace(),
    }


def test_review_generation_consumes_only_after_summary_fortune_and_pdf(monkeypatch):
    calls = []
    review_context = {"review_context": {"current_inputs": {}}}
    review_fortune = {"intro": "result"}

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

    completed = app.generate_review_fortune_pdf_and_consume(**make_review_inputs())

    assert completed == {
        "status": "success",
        "review_context": review_context,
        "review_fortune": review_fortune,
        "pdf_data": b"pdf",
    }
    assert calls == ["summary", "context", "fortune", "pdf", "consume"]


def test_review_generation_does_not_consume_when_summary_fails(monkeypatch):
    calls = []
    summary_result = {"summary_success": False}

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
    assert calls == ["summary"]


def test_review_generation_does_not_consume_when_fortune_fails(monkeypatch):
    calls = []
    fortune_result = {"fortune_success": False}

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
    assert calls == ["summary", "context", "fortune"]


def test_review_generation_does_not_consume_when_pdf_fails(monkeypatch):
    calls = []

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

    assert calls == ["summary", "context", "fortune", "pdf"]


def test_review_generation_returns_no_result_when_consume_fails(monkeypatch):
    calls = []

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

    completed = app.generate_review_fortune_pdf_and_consume(**make_review_inputs())

    assert completed == {"status": "consume_failed"}
    assert calls == ["summary", "context", "fortune", "pdf", "consume"]
