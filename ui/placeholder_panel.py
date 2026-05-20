"""Tab placeholder."""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import COLORS, FONT_SUB, FONT_TITLE


class PlaceholderPanel(ctk.CTkFrame):
    def __init__(self, master, title: str, description: str, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        ctk.CTkLabel(self, text=title, font=FONT_TITLE).pack(pady=(60, 12))
        ctk.CTkLabel(
            self,
            text=description,
            font=FONT_SUB,
            text_color=COLORS["muted"],
            wraplength=560,
            justify="center",
        ).pack(pady=8, padx=24)
