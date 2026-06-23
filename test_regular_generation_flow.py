from types import SimpleNamespace

import pytest

import app


def test_regular_generation_consumes_only_after_gemini_and_pdf(monkeypatch):
    calls = []
    result = {"miko_intro": "result"}
    payload = SimpleNamespace(user_name="テストユーザー")

    monkeypatch.setattr(
        app,
        "call_gemini_fortune",
        lambda value: calls.append("gemini") or result,
    )
    monkeypatch.setattr(
        app,
        "generate_miko_letter_pdf",
        lambda user_name, value: calls.append("pdf") or b"pdf",
    )
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger: calls.append("consume") or True,
    )

    completed = app.generate_regular_fortune_pdf_and_consume(
        payload,
        "p_test",
        SimpleNamespace(),
    )

    assert completed == (result, b"pdf")
    assert calls == ["gemini", "pdf", "consume"]


def test_regular_generation_does_not_consume_when_gemini_fails(monkeypatch):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")

    def fail_gemini(value):
        calls.append("gemini")
        raise RuntimeError("gemini failed")

    monkeypatch.setattr(app, "call_gemini_fortune", fail_gemini)
    monkeypatch.setattr(
        app,
        "generate_miko_letter_pdf",
        lambda user_name, value: calls.append("pdf") or b"pdf",
    )
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger: calls.append("consume") or True,
    )

    with pytest.raises(RuntimeError, match="gemini failed"):
        app.generate_regular_fortune_pdf_and_consume(
            payload,
            "p_test",
            SimpleNamespace(),
        )

    assert calls == ["gemini"]


def test_regular_generation_does_not_consume_when_pdf_fails(monkeypatch):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")

    monkeypatch.setattr(
        app,
        "call_gemini_fortune",
        lambda value: calls.append("gemini") or {"miko_intro": "result"},
    )

    def fail_pdf(user_name, value):
        calls.append("pdf")
        raise RuntimeError("pdf failed")

    monkeypatch.setattr(app, "generate_miko_letter_pdf", fail_pdf)
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger: calls.append("consume") or True,
    )

    with pytest.raises(RuntimeError, match="pdf failed"):
        app.generate_regular_fortune_pdf_and_consume(
            payload,
            "p_test",
            SimpleNamespace(),
        )

    assert calls == ["gemini", "pdf"]


def test_regular_generation_returns_none_when_consume_fails(monkeypatch):
    calls = []
    payload = SimpleNamespace(user_name="テストユーザー")

    monkeypatch.setattr(
        app,
        "call_gemini_fortune",
        lambda value: calls.append("gemini") or {"miko_intro": "result"},
    )
    monkeypatch.setattr(
        app,
        "generate_miko_letter_pdf",
        lambda user_name, value: calls.append("pdf") or b"pdf",
    )
    monkeypatch.setattr(
        app,
        "consume_purchase",
        lambda purchase_id, logger: calls.append("consume") or False,
    )

    completed = app.generate_regular_fortune_pdf_and_consume(
        payload,
        "p_test",
        SimpleNamespace(),
    )

    assert completed is None
    assert calls == ["gemini", "pdf", "consume"]