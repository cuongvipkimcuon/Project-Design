"""Trạng thái dữ liệu — cloud (nguồn chính) vs cache local (đọc nhanh)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from core.database import HubDatabase
from core.team_pull_meta import (
    SETUP_TEAM_BOM_CLOUD_HASH,
    SETUP_TEAM_BOM_LAST_PULL,
    SETUP_TEAM_OL_CLOUD_HASH,
    SETUP_TEAM_OL_LAST_PULL,
)
from core.shared_dataset_service import SharedDatasetService, TeamDatasetInfo
from core.supabase_config import supabase_enabled
from core.utils import normalize_text

SyncState = Literal[
    "cloud_off",
    "missing_cloud",
    "missing_local",
    "stale",
    "partial",
    "synced",
    "local_only",
]


@dataclass
class DatasetSide:
    available: bool = False
    row_count: int = 0
    label: str = ""
    at: str = ""
    hash: str = ""
    extra: str = ""
    publisher: str = ""


@dataclass
class DatasetStatus:
    key: str
    title: str
    cloud: DatasetSide = field(default_factory=DatasetSide)
    local: DatasetSide = field(default_factory=DatasetSide)
    sync_state: SyncState = "missing_cloud"
    ready: bool = False
    summary: str = ""
    hint: str = ""


@dataclass
class DataStatusReport:
    cloud_enabled: bool
    ready_for_work: bool
    headline: str
    detail: str
    ol: DatasetStatus
    bom_ke: DatasetStatus
    team_ops_summary: str = ""
    template_summary: str = ""


def _fmt_when(raw: str) -> str:
    text = normalize_text(raw)
    if not text:
        return "—"
    return text[:16].replace("T", " ")


def _cloud_side(info: TeamDatasetInfo | None) -> DatasetSide:
    if not info:
        return DatasetSide(available=False, label="Chưa có trên cloud")
    extra = ""
    if info.dataset_type == "bom_ke":
        meta = info.meta or {}
        gz = meta.get("excel_gzip_bytes")
        if gz:
            extra = f"file gzip ~{int(gz) // 1024} KB"
        elif meta.get("excel_size_bytes"):
            extra = f"file ~{int(meta['excel_size_bytes']) // (1024 * 1024)} MB"
    return DatasetSide(
        available=True,
        row_count=int(info.row_count or 0),
        label=normalize_text(info.file_name) or info.dataset_type,
        at=_fmt_when(info.published_at),
        hash=normalize_text(info.content_hash),
        publisher=normalize_text(info.publisher_name),
        extra=extra,
    )


def _compare_rows(local_rows: int, cloud_rows: int) -> bool:
    """True nếu local đủ so với cloud."""
    if cloud_rows <= 0:
        return local_rows > 0
    if local_rows >= cloud_rows:
        return True
    if cloud_rows >= 1000:
        return local_rows >= int(cloud_rows * 0.98)
    return local_rows >= cloud_rows - 5


def _resolve_sync_state(
    *,
    cloud_enabled: bool,
    cloud: DatasetSide,
    local: DatasetSide,
    stored_hash: str,
) -> tuple[SyncState, bool, str, str]:
    if not cloud_enabled:
        if local.available and local.row_count > 0:
            return (
                "local_only",
                True,
                "Cloud tắt — đang dùng cache local.",
                "Bật Supabase để đồng bộ bản admin.",
            )
        return (
            "cloud_off",
            False,
            "Chưa có dữ liệu local.",
            "Đăng nhập cloud hoặc admin đọc file trong Setup → Tài khoản.",
        )

    if not cloud.available:
        if local.available and local.row_count > 0:
            return (
                "local_only",
                False,
                "Có cache local nhưng admin chưa chia sẻ cloud.",
                "Liên hệ admin đọc & chia sẻ OL/bảng kê.",
            )
        return (
            "missing_cloud",
            False,
            "Admin chưa đẩy dữ liệu lên cloud.",
            "Admin: Setup → đọc file → tự chia sẻ (hoặc Chia sẻ lại).",
        )

    if not local.available or local.row_count <= 0:
        return (
            "missing_local",
            False,
            f"Cloud có {cloud.row_count:,} dòng — chưa tải về máy.",
            "Bấm «Đồng bộ từ admin» để lấy bản mới nhất.",
        )

    hash_ok = bool(stored_hash) and stored_hash == cloud.hash
    rows_ok = _compare_rows(local.row_count, cloud.row_count)

    if hash_ok and rows_ok:
        return (
            "synced",
            True,
            f"Đã khớp cloud ({cloud.row_count:,} dòng).",
            "Làm việc bình thường — cache local chỉ để đọc nhanh.",
        )

    if rows_ok and not hash_ok:
        return (
            "stale",
            False,
            f"Cache local {local.row_count:,} dòng — cloud có bản mới ({cloud.at}).",
            "Nên đồng bộ lại từ admin.",
        )

    if local.row_count < cloud.row_count:
        return (
            "partial",
            False,
            f"Cache thiếu dòng: local {local.row_count:,} / cloud {cloud.row_count:,}.",
            "Đồng bộ lại — tránh match S/O sai (bảng kê cắt cụt).",
        )

    return (
        "stale",
        False,
        "Hash cloud khác cache — có thể admin vừa cập nhật.",
        "Bấm «Đồng bộ từ admin».",
    )


def _local_ol_side(db: HubDatabase) -> DatasetSide:
    dataset_id = db.resolve_active_ol_dataset_id()
    if not dataset_id:
        snap = db.get_snapshot_meta(date.today().strftime("%Y-%m-%d"))
        if snap:
            return DatasetSide(
                available=True,
                row_count=int(snap[5] or 0),
                label=normalize_text(snap[2]).split("\\")[-1].split("/")[-1] or "snapshot",
                at=_fmt_when(str(snap[4])),
            )
        return DatasetSide(available=False, label="Chưa đọc OL")

    meta = db.get_ol_dataset_by_id(int(dataset_id)) or {}
    row_count = db._count_ol_rows(int(dataset_id))
    read_at = db.get_setup("ol_active_read_at", "")
    return DatasetSide(
        available=row_count > 0,
        row_count=row_count,
        label=normalize_text(meta.get("file_name")) or "OL cache",
        at=_fmt_when(read_at or normalize_text(meta.get("imported_at"))),
        hash=normalize_text(meta.get("file_hash")),
    )


def _local_bom_side(db: HubDatabase) -> DatasetSide:
    a6_hash = db.get_setup("bom_ke_a6_hash", "")
    if not a6_hash:
        return DatasetSide(available=False, label="Chưa đọc bảng kê")

    dataset_id = db.resolve_bom_ke_dataset_id(a6_hash)
    meta = db.get_bom_ke_dataset(a6_hash) or {}
    row_count = db._count_bom_ke_rows(int(dataset_id)) if dataset_id else int(meta.get("row_count") or 0)
    a6_text = normalize_text(meta.get("a6_text") or db.get_setup("bom_ke_a6_text", ""))
    short = a6_text[:36] + "…" if len(a6_text) > 36 else a6_text
    return DatasetSide(
        available=row_count > 0,
        row_count=row_count,
        label=normalize_text(meta.get("file_name")) or "Bảng kê cache",
        at=_fmt_when(normalize_text(meta.get("imported_at"))),
        hash=a6_hash,
        extra=f"A6: {short}" if short else "",
    )


def build_data_status(db: HubDatabase, shared: SharedDatasetService | None = None) -> DataStatusReport:
    svc = shared or SharedDatasetService(db)
    cloud_on = supabase_enabled() and svc.cloud_enabled

    ol_cloud = _cloud_side(svc.get_team_info("ol") if cloud_on else None)
    bom_cloud = _cloud_side(svc.get_team_info("bom_ke") if cloud_on else None)
    ol_local = _local_ol_side(db)
    bom_local = _local_bom_side(db)

    ol_state, ol_ready, ol_sum, ol_hint = _resolve_sync_state(
        cloud_enabled=cloud_on,
        cloud=ol_cloud,
        local=ol_local,
        stored_hash=db.get_setup(SETUP_TEAM_OL_CLOUD_HASH, ""),
    )
    bom_state, bom_ready, bom_sum, bom_hint = _resolve_sync_state(
        cloud_enabled=cloud_on,
        cloud=bom_cloud,
        local=bom_local,
        stored_hash=db.get_setup(SETUP_TEAM_BOM_CLOUD_HASH, ""),
    )

    ol_pull = db.get_setup(SETUP_TEAM_OL_LAST_PULL, "")
    bom_pull = db.get_setup(SETUP_TEAM_BOM_LAST_PULL, "")
    if ol_pull:
        ol_local.extra = (ol_local.extra + " · " if ol_local.extra else "") + f"Tải cloud: {_fmt_when(ol_pull)}"
    if bom_pull:
        bom_local.extra = (bom_local.extra + " · " if bom_local.extra else "") + f"Tải cloud: {_fmt_when(bom_pull)}"

    ol = DatasetStatus(
        key="ol",
        title="Order List (OL)",
        cloud=ol_cloud,
        local=ol_local,
        sync_state=ol_state,
        ready=ol_ready,
        summary=ol_sum,
        hint=ol_hint,
    )
    bom = DatasetStatus(
        key="bom_ke",
        title="Bảng kê định mức",
        cloud=bom_cloud,
        local=bom_local,
        sync_state=bom_state,
        ready=bom_ready,
        summary=bom_sum,
        hint=bom_hint,
    )

    ready = ol.ready and bom.ready
    if ready:
        headline = "Sẵn sàng làm việc"
        detail = "OL và bảng kê đã khớp cloud (hoặc cache local đủ dùng)."
    elif not cloud_on:
        headline = "Chế độ local / cloud tắt"
        detail = "Cần OL + bảng kê trong cache local, hoặc bật cloud để đồng bộ admin."
    else:
        headline = "Cần đồng bộ dữ liệu"
        problems = []
        if not ol.ready:
            problems.append("OL")
        if not bom.ready:
            problems.append("bảng kê")
        detail = f"Thiếu hoặc lệch: {', '.join(problems)} — xem gợi ý bên dưới."

    tpl = svc.get_team_info("supplier_template") if cloud_on else None
    if tpl:
        template_summary = f"Template phiếu: ✓ {tpl.file_name} — {_fmt_when(tpl.published_at)}"
    elif cloud_on:
        template_summary = "Template phiếu: chưa có trên cloud"
    else:
        template_summary = "Template phiếu: —"

    try:
        from core.team_ops_sync import get_team_ops_status

        ops = get_team_ops_status(db)
        lv = int(ops.get("local_version") or 0)
        rv = int(ops.get("remote_version") or 0)
        when = _fmt_when(normalize_text(ops.get("synced_at") or ops.get("remote_updated_at")))
        if lv > 0 or ops.get("has_remote"):
            ver = f"v{lv}"
            if rv and rv != lv:
                ver = f"v{lv} (cloud v{rv})"
            team_ops_summary = f"Plan / phiếu / tồn: {ver} — {when}"
        else:
            team_ops_summary = "Plan / phiếu / tồn: chưa đồng bộ (ghi online khi lưu)"
    except Exception:
        team_ops_summary = "Plan / phiếu / tồn: —"

    return DataStatusReport(
        cloud_enabled=cloud_on,
        ready_for_work=ready,
        headline=headline,
        detail=detail,
        ol=ol,
        bom_ke=bom,
        team_ops_summary=team_ops_summary,
        template_summary=template_summary,
    )


SYNC_STATE_LABELS: dict[SyncState, str] = {
    "cloud_off": "Cloud tắt",
    "missing_cloud": "Chưa có cloud",
    "missing_local": "Chưa tải về",
    "stale": "Cần sync lại",
    "partial": "Thiếu dòng",
    "synced": "Đã khớp",
    "local_only": "Chỉ local",
}
