"""Setup → Phân Quyền (chỉ admin)."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from core.app_state import AppState
from core.auth import AuthService
from core.permissions import ROLES, role_label
from core.supabase_service import APPROVAL_PENDING
from ui.theme import COLORS, FONT_BODY, FONT_SMALL, FONT_SUB


def _status_label(status: str) -> str:
    labels = {
        "pending": "Cho duyet",
        "approved": "Da duyet",
        "rejected": "Tu choi",
    }
    return labels.get(status, status)


class SetupPermissionsPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, state: AppState, auth: AuthService, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state
        self.auth = auth
        self._selected_id: str | None = None
        self._users: list[dict] = []
        self._build()
        self.reload_users()

    def _build(self) -> None:
        ctk.CTkLabel(
            self,
            text="Phan Quyen",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 4))
        ctk.CTkLabel(
            self,
            text="Dang ky moi o trang thai cho duyet. Admin duyet va gan role Design/Sales.",
            font=FONT_SUB,
            text_color=COLORS["muted"],
            wraplength=720,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 12))

        pending_box = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        pending_box.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(
            pending_box,
            text="Cho duyet",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))
        self.pending_list = ctk.CTkTextbox(pending_box, height=100, font=("Consolas", 11))
        self.pending_list.pack(fill="x", padx=16, pady=(0, 8))
        self.pending_list.bind("<ButtonRelease-1>", lambda e: self._on_select_pending())
        prow = ctk.CTkFrame(pending_box, fg_color="transparent")
        prow.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(
            prow,
            text="Duyet",
            width=90,
            fg_color=COLORS["success"][1],
            command=self._approve_selected,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            prow,
            text="Tu choi",
            width=90,
            fg_color="#c62828",
            command=self._reject_selected,
        ).pack(side="left", padx=4)

        box = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        box.pack(fill="both", expand=True, padx=12, pady=8)

        self.user_list = ctk.CTkTextbox(box, height=200, font=("Consolas", 11))
        self.user_list.pack(fill="x", padx=16, pady=(16, 8))
        self.user_list.bind("<ButtonRelease-1>", lambda e: self._on_select_line())

        ctrl = ctk.CTkFrame(box, fg_color="transparent")
        ctrl.pack(fill="x", padx=16, pady=(0, 16))

        ctk.CTkLabel(ctrl, text="Role:", font=FONT_BODY).pack(side="left")
        self.role_var = ctk.StringVar(value=role_label("design"))
        ctk.CTkOptionMenu(
            ctrl,
            variable=self.role_var,
            values=[role_label(r) for r in ROLES],
            width=140,
        ).pack(side="left", padx=8)

        ctk.CTkButton(ctrl, text="Luu role", width=100, command=self._save_role).pack(side="left", padx=4)
        ctk.CTkButton(ctrl, text="Khoa", width=72, command=lambda: self._set_active(False)).pack(
            side="left", padx=4
        )
        ctk.CTkButton(ctrl, text="Mo", width=72, command=lambda: self._set_active(True)).pack(side="left", padx=4)
        ctk.CTkButton(ctrl, text="R", width=40, command=self.reload_users).pack(side="left", padx=8)

        self.status = ctk.CTkLabel(box, text="", font=FONT_SMALL, text_color=COLORS["muted"])
        self.status.pack(anchor="w", padx=16, pady=(0, 12))

    def reload_users(self) -> None:
        try:
            self._users = self.auth.list_users()
            pending = self.auth.list_pending_users()
        except Exception as exc:
            messagebox.showerror("Phan Quyen", str(exc))
            return

        plines = []
        for u in pending:
            plines.append(f"[{u['id']}] @{u['username']} | {u.get('display_name', '')}")
        self.pending_list.delete("1.0", "end")
        self.pending_list.insert("1.0", "\n".join(plines) if plines else "(khong co yeu cau cho duyet)")

        lines = []
        for u in self._users:
            active = "OK" if u.get("is_active", True) else "OFF"
            lines.append(
                f"[{u['id']}] @{u['username']} | {u.get('display_name', '')} | "
                f"{role_label(u.get('role', 'design'))} | {_status_label(u.get('approval_status', ''))} | {active}"
            )
        self.user_list.delete("1.0", "end")
        self.user_list.insert("1.0", "\n".join(lines) if lines else "(chua co user)")
        self.status.configure(text=f"{len(self._users)} tai khoan | {len(pending)} cho duyet")

    def _parse_id_from_line(self, line: str) -> str | None:
        if line.startswith("["):
            try:
                return line.split("]")[0][1:]
            except ValueError:
                return None
        return None

    def _on_select_pending(self) -> None:
        try:
            line = self.pending_list.get("sel.first", "sel.last").strip()
        except Exception:
            return
        self._selected_id = self._parse_id_from_line(line)

    def _on_select_line(self) -> None:
        try:
            line = self.user_list.get("sel.first", "sel.last").strip()
        except Exception:
            return
        self._selected_id = self._parse_id_from_line(line)

    def _role_from_label(self, label: str) -> str:
        rev = {role_label(r): r for r in ROLES}
        return rev.get(label, "design")

    def _approve_selected(self) -> None:
        if not self._selected_id:
            messagebox.showwarning("Phan Quyen", "Chon user trong danh sach cho duyet.")
            return
        role = self._role_from_label(self.role_var.get())
        try:
            self.auth.approve_user(self.state.user.role, self._selected_id, role=role)
            self.reload_users()
            messagebox.showinfo("Phan Quyen", "Da duyet tai khoan.")
        except Exception as exc:
            messagebox.showerror("Phan Quyen", str(exc))

    def _reject_selected(self) -> None:
        if not self._selected_id:
            messagebox.showwarning("Phan Quyen", "Chon user trong danh sach cho duyet.")
            return
        if not messagebox.askyesno("Xac nhan", "Tu choi tai khoan nay?"):
            return
        try:
            self.auth.reject_user(self.state.user.role, self._selected_id)
            self.reload_users()
        except Exception as exc:
            messagebox.showerror("Phan Quyen", str(exc))

    def _save_role(self) -> None:
        if not self._selected_id:
            messagebox.showwarning("Phan Quyen", "Chon mot dong user trong danh sach.")
            return
        role = self._role_from_label(self.role_var.get())
        try:
            self.auth.set_user_role(self.state.user.role, self._selected_id, role)
            self.reload_users()
            messagebox.showinfo("Phan Quyen", "Da cap nhat role.")
        except Exception as exc:
            messagebox.showerror("Phan Quyen", str(exc))

    def _set_active(self, active: bool) -> None:
        if not self._selected_id:
            messagebox.showwarning("Phan Quyen", "Chon user truoc.")
            return
        try:
            self.auth.set_user_active(self.state.user.role, self._selected_id, active)
            self.reload_users()
        except Exception as exc:
            messagebox.showerror("Phan Quyen", str(exc))
