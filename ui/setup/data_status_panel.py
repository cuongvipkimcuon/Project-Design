"""Setup → Trạng thái dữ liệu — cloud (nguồn chính) vs cache local."""

from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from core.app_state import AppState
from core.auth import AuthService
from core.data_status_service import SYNC_STATE_LABELS, build_data_status
from core.shared_dataset_service import SharedDatasetService
from core.supabase_config import supabase_enabled
from ui.theme import COLORS, FONT_BODY, FONT_SMALL


class SetupDataStatusPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, state: AppState, auth: AuthService, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state
        self.auth = auth
        self.shared = SharedDatasetService(state.db)
        self._is_admin = state.user.role == "admin"
        self._cards: dict[str, ctk.CTkFrame] = {}
        self._build()
        self.state.on_change(self._refresh)
        self._refresh()

    def _section(self, title: str) -> ctk.CTkFrame:
        box = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        box.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(box, text=title, font=("Segoe UI", 15, "bold")).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=(0, 14))
        return inner

    def _build(self) -> None:
        intro = self._section("Trạng thái dữ liệu")
        ctk.CTkLabel(
            intro,
            text=(
                "Nguồn chính: cloud (admin đọc file → chia sẻ). "
                "Cache local chỉ để đọc nhanh — khi làm việc hãy «Đồng bộ từ admin» để khớp bản mới nhất. "
                "Plan / phiếu / tồn ghi online khi lưu."
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=820,
            justify="left",
        ).pack(anchor="w")

        self.banner = ctk.CTkFrame(intro, fg_color=COLORS["bg"], corner_radius=8)
        self.banner.pack(fill="x", pady=(12, 0))
        banner_inner = ctk.CTkFrame(self.banner, fg_color="transparent")
        banner_inner.pack(fill="x", padx=14, pady=12)
        self.headline_label = ctk.CTkLabel(banner_inner, text="—", font=("Segoe UI", 16, "bold"), anchor="w")
        self.headline_label.pack(fill="x")
        self.detail_label = ctk.CTkLabel(
            banner_inner, text="", font=FONT_SMALL, text_color=COLORS["muted"], anchor="w", wraplength=780, justify="left"
        )
        self.detail_label.pack(fill="x", pady=(4, 0))

        actions = ctk.CTkFrame(intro, fg_color="transparent")
        actions.pack(fill="x", pady=(12, 0))
        ctk.CTkButton(actions, text="Làm mới", width=90, command=self._refresh).pack(side="left")
        ctk.CTkButton(
            actions,
            text="Đồng bộ tất cả từ admin",
            width=180,
            fg_color=COLORS["accent"][1],
            command=self._pull_all,
        ).pack(side="left", padx=(8, 0))
        if self._is_admin:
            ctk.CTkButton(
                actions,
                text="Chia sẻ lại (admin)",
                width=140,
                fg_color="transparent",
                border_width=1,
                command=self._publish_all,
            ).pack(side="left", padx=(8, 0))

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="x", padx=12, pady=(0, 4))
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)

        self._cards["ol"] = self._make_dataset_card(main, 0, 0, "ol")
        self._cards["bom_ke"] = self._make_dataset_card(main, 0, 1, "bom_ke")

        extra = self._section("Khác")
        self.ops_label = ctk.CTkLabel(extra, text="—", font=FONT_SMALL, anchor="w")
        self.ops_label.pack(anchor="w", pady=2)
        self.tpl_label = ctk.CTkLabel(extra, text="—", font=FONT_SMALL, anchor="w")
        self.tpl_label.pack(anchor="w", pady=2)
        ctk.CTkButton(
            extra,
            text="Đồng bộ plan / phiếu / tồn",
            width=180,
            fg_color="transparent",
            border_width=1,
            command=self._pull_ops,
        ).pack(anchor="w", pady=(10, 0))

        if not supabase_enabled():
            ctk.CTkLabel(
                self,
                text="Supabase chưa bật (.env) — chỉ xem cache local.",
                font=FONT_SMALL,
                text_color=COLORS["warning"][1],
            ).pack(anchor="w", padx=16, pady=(0, 12))

    def _make_dataset_card(self, parent, row: int, col: int, key: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=10)
        card.grid(row=row, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 6 if col == 0 else 0), pady=4)

        title_lbl = ctk.CTkLabel(card, text="—", font=("Segoe UI", 14, "bold"), anchor="w")
        title_lbl.pack(anchor="w", padx=14, pady=(12, 4))
        badge_lbl = ctk.CTkLabel(card, text="—", font=FONT_SMALL, anchor="w")
        badge_lbl.pack(anchor="w", padx=14)

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=14, pady=(8, 4))

        cloud_title = ctk.CTkLabel(body, text="Cloud (nguồn chính)", font=FONT_SMALL, text_color=COLORS["muted"])
        cloud_title.pack(anchor="w")
        cloud_lbl = ctk.CTkLabel(body, text="—", font=FONT_SMALL, anchor="w", wraplength=360, justify="left")
        cloud_lbl.pack(anchor="w", pady=(2, 8))

        local_title = ctk.CTkLabel(body, text="Cache local (đọc nhanh)", font=FONT_SMALL, text_color=COLORS["muted"])
        local_title.pack(anchor="w")
        local_lbl = ctk.CTkLabel(body, text="—", font=FONT_SMALL, anchor="w", wraplength=360, justify="left")
        local_lbl.pack(anchor="w", pady=(2, 8))

        summary_lbl = ctk.CTkLabel(body, text="—", font=FONT_BODY, anchor="w", wraplength=360, justify="left")
        summary_lbl.pack(anchor="w")
        hint_lbl = ctk.CTkLabel(body, text="", font=FONT_SMALL, text_color=COLORS["muted"], anchor="w", wraplength=360, justify="left")
        hint_lbl.pack(anchor="w", pady=(4, 8))

        pull_btn = ctk.CTkButton(
            card,
            text="Đồng bộ từ admin",
            width=150,
            fg_color=COLORS["accent"][1],
            command=lambda k=key: self._pull_one(k),
        )
        pull_btn.pack(anchor="w", padx=14, pady=(0, 12))

        card._title = title_lbl  # type: ignore[attr-defined]
        card._badge = badge_lbl  # type: ignore[attr-defined]
        card._cloud = cloud_lbl  # type: ignore[attr-defined]
        card._local = local_lbl  # type: ignore[attr-defined]
        card._summary = summary_lbl  # type: ignore[attr-defined]
        card._hint = hint_lbl  # type: ignore[attr-defined]
        card._pull = pull_btn  # type: ignore[attr-defined]
        return card

    def _state_color(self, sync_state: str, ready: bool) -> str:
        if ready and sync_state == "synced":
            return COLORS["success"][1]
        if sync_state in ("missing_local", "stale", "partial", "missing_cloud"):
            return COLORS["warning"][1]
        if sync_state == "local_only":
            return COLORS["muted"][1]
        return COLORS["muted"][1]

    def _format_cloud_side(self, ds) -> str:
        c = ds.cloud
        if not c.available:
            return "Chưa có — admin cần đọc file và chia sẻ lên cloud."
        text = f"✓ {c.row_count:,} dòng"
        if c.label:
            text += f" · {c.label}"
        if c.publisher or c.at != "—":
            who = c.publisher or "admin"
            when = f", {c.at}" if c.at != "—" else ""
            text += f"\nChia sẻ: {who}{when}"
        if c.extra:
            text += f"\n{c.extra}"
        return text

    def _format_local(self, ds) -> str:
        loc = ds.local
        if not loc.available:
            return "Chưa có cache — bấm «Đồng bộ từ admin»."
        lines = [f"✓ {loc.row_count:,} dòng · {loc.label}"]
        if loc.at != "—":
            lines.append(f"Đọc/lưu: {loc.at}")
        if loc.extra:
            lines.append(loc.extra)
        return "\n".join(lines)

    def _refresh(self) -> None:
        report = build_data_status(self.state.db, self.shared)

        color = COLORS["success"][1] if report.ready_for_work else COLORS["warning"][1]
        self.headline_label.configure(text=report.headline, text_color=color)
        self.detail_label.configure(text=report.detail)

        for key in ("ol", "bom_ke"):
            ds = report.ol if key == "ol" else report.bom_ke
            card = self._cards[key]
            card._title.configure(text=ds.title)  # type: ignore[attr-defined]
            badge = SYNC_STATE_LABELS.get(ds.sync_state, ds.sync_state)
            card._badge.configure(  # type: ignore[attr-defined]
                text=f"● {badge}",
                text_color=self._state_color(ds.sync_state, ds.ready),
            )
            card._cloud.configure(text=self._format_cloud_side(ds))  # type: ignore[attr-defined]
            card._local.configure(text=self._format_local(ds))  # type: ignore[attr-defined]
            card._summary.configure(  # type: ignore[attr-defined]
                text=ds.summary,
                text_color=self._state_color(ds.sync_state, ds.ready),
            )
            card._hint.configure(text=ds.hint)  # type: ignore[attr-defined]
            card._pull.configure(state="normal" if report.cloud_enabled else "disabled")  # type: ignore[attr-defined]

        self.ops_label.configure(text=report.team_ops_summary)
        self.tpl_label.configure(text=report.template_summary)

    def _publisher_name(self) -> str:
        return self.state.user.display_name or self.state.user.username

    def _pull_one(self, key: str) -> None:
        card = self._cards[key]
        card._summary.configure(text="Đang đồng bộ…", text_color=COLORS["muted"][1])  # type: ignore[attr-defined]

        def worker() -> None:
            try:
                if key == "ol":
                    result = self.shared.pull_ol()
                    self.after(0, lambda: self._on_ol_done(result))
                else:
                    result = self.shared.pull_bom_ke()
                    self.after(0, lambda: self._on_bom_done(result))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda msg=err: self._on_fail(key, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _pull_all(self) -> None:
        self.headline_label.configure(text="Đang đồng bộ tất cả…", text_color=COLORS["muted"][1])

        def worker() -> None:
            try:
                result = self.shared.pull_all_team_data(skip_missing=True)
                self.after(0, lambda: self._on_pull_all_done(result))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda msg=err: self._on_fail("all", msg))

        threading.Thread(target=worker, daemon=True).start()

    def _pull_ops(self) -> None:
        self.ops_label.configure(text="Plan / phiếu / tồn: đang đồng bộ…")

        def worker() -> None:
            try:
                from core.team_ops_sync import TeamOpsSyncService

                ops = TeamOpsSyncService(self.state.db).sync_bidirectional(actor_name=self._publisher_name())
                self.after(0, lambda: self._on_ops_done(ops))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda msg=err: self._on_fail("ops", msg))

        threading.Thread(target=worker, daemon=True).start()

    def _publish_all(self) -> None:
        if not self._is_admin:
            return
        try:
            msgs = self.shared.publish_all_team_data(publisher_name=self._publisher_name())
            self._refresh()
            messagebox.showinfo("Chia sẻ cloud", "\n".join(msgs), parent=self.winfo_toplevel())
        except Exception as exc:
            messagebox.showerror("Chia sẻ cloud", str(exc), parent=self.winfo_toplevel())

    def _on_ol_done(self, result) -> None:
        self.state.set_ol_result(result)
        self._refresh()
        messagebox.showinfo("OL", result.message, parent=self.winfo_toplevel())

    def _on_bom_done(self, result) -> None:
        self.state.set_bom_ke_result(result)
        self._refresh()
        messagebox.showinfo("Bảng kê", result.message, parent=self.winfo_toplevel())

    def _on_pull_all_done(self, result) -> None:
        if result.ol_result:
            self.state.set_ol_result(result.ol_result)
        if result.bom_result:
            self.state.set_bom_ke_result(result.bom_result)
        if getattr(result, "ops_pulled", False) or getattr(result, "ops_pushed", False):
            self.state.notify()
        self._refresh()
        lines = result.messages or ["Không có mục nào tải được."]
        if result.errors:
            lines.extend(["", "Bỏ qua:", *result.errors])
        messagebox.showinfo("Đồng bộ cloud", "\n".join(lines), parent=self.winfo_toplevel())

    def _on_ops_done(self, result) -> None:
        if getattr(result, "needs_overwrite_confirm", False):
            if messagebox.askyesno("Đồng bộ cloud", result.message, parent=self.winfo_toplevel()):
                from core.team_ops_sync import TeamOpsSyncService

                result = TeamOpsSyncService(self.state.db).push(
                    actor_name=self._publisher_name(),
                    force=True,
                )
            else:
                self._refresh()
                return
        if getattr(result, "pulled", False) or getattr(result, "pushed", False):
            self.state.notify()
        self._refresh()
        msg = getattr(result, "message", "") or "Xong."
        if getattr(result, "errors", None):
            msg += "\n\n" + "\n".join(result.errors)
        messagebox.showinfo("Plan / phiếu / tồn", msg, parent=self.winfo_toplevel())

    def _on_fail(self, key: str, msg: str) -> None:
        self._refresh()
        labels = {"ol": "OL", "bom_ke": "Bảng kê", "all": "Đồng bộ", "ops": "Plan/phiếu/tồn"}
        messagebox.showerror(labels.get(key, "Lỗi"), msg, parent=self.winfo_toplevel())
