from __future__ import annotations

import argparse
import ctypes
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO
from urllib.parse import urlsplit

from ctypes import wintypes

from google.cloud import firestore


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services.firestore_service import (  # noqa: E402
    TOKEN_RESCUE_ELIGIBLE,
    get_purchase_by_id,
    get_purchase_token_rescue_status,
    is_purchase_token_rescue_window_active,
    reissue_purchase_access_token_transaction,
)
from services.self_resume_service import build_self_resume_url  # noqa: E402


PRODUCTION_APP_ORIGIN = "https://ai-uranai-h1-155905710900.asia-northeast2.run.app"
PRODUCTION_PROJECT_ID = "gen-lang-client-0636169164"
PRODUCTION_DATABASE_ID = "(default)"
PRODUCTION_COLLECTION = "purchases"
STAGING_APP_ORIGIN = "https://ai-uranai-h1-staging-155905710900.asia-northeast2.run.app"
STAGING_PROJECT_ID = "gen-lang-client-0636169164"
STAGING_DATABASE_ID = "ryujin-staging"
STAGING_COLLECTION = "purchases"
REQUIRED_TARGET_ENV_KEYS = (
    "APP_ENV",
    "FIRESTORE_PROJECT_ID",
    "FIRESTORE_DATABASE_ID",
    "FIRESTORE_PURCHASES_COLLECTION",
    "APP_BASE_URL",
    "ADMIN_RESCUE_CANONICAL_APP_ORIGIN",
)
PROJECT_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
DATABASE_ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{2,61}[a-z0-9]")
COLLECTION_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,127}")


class RescueTargetConfigError(ValueError):
    pass


class ClipboardUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class RescueTarget:
    app_env: str
    project_id: str
    database_id: str
    collection_name: str
    app_origin: str

    @property
    def confirmation(self) -> str:
        return (
            f"{self.app_env}:{self.project_id}/{self.database_id}/"
            f"{self.collection_name}@{self.app_origin}"
        )


def _required_value(source: Mapping[str, str], key: str) -> str:
    value = str(source.get(key, "")).strip()
    if not value:
        raise RescueTargetConfigError(f"missing_{key.lower()}")
    return value


def _parse_https_origin(value: str, field_name: str) -> str:
    if "?" in value or "#" in value:
        raise RescueTargetConfigError(f"invalid_{field_name.lower()}")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise RescueTargetConfigError(f"invalid_{field_name.lower()}") from exc
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise RescueTargetConfigError(f"invalid_{field_name.lower()}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RescueTargetConfigError(f"invalid_{field_name.lower()}")
    if parsed.path not in {"", "/"}:
        raise RescueTargetConfigError(f"invalid_{field_name.lower()}")

    host = parsed.hostname.lower()
    return f"https://{host}:{port}" if port is not None else f"https://{host}"


def load_rescue_target(env: Mapping[str, str] | None = None) -> RescueTarget:
    source = os.environ if env is None else env
    values = {key: _required_value(source, key) for key in REQUIRED_TARGET_ENV_KEYS}
    app_env = values["APP_ENV"].lower()
    if app_env not in {"staging", "production"}:
        raise RescueTargetConfigError("invalid_app_env")

    project_id = values["FIRESTORE_PROJECT_ID"]
    database_id = values["FIRESTORE_DATABASE_ID"]
    collection_name = values["FIRESTORE_PURCHASES_COLLECTION"]
    if PROJECT_ID_PATTERN.fullmatch(project_id) is None:
        raise RescueTargetConfigError("invalid_firestore_project_id")
    if database_id != PRODUCTION_DATABASE_ID and DATABASE_ID_PATTERN.fullmatch(database_id) is None:
        raise RescueTargetConfigError("invalid_firestore_database_id")
    if COLLECTION_PATTERN.fullmatch(collection_name) is None:
        raise RescueTargetConfigError("invalid_firestore_purchases_collection")

    app_origin = _parse_https_origin(values["APP_BASE_URL"], "app_base_url")
    expected_origin = _parse_https_origin(
        values["ADMIN_RESCUE_CANONICAL_APP_ORIGIN"],
        "admin_rescue_canonical_app_origin",
    )
    if app_origin != expected_origin:
        raise RescueTargetConfigError("app_origin_mismatch")

    target = RescueTarget(
        app_env=app_env,
        project_id=project_id,
        database_id=database_id,
        collection_name=collection_name,
        app_origin=app_origin,
    )
    production_tuple = (
        PRODUCTION_PROJECT_ID,
        PRODUCTION_DATABASE_ID,
        PRODUCTION_COLLECTION,
    )
    staging_tuple = (
        STAGING_PROJECT_ID,
        STAGING_DATABASE_ID,
        STAGING_COLLECTION,
    )
    target_tuple = (target.project_id, target.database_id, target.collection_name)
    if app_env == "production":
        if target.app_origin != PRODUCTION_APP_ORIGIN or target_tuple != production_tuple:
            raise RescueTargetConfigError("production_target_mismatch")
    else:
        if target.app_origin != STAGING_APP_ORIGIN or target_tuple != staging_tuple:
            raise RescueTargetConfigError("staging_target_mismatch")
    return target


def create_target_firestore_client(target: RescueTarget) -> firestore.Client:
    return firestore.Client(project=target.project_id, database=target.database_id)


def close_target_firestore_client(db: Any) -> None:
    """Close both public client resources and the SDK's initialized gRPC transport."""
    close = getattr(db, "close", None)
    transport = getattr(db, "_transport", None)
    try:
        if callable(close):
            close()
    finally:
        transport_close = getattr(transport, "close", None)
        if callable(transport_close):
            transport_close()


def _windows_clipboard_apis() -> tuple[Any, Any]:
    if sys.platform != "win32":
        raise ClipboardUnavailableError("windows_clipboard_required")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    return user32, kernel32


def _open_windows_clipboard(user32: Any) -> None:
    for _ in range(10):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise ClipboardUnavailableError("clipboard_open_failed")


def preflight_windows_clipboard() -> None:
    user32, _ = _windows_clipboard_apis()
    _open_windows_clipboard(user32)
    if not user32.CloseClipboard():
        raise ClipboardUnavailableError("clipboard_close_failed")


def copy_text_to_windows_clipboard(value: str) -> None:
    if not value:
        raise ClipboardUnavailableError("clipboard_value_empty")

    user32, kernel32 = _windows_clipboard_apis()
    encoded = (value + "\0").encode("utf-16-le")
    memory_handle = kernel32.GlobalAlloc(0x0002, len(encoded))
    if not memory_handle:
        raise ClipboardUnavailableError("clipboard_allocation_failed")

    ownership_transferred = False
    clipboard_open = False
    try:
        memory_pointer = kernel32.GlobalLock(memory_handle)
        if not memory_pointer:
            raise ClipboardUnavailableError("clipboard_lock_failed")
        try:
            ctypes.memmove(memory_pointer, encoded, len(encoded))
        finally:
            kernel32.GlobalUnlock(memory_handle)

        _open_windows_clipboard(user32)
        clipboard_open = True
        if not user32.EmptyClipboard():
            raise ClipboardUnavailableError("clipboard_empty_failed")
        if not user32.SetClipboardData(13, memory_handle):
            raise ClipboardUnavailableError("clipboard_set_failed")
        ownership_transferred = True
    finally:
        if clipboard_open:
            user32.CloseClipboard()
        if not ownership_transferred:
            kernel32.GlobalFree(memory_handle)


def print_target(target: RescueTarget, stream: TextIO) -> None:
    print(f"Environment: {target.app_env}", file=stream)
    print(f"Project: {target.project_id}", file=stream)
    print(f"Database: {target.database_id}", file=stream)
    print(f"Collection: {target.collection_name}", file=stream)
    print(f"App origin: {target.app_origin}", file=stream)
    print(f"Target confirmation: {target.confirmation}", file=stream)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="既存purchaseのself-resume access tokenを安全に再発行します。",
    )
    parser.add_argument("purchase_id", help="救済対象のpurchase ID")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Firestoreへ新しいaccess_token_hashを書き込みます。省略時はdry-runです。",
    )
    parser.add_argument(
        "--confirm-purchase-id",
        help="--apply時の確認用にpurchase IDを再入力します。",
    )
    parser.add_argument(
        "--confirm-target",
        help="--apply時の接続先確認文字列です。dry-runで確認した値を指定します。",
    )
    parser.add_argument(
        "--copy-url-to-clipboard",
        action="store_true",
        help="--apply時に必須。成功時にself-resume URLをWindowsクリップボードへコピーします。",
    )
    return parser


def _dry_run_lines(purchase: dict[str, Any] | None, status: str) -> list[str]:
    return [
        f"purchase_exists={purchase is not None}",
        f"payment_status={purchase.get('payment_status') if purchase else 'unavailable'}",
        f"used_flag={purchase.get('used_flag') if purchase else 'unavailable'}",
        f"generation_processing={purchase.get('generation_processing') if purchase else 'unavailable'}",
        f"product_type={purchase.get('product_type') if purchase else 'unavailable'}",
        f"checkout_completed_at_present={bool(purchase and purchase.get('checkout_completed_at'))}",
        f"self_resume_within_window={is_purchase_token_rescue_window_active(purchase)}",
        f"Purchase eligibility: {status}",
    ]


def run(
    args: argparse.Namespace,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    try:
        target = load_rescue_target()
    except RescueTargetConfigError as exc:
        print(f"error={exc}", file=stderr)
        return 2

    target_stream = stderr if args.apply else stdout
    print_target(target, target_stream)

    if args.apply and args.confirm_purchase_id != args.purchase_id:
        print("error=confirm_purchase_id_mismatch", file=stderr)
        return 2
    if args.apply and args.confirm_target != target.confirmation:
        print("error=confirm_target_mismatch", file=stderr)
        return 2
    copy_url_to_clipboard = bool(getattr(args, "copy_url_to_clipboard", False))
    if args.apply and not copy_url_to_clipboard:
        print("error=copy_url_to_clipboard_required", file=stderr)
        return 2
    if copy_url_to_clipboard and not args.apply:
        print("error=copy_url_to_clipboard_requires_apply", file=stderr)
        return 2

    db = create_target_firestore_client(target)
    try:
        purchase = get_purchase_by_id(
            args.purchase_id,
            db=db,
            collection_name=target.collection_name,
        )
        status = get_purchase_token_rescue_status(purchase)

        if not args.apply:
            for line in ("mode=dry-run", *_dry_run_lines(purchase, status)):
                print(line, file=stdout)
            return 0 if status == TOKEN_RESCUE_ELIGIBLE else 1

        if status != TOKEN_RESCUE_ELIGIBLE:
            print(f"error={status}", file=stderr)
            return 1

        try:
            current_target = load_rescue_target()
        except RescueTargetConfigError:
            print("error=target_config_changed", file=stderr)
            return 2
        if current_target != target:
            print("error=target_config_changed", file=stderr)
            return 2

        try:
            preflight_windows_clipboard()
        except ClipboardUnavailableError:
            print("error=clipboard_preflight_failed", file=stderr)
            return 2

        new_access_token = secrets.token_urlsafe(24)
        write_status = reissue_purchase_access_token_transaction(
            args.purchase_id,
            new_access_token,
            db=db,
            collection_name=target.collection_name,
        )
        if write_status != TOKEN_RESCUE_ELIGIBLE:
            print(f"error={write_status}", file=stderr)
            return 1

        resume_url = build_self_resume_url(
            target.app_origin,
            args.purchase_id,
            new_access_token,
            str(purchase["product_type"]),
        )
        try:
            copy_text_to_windows_clipboard(resume_url)
        except ClipboardUnavailableError:
            print("error=clipboard_copy_failed_after_write", file=stderr)
            return 3
        print("SELF_RESUME_URL_COPIED=true", file=stdout)
        return 0
    finally:
        close_target_firestore_client(db)


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
