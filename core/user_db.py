"""Tạo HubDatabase scoped theo user + đồng bộ cloud."""

from __future__ import annotations

from core.database import HubDatabase
from core.user_cloud import UserCloud


def create_user_database(
    user_id: str,
    db_file: str | None = None,
    *,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> HubDatabase:
    cloud = UserCloud(user_id, access_token=access_token, refresh_token=refresh_token)
    kwargs: dict = {"owner_id": user_id, "cloud": cloud}
    if db_file:
        kwargs["db_file"] = db_file
    db = HubDatabase(**kwargs)
    if cloud.enabled:
        for key, value in cloud.pull_settings().items():
            db.set_setup(key, value, sync_cloud=False)
    return db
