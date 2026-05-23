"""Toast nhẹ — thông báo không chặn UI."""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import COLORS, FONT_SMALL

_toast_win: ctk.CTkToplevel | None = None
_toast_after_id: str | None = None


def show_toast(parent: ctk.CTk, message: str, *, duration_ms: int = 3500) -> None:
    """Hiện toast góc dưới-phải cửa sổ chính (gọi trên main thread)."""
    global _toast_win, _toast_after_id

    if _toast_win is not None:
        try:
            if _toast_after_id:
                _toast_win.after_cancel(_toast_after_id)
            _toast_win.destroy()
        except Exception:
            pass
        _toast_win = None
        _toast_after_id = None

    win = ctk.CTkToplevel(parent)
    win.withdraw()
    win.overrideredirect(True)
    win.attributes("-topmost", True)

    frame = ctk.CTkFrame(
        win,
        corner_radius=10,
        fg_color=COLORS["card"][1],
        border_width=1,
        border_color=COLORS["accent"][1],
    )
    frame.pack()
    ctk.CTkLabel(
        frame,
        text=message,
        font=FONT_SMALL,
        wraplength=340,
        justify="left",
    ).pack(padx=16, pady=12)

    win.update_idletasks()
    px = parent.winfo_rootx() + parent.winfo_width() - win.winfo_width() - 28
    py = parent.winfo_rooty() + parent.winfo_height() - win.winfo_height() - 28
    win.geometry(f"+{max(px, 0)}+{max(py, 0)}")
    win.deiconify()

    _toast_win = win

    def _close() -> None:
        global _toast_win, _toast_after_id
        try:
            win.destroy()
        except Exception:
            pass
        _toast_win = None
        _toast_after_id = None

    _toast_after_id = win.after(duration_ms, _close)


def schedule_toast(parent: ctk.CTk, message: str, *, duration_ms: int = 3500) -> None:
    """Thread-safe — lên lịch toast trên main thread."""
    parent.after(0, lambda: show_toast(parent, message, duration_ms=duration_ms))
