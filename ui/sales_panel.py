"""Sales — placeholder."""

from __future__ import annotations

import customtkinter as ctk

from ui.theme import COLORS, FONT_SUB, FONT_TITLE


class SalesPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        ctk.CTkLabel(self, text="Sales", font=FONT_TITLE).pack(pady=(60, 12))
        ctk.CTkLabel(
            self,
            text="Module Sales sẽ được bổ sung sau.",
            font=FONT_SUB,
            text_color=COLORS["muted"],
            wraplength=560,
            justify="center",
        ).pack(pady=8, padx=24)
