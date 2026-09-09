from types import SimpleNamespace
from datetime import date

import app
from models.schemas import FortuneInput, PalmImageMeta
from services import fortune_service
from services.image_service import ImageProcessingError, NormalizedPalmImage
from services.validation_service import validate_inputs


class RecordingLogger:
    def __init__(self):
        self.calls = []

    def info(self, *args, **kwargs):
        self.calls.append(("info", args, kwargs))

    def error(self, *args, **kwargs):
        self.calls.append(("error", args, kwargs))


class AttrDict(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


class ContextStub:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def empty(self):
        return None


class StreamlitStub:
    def __init__(self, uploaded_images, *, uploaded_pdf=None, click_submit=False):
        self.uploaded_images = uploaded_images
        self.uploaded_pdf = uploaded_pdf
        self.click_submit = click_submit
        self.errors = []
        self.infos = []
        self.images = []
        self.warnings = []
        self.buttons = []
        self.session_state = AttrDict(
            ga4_form_displayed_purchase_ids=set(),
            ga4_pdf_generated_purchase_ids=set(),
            fortune_json=None,
            fortune_pdf_bytes=None,
            fortune_pdf_purchase_id=None,
            fortune_pdf_recovery_metadata=None,
            review_context=None,
            review_fortune=None,
            review_fortune_purchase_id=None,
            review_pdf_bytes=None,
            review_pdf_generated_purchase_id=None,
            review_pdf_recovery_metadata=None,
            review_purchase_consumed=set(),
        )

    def caption(self, *args, **kwargs):
        return None

    def markdown(self, *args, **kwargs):
        return None

    def columns(self, count):
        return [ContextStub() for _ in range(count)]

    def text_input(self, label, *args, **kwargs):
        if label in {"姓", "名"}:
            return "山田" if label == "姓" else "太郎"
        return "東京都"

    def selectbox(self, label, options, *args, **kwargs):
        if label == "年":
            return 2000
        if label == "月":
            return 1
        if label == "日":
            return 1
        if label == "相談カテゴリ1":
            return "総合運"
        if label in {"相談カテゴリ2", "相談カテゴリ3"}:
            return "（未選択）"
        if label == "今回とくに見返したいテーマ":
            return "総合運"
        return options[0]

    def radio(self, label, options, *args, **kwargs):
        return options[0]

    def text_area(self, *args, **kwargs):
        return "近況メモ"

    def file_uploader(self, label, *args, **kwargs):
        if kwargs.get("key") == "review_previous_pdf":
            return self.uploaded_pdf
        return self.uploaded_images

    def error(self, *args, **kwargs):
        self.errors.append(args[0] if args else "")

    def warning(self, *args, **kwargs):
        self.warnings.append(args[0] if args else "")

    def success(self, *args, **kwargs):
        self.session_state.setdefault("success_calls", []).append(args[0] if args else "")
        return None

    def info(self, *args, **kwargs):
        self.infos.append(args[0] if args else "")
        return None

    def image(self, *args, **kwargs):
        self.images.append(args)
        return None

    def button(self, label, *args, **kwargs):
        self.buttons.append({"label": label, **kwargs})
        return self.click_submit

    def empty(self):
        return ContextStub()

    def divider(self):
        return None

    def download_button(self, *args, **kwargs):
        return None

    def spinner(self, *args, **kwargs):
        return ContextStub()

    def stop(self):
        raise AssertionError("st.stop should not be reached in this test")


def normalized_image(name="palm.heic"):
    return NormalizedPalmImage(
        original_name=name,
        jpeg_bytes=b"jpeg",
        mime_type="image/jpeg",
        width=10,
        height=10,
        source_format="HEIF",
        original_size_bytes=100,
        normalized_size_bytes=4,
    )


def uploaded(name: str, size: int = 100):
    return SimpleNamespace(name=name, size=size, getvalue=lambda: b"image")


def uploaded_pdf():
    return SimpleNamespace(name="previous.pdf", size=10, type="application/pdf", getvalue=lambda: b"%PDF-1.4")


def patch_common(monkeypatch, streamlit_stub, calls):
    from ui import components

    monkeypatch.setattr(app, "st", streamlit_stub)
    monkeypatch.setattr(components, "st", streamlit_stub)
    monkeypatch.setattr(app, "track_ga4_event", lambda *args, **kwargs: True)
    monkeypatch.setattr(app, "get_purchase_record", lambda purchase_id: {"purchase_id": purchase_id, "payment_status": "paid", "used_flag": False})
    monkeypatch.setattr(app, "is_purchase_ready", lambda record: True)
    monkeypatch.setattr(app, "track_purchase_ga4_event_once", lambda *args, **kwargs: calls.append("reading_started"))
    monkeypatch.setattr(app, "generate_regular_fortune_pdf_and_consume", lambda *args, **kwargs: calls.append("regular_generate") or None)
    monkeypatch.setattr(
        app,
        "generate_review_fortune_pdf_and_consume",
        lambda *args, **kwargs: calls.append("review_generate") or {"status": "consume_failed"},
    )

    from services import validation_service

    monkeypatch.setattr(validation_service, "get_gemini_api_key", lambda: "dummy")
    monkeypatch.setattr(validation_service, "get_app_passphrase", lambda: "dummy")


def test_regular_image_error_click_is_guarded(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([uploaded("broken.jpg")], click_submit=True)
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(
        app,
        "normalize_uploaded_images",
        lambda files: (_ for _ in ()).throw(ImageProcessingError("unreadable", "画像を読み込めませんでした。")),
    )

    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert streamlit_stub.buttons[-1]["disabled"] is True
    assert "reading_started" not in calls
    assert "regular_generate" not in calls


def test_review_image_error_click_is_guarded(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([uploaded("broken.jpg")], uploaded_pdf=uploaded_pdf(), click_submit=True)
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "get_purchase_product_type", lambda record: app.PRODUCT_TYPE_REVIEW)
    monkeypatch.setattr(
        app,
        "normalize_uploaded_images",
        lambda files: (_ for _ in ()).throw(ImageProcessingError("unreadable", "画像を読み込めませんでした。")),
    )

    app.render_review_fortune_form(
        {"purchase_id": "p_review", "payment_status": "paid", "used_flag": False, "product_type": app.PRODUCT_TYPE_REVIEW},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert streamlit_stub.buttons[-1]["disabled"] is True
    assert "reading_started" not in calls
    assert "review_generate" not in calls


def test_regular_inputs_allow_missing_palm_images():
    errors = validate_inputs(
        user_name="山田太郎",
        birth_place="東京都",
        categories=["総合運"],
        concern_detail="近況メモ",
        birth_time_accuracy="不明",
        birth_hour=None,
        birth_minute=None,
        uploaded_files=[],
        hand_sides=[],
    )

    assert "手相画像をアップロードしてください。" not in errors


def test_regular_no_image_can_enter_submit_path(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([], click_submit=True)
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "normalize_uploaded_images", lambda files: calls.append("normalize"))

    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert streamlit_stub.buttons[-1]["disabled"] is False
    assert "normalize" not in calls
    assert "reading_started" in calls
    assert "regular_generate" in calls


def test_regular_cached_heic_image_survives_submit_rerun(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([uploaded("palm.heic")])
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "normalize_uploaded_images", lambda files: [normalized_image("palm.heic")])
    captured = {}
    monkeypatch.setattr(
        app,
        "generate_regular_fortune_pdf_and_consume",
        lambda payload, *args, **kwargs: (captured.setdefault("image_count", payload.image_count), ({"miko_intro": "result"}, b"pdf", None))[1],
    )

    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    streamlit_stub.uploaded_images = []
    streamlit_stub.click_submit = True
    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert captured["image_count"] == 1


def test_regular_cached_png_image_survives_submit_rerun(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([uploaded("palm.png")])
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "normalize_uploaded_images", lambda files: [normalized_image("palm.png")])
    captured = {}
    monkeypatch.setattr(
        app,
        "generate_regular_fortune_pdf_and_consume",
        lambda payload, *args, **kwargs: (captured.setdefault("image_count", payload.image_count), ({"miko_intro": "result"}, b"pdf", None))[1],
    )

    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    streamlit_stub.uploaded_images = []
    streamlit_stub.click_submit = True
    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert captured["image_count"] == 1


def test_regular_cached_image_is_not_reused_for_other_purchase(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([uploaded("palm.heic")])
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "normalize_uploaded_images", lambda files: [normalized_image("palm.heic")])
    captured = {}
    monkeypatch.setattr(
        app,
        "generate_regular_fortune_pdf_and_consume",
        lambda payload, *args, **kwargs: (captured.setdefault("image_count", payload.image_count), ({"miko_intro": "result"}, b"pdf", None))[1],
    )

    app.render_fortune_form(
        {"purchase_id": "p_first", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    streamlit_stub.uploaded_images = []
    streamlit_stub.click_submit = True
    app.render_fortune_form(
        {"purchase_id": "p_second", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert captured["image_count"] == 0


def test_regular_removed_image_cache_is_not_reused(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([uploaded("palm.heic")])
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "normalize_uploaded_images", lambda files: [normalized_image("palm.heic")])
    captured = {}
    monkeypatch.setattr(
        app,
        "generate_regular_fortune_pdf_and_consume",
        lambda payload, *args, **kwargs: (captured.setdefault("image_count", payload.image_count), ({"miko_intro": "result"}, b"pdf", None))[1],
    )

    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    streamlit_stub.uploaded_images = []
    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    streamlit_stub.click_submit = True
    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert captured["image_count"] == 0


def test_regular_valid_image_can_enter_submit_path(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([uploaded("palm.heic")], click_submit=True)
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "normalize_uploaded_images", lambda files: [normalized_image()])

    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert streamlit_stub.buttons[-1]["disabled"] is False
    assert "reading_started" in calls
    assert "regular_generate" in calls


def test_regular_production_missing_bucket_stops_before_reading_started_and_generation(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([], click_submit=True)
    logger = RecordingLogger()
    purchase = {
        "purchase_id": "p_test",
        "payment_status": "paid",
        "used_flag": False,
        "generation_processing": False,
    }
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "APP_ENV", "production")
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: False)
    monkeypatch.setattr(app, "get_purchase_record", lambda purchase_id: purchase)
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda *args, **kwargs: calls.append("claim"),
    )
    monkeypatch.setattr(app, "consume_purchase", lambda *args, **kwargs: calls.append("consume"))

    app.render_fortune_form(purchase, logger)

    assert "reading_started" not in calls
    assert "regular_generate" not in calls
    assert "claim" not in calls
    assert "consume" not in calls
    assert purchase["used_flag"] is False
    assert purchase["generation_processing"] is False
    assert streamlit_stub.session_state.fortune_json is None
    assert streamlit_stub.session_state.fortune_pdf_bytes is None
    assert streamlit_stub.session_state.fortune_pdf_purchase_id is None
    assert not streamlit_stub.session_state.get("success_calls")
    assert any("PDF保存設定に不備" in message for message in streamlit_stub.errors)
    assert any(
        call[0] == "error" and call[1][0] == "pdf_recovery_configuration_missing"
        for call in logger.calls
    )


def test_review_valid_image_can_enter_submit_path(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([uploaded("palm.heic")], uploaded_pdf=uploaded_pdf(), click_submit=True)
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "get_purchase_product_type", lambda record: app.PRODUCT_TYPE_REVIEW)
    monkeypatch.setattr(app, "normalize_uploaded_images", lambda files: [normalized_image()])
    monkeypatch.setattr(
        app,
        "validate_review_pdf_content",
        lambda pdf_bytes: {"is_valid_previous_pdf": True, "previous_reading_date": "2026-08-01"},
    )

    app.render_review_fortune_form(
        {"purchase_id": "p_review", "payment_status": "paid", "used_flag": False, "product_type": app.PRODUCT_TYPE_REVIEW},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert streamlit_stub.buttons[-1]["disabled"] is False
    assert "reading_started" in calls
    assert "review_generate" in calls


def test_review_production_missing_bucket_stops_before_pdf_validation_gemini_and_reading_started(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([uploaded("palm.heic")], uploaded_pdf=uploaded_pdf(), click_submit=True)
    logger = RecordingLogger()
    purchase = {
        "purchase_id": "p_review",
        "payment_status": "paid",
        "used_flag": False,
        "generation_processing": False,
        "product_type": app.PRODUCT_TYPE_REVIEW,
    }
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "APP_ENV", "production")
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: False)
    monkeypatch.setattr(app, "get_purchase_product_type", lambda record: app.PRODUCT_TYPE_REVIEW)
    monkeypatch.setattr(app, "get_purchase_record", lambda purchase_id: purchase)
    monkeypatch.setattr(app, "normalize_uploaded_images", lambda files: [normalized_image()])
    monkeypatch.setattr(
        app,
        "validate_review_pdf_content",
        lambda pdf_bytes: calls.append("validate_pdf") or {"is_valid_previous_pdf": True},
    )
    monkeypatch.setattr(
        fortune_service,
        "call_gemini_review_pdf_analysis",
        lambda pdf_bytes: calls.append("gemini_pdf_analysis"),
    )
    monkeypatch.setattr(
        app,
        "claim_purchase_generation",
        lambda *args, **kwargs: calls.append("claim"),
    )
    monkeypatch.setattr(app, "consume_purchase", lambda *args, **kwargs: calls.append("consume"))

    app.render_review_fortune_form(purchase, logger)

    assert "validate_pdf" not in calls
    assert "gemini_pdf_analysis" not in calls
    assert "reading_started" not in calls
    assert "review_generate" not in calls
    assert "claim" not in calls
    assert "consume" not in calls
    assert purchase["used_flag"] is False
    assert purchase["generation_processing"] is False
    assert streamlit_stub.session_state.review_context is None
    assert streamlit_stub.session_state.review_fortune is None
    assert streamlit_stub.session_state.review_fortune_purchase_id is None
    assert streamlit_stub.session_state.review_pdf_bytes is None
    assert streamlit_stub.session_state.review_pdf_generated_purchase_id is None
    assert "p_review" not in streamlit_stub.session_state.review_purchase_consumed
    assert not streamlit_stub.session_state.get("success_calls")
    assert any("PDF保存設定に不備" in message for message in streamlit_stub.errors)
    assert any(
        call[0] == "error" and call[1][0] == "pdf_recovery_configuration_missing"
        for call in logger.calls
    )


def ready_pdf_recovery_metadata():
    return {
        "pdf_status": "ready",
        "pdf_object_path": "pdf-recovery/p_test/artifact.pdf",
        "pdf_expires_at": app.datetime.datetime.now(app.datetime.timezone.utc) + app.datetime.timedelta(days=7),
        "pdf_sha256": app.sha256_pdf(b"pdf"),
        "pdf_artifact_version": "v1",
    }


def test_regular_completion_shows_pdf_recovery_notice_for_ready_metadata(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([], click_submit=False)
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: True)
    monkeypatch.setattr(app, "render_html_box", lambda *args, **kwargs: None)
    streamlit_stub.session_state.fortune_json = {"miko_intro": "result"}
    streamlit_stub.session_state.fortune_pdf_bytes = b"pdf"
    streamlit_stub.session_state.fortune_pdf_purchase_id = "p_test"
    streamlit_stub.session_state.fortune_pdf_recovery_metadata = ready_pdf_recovery_metadata()
    streamlit_stub.session_state.user_name = "山田 太郎"

    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert any("決済完了から7日間" in message for message in streamlit_stub.infos)
    assert any("このページから再ダウンロードできます" in message for message in streamlit_stub.infos)
    assert any("このページのURLは第三者と共有しないでください" in message for message in streamlit_stub.infos)


def test_review_completion_shows_pdf_recovery_notice_for_ready_metadata(monkeypatch):
    calls = []
    streamlit_stub = StreamlitStub([], uploaded_pdf=uploaded_pdf(), click_submit=False)
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "is_pdf_recovery_enabled", lambda: True)
    monkeypatch.setattr(app, "render_html_box", lambda *args, **kwargs: None)
    streamlit_stub.session_state.review_fortune = {"intro": "result"}
    streamlit_stub.session_state.review_fortune_purchase_id = "p_review"
    streamlit_stub.session_state.review_pdf_bytes = b"pdf"
    streamlit_stub.session_state.review_pdf_generated_purchase_id = "p_review"
    streamlit_stub.session_state.review_pdf_recovery_metadata = ready_pdf_recovery_metadata()

    app.render_review_fortune_form(
        {"purchase_id": "p_review", "payment_status": "paid", "used_flag": False, "product_type": app.PRODUCT_TYPE_REVIEW},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert any("決済完了から7日間" in message for message in streamlit_stub.infos)
    assert any("このページから再ダウンロードできます" in message for message in streamlit_stub.infos)
    assert any("このページのURLは第三者と共有しないでください" in message for message in streamlit_stub.infos)


def test_regular_too_many_files_does_not_normalize(monkeypatch):
    calls = []
    files = [uploaded(f"palm_{index}.jpg") for index in range(app.MAX_IMAGE_FILES + 1)]
    streamlit_stub = StreamlitStub(files)
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "normalize_uploaded_images", lambda files: calls.append("normalize"))

    app.render_fortune_form(
        {"purchase_id": "p_test", "payment_status": "paid", "used_flag": False},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert "normalize" not in calls
    assert streamlit_stub.buttons[-1]["disabled"] is True


def test_review_too_many_files_does_not_normalize(monkeypatch):
    calls = []
    files = [uploaded(f"palm_{index}.jpg") for index in range(app.MAX_IMAGE_FILES + 1)]
    streamlit_stub = StreamlitStub(files, uploaded_pdf=uploaded_pdf())
    patch_common(monkeypatch, streamlit_stub, calls)
    monkeypatch.setattr(app, "normalize_uploaded_images", lambda files: calls.append("normalize"))

    app.render_review_fortune_form(
        {"purchase_id": "p_review", "payment_status": "paid", "used_flag": False, "product_type": app.PRODUCT_TYPE_REVIEW},
        SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert "normalize" not in calls
    assert streamlit_stub.buttons[-1]["disabled"] is True


def test_build_image_parts_uses_normalized_jpeg_bytes(monkeypatch):
    captured = {}

    class FakePart:
        @staticmethod
        def from_bytes(**kwargs):
            captured.update(kwargs)
            return kwargs

    from services import fortune_service

    monkeypatch.setattr(fortune_service.types, "Part", FakePart)
    result = fortune_service.build_image_parts(
        [SimpleNamespace(jpeg_bytes=b"jpeg", mime_type="image/jpeg", original_name="palm.heic")]
    )

    assert result == [{"data": b"jpeg", "mime_type": "image/jpeg"}]
    assert captured == {"data": b"jpeg", "mime_type": "image/jpeg"}


def test_call_gemini_fortune_sends_image_parts(monkeypatch):
    captured = {}

    class FakeModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                text=(
                    '{"miko_intro":"a","method_summary":"b","palm_details":"c",'
                    '"name_reading":"d","shichusuimei":"e","western_astrology":"f",'
                    '"fortune_3months":"g","fortune_1year":"h","fortune_3years":"i",'
                    '"advice":{"item":"j","spot":"k","color":"l","luck_action":"m"},'
                    '"cautions":["n","o"],"miko_closing":"p"}'
                )
            )

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(fortune_service, "get_gemini_api_key", lambda: "dummy")
    monkeypatch.setattr(fortune_service, "get_gemini_client", lambda api_key: FakeClient())
    image_part = SimpleNamespace(inline_data=SimpleNamespace(data=b"jpeg", mime_type="image/jpeg"), function_call=None)
    payload = FortuneInput(
        user_name="山田太郎",
        birth_date=date(2000, 1, 1),
        birth_place="東京都",
        categories=["総合運"],
        concern_detail="近況メモ",
        birth_time_accuracy="不明",
        birth_time_text="不明",
        image_parts=[image_part],
        image_meta=[PalmImageMeta(filename="palm.heic", hand_side="左手")],
        image_count=1,
    )

    fortune_service.call_gemini_fortune(payload)

    assert captured["contents"][1] is image_part


def test_hand_side_preview_does_not_fallback_to_raw_uploaded_bytes(monkeypatch):
    from ui import components

    streamlit_stub = StreamlitStub([])
    monkeypatch.setattr(components, "st", streamlit_stub)
    raw_uploaded = SimpleNamespace(name="raw.jpg", getvalue=lambda: b"raw")

    selections = components.build_selected_hand_sides([raw_uploaded])

    assert selections == ["左手"]
    assert streamlit_stub.images == []
    assert streamlit_stub.warnings
