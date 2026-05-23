"""Metadata lần pull dataset team về local."""

from __future__ import annotations

from core.database import HubDatabase
from core.db.dialect import now_iso
from core.utils import normalize_text

SETUP_TEAM_OL_CLOUD_HASH = "team_ol_cloud_hash"
SETUP_TEAM_OL_LAST_PULL = "team_ol_last_pulled_at"
SETUP_TEAM_BOM_CLOUD_HASH = "team_bom_ke_cloud_hash"
SETUP_TEAM_BOM_LAST_PULL = "team_bom_ke_last_pulled_at"


def mark_team_ol_pulled(db: HubDatabase, *, content_hash: str) -> None:
    db.set_setup(SETUP_TEAM_OL_CLOUD_HASH, normalize_text(content_hash))
    db.set_setup(SETUP_TEAM_OL_LAST_PULL, now_iso())


def mark_team_bom_pulled(db: HubDatabase, *, content_hash: str) -> None:
    db.set_setup(SETUP_TEAM_BOM_CLOUD_HASH, normalize_text(content_hash))
    db.set_setup(SETUP_TEAM_BOM_LAST_PULL, now_iso())
