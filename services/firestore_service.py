from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from google.cloud import firestore


COLLECTION_NAME = "purchases"


def _now_utc() -> datetime:
    """UTC の現在時刻を返す。"""
    return datetime.now(timezone.utc)


def get_firestore_client() -> firestore.Client:
    """
    Firestore クライアントを返す。

    Cloud Run 上では Application Default Credentials (ADC) を使って
    認証される想定。
    """
    return firestore.Client()


def hash_access_token(access_token: str) -> str:
    """access token の SHA-256 hash を返す。"""
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def create_purchase_record(
    purchase_id: str,
    stripe_checkout_session_id: str,
    access_token: str,
    token_expires_at: datetime,
    product_type: str = "regular",
    price_type: Optional[str] = None,
    price_id: Optional[str] = None,
    amount_jpy: int = 300,
    currency: str = "jpy",
    source: str = "wix_lp",
) -> str:
    """
    購入レコードを新規作成する。

    Args:
        purchase_id: アプリ側で管理する購入ID
        stripe_checkout_session_id: Stripe Checkout Session ID
        access_token: 決済後アクセス用トークン（Firestore には hash のみ保存）
        token_expires_at: トークン有効期限（UTC datetime）
        product_type: 商品種別（regular / review）
        price_type: 価格種別（regular_campaign / review_regular など）
        price_id: Stripe Price ID
        amount_jpy: 金額（既定 300）
        currency: 通貨（既定 jpy）
        source: 流入元や購入元の識別子

    Returns:
        作成した purchase_id
    """
    db = get_firestore_client()
    doc_ref = db.collection(COLLECTION_NAME).document(purchase_id)

    now = _now_utc()

    payload: Dict[str, Any] = {
        "purchase_id": purchase_id,
        "stripe_checkout_session_id": stripe_checkout_session_id,
        "stripe_event_id": None,
        "payment_status": "pending",
        "used_flag": False,
        "used_at": None,
        "access_token_hash": hash_access_token(access_token),
        "token_expires_at": token_expires_at,
        "product_type": product_type if product_type in {"regular", "review"} else "regular",
        "price_type": price_type,
        "price_id": price_id,
        "amount_jpy": amount_jpy,
        "currency": currency,
        "source": source,
        "created_at": now,
        "updated_at": now,
    }

    doc_ref.set(payload)
    return purchase_id


def get_purchase_by_id(purchase_id: str) -> Optional[Dict[str, Any]]:
    """
    purchase_id で購入レコードを取得する。
    """
    db = get_firestore_client()
    doc_ref = db.collection(COLLECTION_NAME).document(purchase_id)
    snapshot = doc_ref.get()

    if not snapshot.exists:
        return None

    data = snapshot.to_dict()
    return data


def get_purchase_by_access_token(access_token: str) -> Optional[Dict[str, Any]]:
    """
    access_token で購入レコードを1件取得する。

    新形式の access_token_hash を優先し、既存レコードとの後方互換のため
    旧 access_token フィールドも照合する。
    """
    db = get_firestore_client()
    access_token_hash = hash_access_token(access_token)

    hash_query = (
        db.collection(COLLECTION_NAME)
        .where("access_token_hash", "==", access_token_hash)
        .limit(1)
    )
    hash_docs = list(hash_query.stream())
    if hash_docs:
        data = hash_docs[0].to_dict() or {}
        stored_hash = data.get("access_token_hash")
        if isinstance(stored_hash, str) and hmac.compare_digest(stored_hash, access_token_hash):
            return data

    legacy_query = (
        db.collection(COLLECTION_NAME)
        .where("access_token", "==", access_token)
        .limit(1)
    )
    legacy_docs = list(legacy_query.stream())
    if legacy_docs:
        data = legacy_docs[0].to_dict() or {}
        stored_token = data.get("access_token")
        if isinstance(stored_token, str) and hmac.compare_digest(stored_token, access_token):
            data.pop("access_token", None)
            return data

    return None


def mark_purchase_paid(
    purchase_id: str,
    stripe_event_id: Optional[str] = None,
) -> None:
    """
    購入レコードを paid 状態に更新する。
    """
    db = get_firestore_client()
    doc_ref = db.collection(COLLECTION_NAME).document(purchase_id)

    update_data: Dict[str, Any] = {
        "payment_status": "paid",
        "updated_at": _now_utc(),
    }

    if stripe_event_id:
        update_data["stripe_event_id"] = stripe_event_id

    doc_ref.update(update_data)


def mark_purchase_cancelled(purchase_id: str) -> None:
    """
    購入レコードを cancelled 状態に更新する。
    """
    db = get_firestore_client()
    doc_ref = db.collection(COLLECTION_NAME).document(purchase_id)

    doc_ref.update(
        {
            "payment_status": "cancelled",
            "updated_at": _now_utc(),
        }
    )


def mark_purchase_used(purchase_id: str) -> None:
    """
    購入レコードを利用済みに更新する。
    """
    db = get_firestore_client()
    doc_ref = db.collection(COLLECTION_NAME).document(purchase_id)

    doc_ref.update(
        {
            "used_flag": True,
            "used_at": _now_utc(),
            "updated_at": _now_utc(),
        }
    )


def is_purchase_usable(access_token: str) -> bool:
    """
    access_token から購入レコードを確認し、
    利用可能かどうかを返す。

    利用可能条件:
    - レコードが存在する
    - payment_status が paid
    - used_flag が False
    - token_expires_at が現在時刻より後
    """
    purchase = get_purchase_by_access_token(access_token)
    if not purchase:
        return False

    if purchase.get("payment_status") != "paid":
        return False

    if purchase.get("used_flag") is True:
        return False

    expires_at = purchase.get("token_expires_at")
    if not expires_at:
        return False

    now = _now_utc()

    # Firestore Timestamp でも datetime でも比較できるように吸収
    if hasattr(expires_at, "replace"):
        try:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except Exception:
            return False

    return expires_at > now
