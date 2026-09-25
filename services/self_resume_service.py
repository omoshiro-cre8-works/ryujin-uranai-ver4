from __future__ import annotations

import urllib.parse


VALID_SELF_RESUME_PRODUCT_TYPES = frozenset({"regular", "review"})


def normalize_product_type(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in VALID_SELF_RESUME_PRODUCT_TYPES:
        return normalized
    return "regular"


def build_self_resume_url(
    app_base_url: str,
    purchase_id: str,
    access_token: str,
    product_type: str,
) -> str:
    query_params = {
        "purchase_id": purchase_id,
        "product_type": normalize_product_type(product_type),
        "action": "resume",
    }
    fragment_params = {"access_token": access_token}
    return (
        f"{app_base_url.rstrip('/')}/?{urllib.parse.urlencode(query_params)}"
        f"#{urllib.parse.urlencode(fragment_params)}"
    )
