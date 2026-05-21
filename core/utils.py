"""Shared normalization and file helpers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from pathlib import Path

import pandas as pd


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    if "$" not in stored_hash:
        return False
    salt, digest_hex = stored_hash.split("$", 1)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return secrets.compare_digest(digest.hex(), digest_hex)


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def normalize_key(value: object) -> str:
    return normalize_text(value).lower()


def normalize_dg_case(value: object) -> str:
    text = normalize_text(value).upper().replace(" ", "")
    if not text:
        return ""
    if text.startswith("0-"):
        text = "O-" + text[2:]
    return text


def looks_like_dg_case(value: object) -> bool:
    text = normalize_dg_case(value)
    if not text:
        return False
    return "-" in text and any(ch.isdigit() for ch in text)


def compute_file_signature(file_path: str) -> str:
    st = Path(file_path).stat()
    return f"stat:{st.st_size}:{st.st_mtime_ns}"


def hash_text(value: object) -> str:
    text = normalize_text(value)
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def compute_file_md5(file_path: str) -> str:
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            md5.update(chunk)
    return md5.hexdigest()


def parse_date_dd_mm_yyyy(value: object) -> datetime | None:
    text = normalize_text(value)
    if not text:
        return None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        ts = pd.to_datetime(value, dayfirst=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def format_date_dd_mm_yyyy(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y")
    parsed = parse_date_dd_mm_yyyy(value)
    return parsed.strftime("%d-%m-%Y") if parsed else normalize_text(value)


def extract_customer_code_from_product_code(product_code: object) -> str:
    text = normalize_text(product_code)
    if not text:
        return ""
    parts = [p.strip() for p in text.split(".") if p.strip()]
    if len(parts) >= 2:
        return parts[1]
    return ""


def extract_item_code_from_product_code(product_code: object) -> str:
    text = normalize_text(product_code)
    if not text:
        return ""
    parts = [p.strip() for p in text.split(".") if p.strip()]
    if len(parts) >= 3:
        return parts[2]
    return ""
