"""Lưu / tải team_datasets — gzip + chunk (bảng kê lớn)."""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
from typing import Any

from core.supabase_config import database_configured, get_database_url
from core.utils import normalize_text

CHUNK_SIZE = 2500
STORAGE_EXCEL_GZIP = "excel_gzip"
MAX_EXCEL_BYTES = 30 * 1024 * 1024  # file .xlsx gốc trước khi gzip


def _bytea_for_rest(blob: bytes) -> str:
    return "\\x" + blob.hex()


def _bytea_from_rest(value: object) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    text = str(value).strip()
    if text.startswith("\\x"):
        return bytes.fromhex(text[2:])
    try:
        return base64.b64decode(text)
    except Exception:
        return None
# REST: chỉ inline khi gzip nhỏ; bảng kê lớn luôn chunked
INLINE_MAX_GZIP_BYTES = 400_000


def records_to_gzip(records: list[dict]) -> bytes:
    raw = json.dumps(records, ensure_ascii=False, default=str).encode("utf-8")
    return gzip.compress(raw, compresslevel=6)


def gzip_to_records(blob: bytes) -> list[dict]:
    raw = gzip.decompress(blob)
    data = json.loads(raw.decode("utf-8"))
    return list(data) if isinstance(data, list) else []


def split_chunks(records: list[dict], size: int = CHUNK_SIZE) -> list[list[dict]]:
    if not records:
        return [[]]
    return [records[i : i + size] for i in range(0, len(records), size)]


def format_cloud_error(exc: Exception) -> str:
    text = str(exc)
    if "520" in text or "521" in text or "525" in text or "cloudflare" in text.lower():
        return (
            "Supabase/Cloudflare tạm lỗi hoặc dữ liệu quá lớn. "
            "Thử lại sau vài phút; admin có thể dùng DATABASE_URL (Postgres trực tiếp)."
        )
    if "payload" in text.lower() or "too large" in text.lower():
        return "Dữ liệu quá lớn để gửi một lần — hệ thống sẽ chia chunk (cập nhật app)."
    if len(text) > 240:
        return text[:240] + "…"
    return text or "Lỗi cloud không xác định."


class TeamDatasetStore:
    """Publish/pull qua Postgres (ưu tiên) hoặc Supabase REST."""

    def __init__(self, owner_id: str, get_client) -> None:
        self.owner_id = normalize_text(owner_id)
        self._get_client = get_client

    def publish(
        self,
        *,
        dataset_type: str,
        publisher_name: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        content_hash: str,
        row_count: int,
        meta: dict,
        records: list[dict],
    ) -> str:
        gz = records_to_gzip(records)
        use_chunks = len(gz) > INLINE_MAX_GZIP_BYTES or len(records) > CHUNK_SIZE
        if database_configured():
            return self._publish_postgres(
                dataset_type=dataset_type,
                publisher_name=publisher_name,
                file_name=file_name,
                file_path=file_path,
                file_hash=file_hash,
                content_hash=content_hash,
                row_count=row_count,
                meta=meta,
                records=records,
                use_chunks=use_chunks,
            )
        return self._publish_rest(
            dataset_type=dataset_type,
            publisher_name=publisher_name,
            file_name=file_name,
            file_path=file_path,
            file_hash=file_hash,
            content_hash=content_hash,
            row_count=row_count,
            meta=meta,
            records=records,
            use_chunks=use_chunks,
        )

    def fetch_records(self, dataset_type: str) -> tuple[dict[str, Any], list[dict]]:
        if database_configured():
            row = self._fetch_header_postgres(dataset_type)
            if not row:
                return {}, []
            records = self._fetch_records_postgres(str(row["id"]), str(row.get("storage_format", "inline")))
            return row, records
        row = self._fetch_header_rest(dataset_type)
        if not row:
            return {}, []
        records = self._fetch_records_rest(row)
        return row, records

    def fetch_header(self, dataset_type: str) -> dict[str, Any] | None:
        if database_configured():
            return self._fetch_header_postgres(dataset_type)
        return self._fetch_header_rest(dataset_type)

    def publish_excel_file(
        self,
        *,
        dataset_type: str,
        publisher_name: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        content_hash: str,
        row_count: int,
        meta: dict,
        excel_path: str,
    ) -> str:
        """Chia sẻ file Excel gốc (gzip) — tối ưu bảng kê nhiều dòng."""
        path = Path(excel_path)
        if not path.is_file():
            raise FileNotFoundError(f"Không tìm thấy file: {excel_path}")
        raw = path.read_bytes()
        if len(raw) > MAX_EXCEL_BYTES:
            raise ValueError(
                f"File Excel quá lớn ({len(raw) // (1024 * 1024)} MB). "
                f"Giới hạn {MAX_EXCEL_BYTES // (1024 * 1024)} MB."
            )
        file_gzip = gzip.compress(raw, compresslevel=6)
        meta = dict(meta)
        meta["excel_size_bytes"] = len(raw)
        meta["excel_gzip_bytes"] = len(file_gzip)

        if database_configured():
            return self._publish_excel_postgres(
                dataset_type=dataset_type,
                publisher_name=publisher_name,
                file_name=file_name,
                file_path=file_path,
                file_hash=file_hash,
                content_hash=content_hash,
                row_count=row_count,
                meta=meta,
                file_gzip=file_gzip,
            )
        return self._publish_excel_rest(
            dataset_type=dataset_type,
            publisher_name=publisher_name,
            file_name=file_name,
            file_path=file_path,
            file_hash=file_hash,
            content_hash=content_hash,
            row_count=row_count,
            meta=meta,
            file_gzip=file_gzip,
        )

    def fetch_excel_bytes(self, dataset_type: str) -> tuple[dict[str, Any], bytes]:
        header = self.fetch_header(dataset_type)
        if not header:
            return {}, b""
        if str(header.get("storage_format")) != STORAGE_EXCEL_GZIP:
            return header, b""
        if database_configured():
            blob = self._fetch_excel_postgres(str(header["id"]))
        else:
            blob = self._fetch_excel_rest(str(header["id"]))
        if not blob:
            return header, b""
        return header, gzip.decompress(blob)

    # --- Postgres ---

    def _publish_postgres(
        self,
        *,
        dataset_type: str,
        publisher_name: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        content_hash: str,
        row_count: int,
        meta: dict,
        records: list[dict],
        use_chunks: bool,
    ) -> str:
        import psycopg
        from psycopg.types.json import Jsonb

        url = get_database_url()
        meta_json = Jsonb(meta)
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(
                """
                UPDATE public.team_datasets
                SET is_active = FALSE
                WHERE dataset_type = %s AND is_active = TRUE
                """,
                (dataset_type,),
            )
            row = conn.execute(
                """
                INSERT INTO public.team_datasets(
                    dataset_type, publisher_id, publisher_name,
                    file_name, file_path, file_hash, content_hash,
                    row_count, meta, rows_data, storage_format, is_active
                )
                VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, %s, TRUE)
                RETURNING id
                """,
                (
                    dataset_type,
                    self.owner_id,
                    publisher_name,
                    file_name,
                    file_path,
                    file_hash,
                    content_hash or file_hash,
                    row_count,
                    meta_json,
                    "chunked" if use_chunks else "inline",
                ),
            ).fetchone()
            dataset_id = str(row[0])
            if use_chunks:
                for idx, part in enumerate(split_chunks(records)):
                    conn.execute(
                        """
                        INSERT INTO public.team_dataset_chunks(
                            dataset_id, chunk_index, row_count, payload_gzip
                        )
                        VALUES (%s::uuid, %s, %s, %s)
                        """,
                        (dataset_id, idx, len(part), records_to_gzip(part)),
                    )
            else:
                conn.execute(
                    """
                    UPDATE public.team_datasets
                    SET rows_data = %s::jsonb
                    WHERE id = %s::uuid
                    """,
                    (Jsonb(records), dataset_id),
                )
        return dataset_id

    def _fetch_header_postgres(self, dataset_type: str) -> dict[str, Any] | None:
        import psycopg

        with psycopg.connect(get_database_url()) as conn:
            row = conn.execute(
                """
                SELECT id, dataset_type, publisher_name, file_name, file_path,
                       file_hash, content_hash, row_count, meta, published_at, storage_format
                FROM public.team_datasets
                WHERE dataset_type = %s AND is_active = TRUE
                ORDER BY published_at DESC
                LIMIT 1
                """,
                (dataset_type,),
            ).fetchone()
        if not row:
            return None
        cols = [
            "id",
            "dataset_type",
            "publisher_name",
            "file_name",
            "file_path",
            "file_hash",
            "content_hash",
            "row_count",
            "meta",
            "published_at",
            "storage_format",
        ]
        out = dict(zip(cols, row))
        if hasattr(out.get("published_at"), "isoformat"):
            out["published_at"] = out["published_at"].isoformat()
        return out

    def _fetch_records_postgres(self, dataset_id: str, storage_format: str) -> list[dict]:
        import psycopg

        with psycopg.connect(get_database_url()) as conn:
            if storage_format == "chunked":
                rows = conn.execute(
                    """
                    SELECT payload_gzip FROM public.team_dataset_chunks
                    WHERE dataset_id = %s::uuid
                    ORDER BY chunk_index ASC
                    """,
                    (dataset_id,),
                ).fetchall()
                merged: list[dict] = []
                for (blob,) in rows:
                    merged.extend(gzip_to_records(bytes(blob)))
                return merged
            row = conn.execute(
                "SELECT rows_data FROM public.team_datasets WHERE id = %s::uuid",
                (dataset_id,),
            ).fetchone()
        if not row or not row[0]:
            return []
        data = row[0]
        if isinstance(data, str):
            data = json.loads(data)
        return list(data) if isinstance(data, list) else []

    def _publish_excel_postgres(
        self,
        *,
        dataset_type: str,
        publisher_name: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        content_hash: str,
        row_count: int,
        meta: dict,
        file_gzip: bytes,
    ) -> str:
        import psycopg
        from psycopg.types.json import Jsonb

        with psycopg.connect(get_database_url(), autocommit=True) as conn:
            conn.execute(
                """
                UPDATE public.team_datasets
                SET is_active = FALSE
                WHERE dataset_type = %s AND is_active = TRUE
                """,
                (dataset_type,),
            )
            row = conn.execute(
                """
                INSERT INTO public.team_datasets(
                    dataset_type, publisher_id, publisher_name,
                    file_name, file_path, file_hash, content_hash,
                    row_count, meta, rows_data, storage_format, file_gzip, is_active
                )
                VALUES (%s, %s::uuid, %s, %s, %s, %s, %s, %s, %s, '[]'::jsonb, %s, %s, TRUE)
                RETURNING id
                """,
                (
                    dataset_type,
                    self.owner_id,
                    publisher_name,
                    file_name,
                    file_path,
                    file_hash,
                    content_hash or file_hash,
                    row_count,
                    Jsonb(meta),
                    STORAGE_EXCEL_GZIP,
                    file_gzip,
                ),
            ).fetchone()
        return str(row[0])

    def _fetch_excel_postgres(self, dataset_id: str) -> bytes:
        import psycopg

        with psycopg.connect(get_database_url()) as conn:
            row = conn.execute(
                "SELECT file_gzip FROM public.team_datasets WHERE id = %s::uuid",
                (dataset_id,),
            ).fetchone()
        if not row or not row[0]:
            return b""
        return bytes(row[0])

    # --- REST ---

    def _publish_rest(
        self,
        *,
        dataset_type: str,
        publisher_name: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        content_hash: str,
        row_count: int,
        meta: dict,
        records: list[dict],
        use_chunks: bool,
    ) -> str:
        client = self._get_client()
        client.table("team_datasets").update({"is_active": False}).eq(
            "dataset_type", dataset_type
        ).eq("is_active", True).execute()

        header = {
            "dataset_type": dataset_type,
            "publisher_id": self.owner_id,
            "publisher_name": publisher_name,
            "file_name": file_name,
            "file_path": file_path,
            "file_hash": file_hash,
            "content_hash": content_hash or file_hash,
            "row_count": row_count,
            "meta": meta,
            "rows_data": [] if use_chunks else records,
            "storage_format": "chunked" if use_chunks else "inline",
            "is_active": True,
        }
        resp = client.table("team_datasets").insert(header).execute()
        rows = resp.data or []
        if not rows:
            raise RuntimeError("Không tạo được bản ghi team_datasets trên cloud.")
        dataset_id = str(rows[0]["id"])

        if use_chunks:
            for idx, part in enumerate(split_chunks(records)):
                blob = records_to_gzip(part)
                client.table("team_dataset_chunks").insert(
                    {
                        "dataset_id": dataset_id,
                        "chunk_index": idx,
                        "row_count": len(part),
                        "payload_gzip": _bytea_for_rest(blob),
                    }
                ).execute()
        return dataset_id

    def _publish_excel_rest(
        self,
        *,
        dataset_type: str,
        publisher_name: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        content_hash: str,
        row_count: int,
        meta: dict,
        file_gzip: bytes,
    ) -> str:
        client = self._get_client()
        client.table("team_datasets").update({"is_active": False}).eq(
            "dataset_type", dataset_type
        ).eq("is_active", True).execute()
        header = {
            "dataset_type": dataset_type,
            "publisher_id": self.owner_id,
            "publisher_name": publisher_name,
            "file_name": file_name,
            "file_path": file_path,
            "file_hash": file_hash,
            "content_hash": content_hash or file_hash,
            "row_count": row_count,
            "meta": meta,
            "rows_data": [],
            "storage_format": STORAGE_EXCEL_GZIP,
            "file_gzip": _bytea_for_rest(file_gzip),
            "is_active": True,
        }
        resp = client.table("team_datasets").insert(header).execute()
        rows = resp.data or []
        if not rows:
            raise RuntimeError("Không tạo được bản ghi team_datasets trên cloud.")
        return str(rows[0]["id"])

    def _fetch_excel_rest(self, dataset_id: str) -> bytes:
        client = self._get_client()
        rows = (
            client.table("team_datasets")
            .select("file_gzip")
            .eq("id", dataset_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows:
            return b""
        return _bytea_from_rest(rows[0].get("file_gzip")) or b""

    def _fetch_header_rest(self, dataset_type: str) -> dict[str, Any] | None:
        client = self._get_client()
        rows = (
            client.table("team_datasets")
            .select(
                "id, dataset_type, publisher_name, file_name, file_path, "
                "file_hash, content_hash, row_count, meta, published_at, storage_format"
            )
            .eq("dataset_type", dataset_type)
            .eq("is_active", True)
            .order("published_at", desc=True)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    def _fetch_records_rest(self, header: dict[str, Any]) -> list[dict]:
        client = self._get_client()
        if str(header.get("storage_format")) == "chunked":
            dataset_id = str(header["id"])
            chunks = (
                client.table("team_dataset_chunks")
                .select("chunk_index, payload_gzip")
                .eq("dataset_id", dataset_id)
                .order("chunk_index")
                .execute()
                .data
                or []
            )
            merged: list[dict] = []
            for ch in chunks:
                blob = _bytea_from_rest(ch.get("payload_gzip"))
                if blob:
                    merged.extend(gzip_to_records(blob))
            return merged
        inline = header.get("rows_data") or []
        if isinstance(inline, str):
            inline = json.loads(inline)
        return list(inline) if isinstance(inline, list) else []
