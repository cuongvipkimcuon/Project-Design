"""Helpers for popup windows — keep footers/actions always visible."""

from __future__ import annotations

import customtkinter as ctk


def configure_dialog(
    win: ctk.CTkToplevel,
    *,
    width: int,
    height: int,
    min_width: int | None = None,
    min_height: int | None = None,
    resizable: bool = True,
    parent: ctk.CTk | ctk.CTkToplevel | None = None,
) -> None:
    win.geometry(f"{width}x{height}")
    if min_width is not None and min_height is not None:
        win.minsize(min_width, min_height)
    win.resizable(resizable, resizable)
    if parent is not None:
        center_on_parent(win, parent)


def center_on_parent(win: ctk.CTkToplevel, parent: ctk.CTk | ctk.CTkToplevel) -> None:
    win.update_idletasks()
    try:
        top = parent.winfo_toplevel()
        px = top.winfo_rootx()
        py = top.winfo_rooty()
        pw = top.winfo_width()
        ph = top.winfo_height()
        ww = win.winfo_width()
        wh = win.winfo_height()
        x = px + max(0, (pw - ww) // 2)
        y = py + max(0, (ph - wh) // 2)
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass


def create_dialog_layout(
    win: ctk.CTkToplevel,
    *,
    padx: int = 20,
    pady: int = 16,
) -> tuple[ctk.CTkFrame, ctk.CTkFrame, ctk.CTkFrame, ctk.CTkFrame]:
    """Return (body, header, content, footer). Content row expands; footer stays pinned."""
    body = ctk.CTkFrame(win, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=padx, pady=pady)
    body.grid_columnconfigure(0, weight=1)
    body.grid_rowconfigure(1, weight=1)

    header = ctk.CTkFrame(body, fg_color="transparent")
    header.grid(row=0, column=0, sticky="new")

    content = ctk.CTkFrame(body, fg_color="transparent")
    content.grid(row=1, column=0, sticky="nsew")
    content.grid_columnconfigure(0, weight=1)
    content.grid_rowconfigure(0, weight=1)

    footer = ctk.CTkFrame(body, fg_color="transparent")
    footer.grid(row=2, column=0, sticky="sew", pady=(12, 0))
    return body, header, content, footer


def show_dialog(win: ctk.CTkToplevel, parent: ctk.CTk | ctk.CTkToplevel | None = None) -> None:
    if parent is not None:
        center_on_parent(win, parent)
    win.after(80, lambda: (win.lift(), win.focus_force()))
