"""Phân trang + lọc nhanh cho bảng (tối đa 50 dòng/trang)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ui.theme import COLORS, FONT_SMALL

PAGE_SIZE_MAX = 50


class TablePager:
    def __init__(self, *, page_size: int = PAGE_SIZE_MAX) -> None:
        self.page_size = min(max(1, page_size), PAGE_SIZE_MAX)
        self.page = 1
        self.filter_text = ""
        self._all: list[Any] = []
        self._filtered: list[Any] = []

    def set_items(
        self,
        items: list[Any],
        *,
        filter_fn: Callable[[Any, str], bool] | None = None,
        reset_page: bool = True,
    ) -> None:
        self._all = list(items)
        if reset_page:
            self.page = 1
        self._apply_filter(filter_fn)

    def set_filter(self, text: str, *, filter_fn: Callable[[Any, str], bool] | None = None) -> None:
        self.filter_text = text
        self.page = 1
        self._apply_filter(filter_fn)

    def _apply_filter(self, filter_fn: Callable[[Any, str], bool] | None) -> None:
        q = self.filter_text.strip().lower()
        if q and filter_fn:
            self._filtered = [item for item in self._all if filter_fn(item, q)]
        else:
            self._filtered = list(self._all)
        if self.page > self.total_pages:
            self.page = self.total_pages

    @property
    def filtered_count(self) -> int:
        return len(self._filtered)

    @property
    def total_pages(self) -> int:
        if not self._filtered:
            return 1
        return max(1, (len(self._filtered) + self.page_size - 1) // self.page_size)

    def page_items(self) -> list[Any]:
        if not self._filtered:
            return []
        start = (self.page - 1) * self.page_size
        return self._filtered[start : start + self.page_size]

    def info_text(self) -> str:
        total = len(self._filtered)
        if total == 0:
            return "0 dòng"
        start = (self.page - 1) * self.page_size + 1
        end = min(self.page * self.page_size, total)
        return f"{start}–{end} / {total} · trang {self.page}/{self.total_pages}"

    def prev_page(self) -> bool:
        if self.page <= 1:
            return False
        self.page -= 1
        return True

    def next_page(self) -> bool:
        if self.page >= self.total_pages:
            return False
        self.page += 1
        return True


class TablePagerBar(ctk.CTkFrame):
    """Thanh lọc + nút prev/next — gọi on_change khi đổi trang/lọc."""

    def __init__(
        self,
        master,
        pager: TablePager,
        *,
        on_change: Callable[[], None],
        placeholder: str = "Lọc nhanh…",
        show_filter: bool = True,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.pager = pager
        self._on_change = on_change
        self._filter_var = ctk.StringVar()
        self._info = ctk.CTkLabel(self, text="", font=FONT_SMALL, text_color=COLORS["muted"])

        if show_filter:
            ctk.CTkLabel(self, text="Lọc", font=FONT_SMALL).pack(side="left", padx=(0, 6))
            entry = ctk.CTkEntry(
                self,
                textvariable=self._filter_var,
                width=180,
                height=30,
                placeholder_text=placeholder,
            )
            entry.pack(side="left", padx=(0, 8))
            entry.bind("<Return>", lambda _e: self._apply_filter())
            ctk.CTkButton(self, text="Áp dụng", width=72, height=30, command=self._apply_filter).pack(
                side="left", padx=(0, 12)
            )

        self._info.pack(side="left", padx=(0, 12))
        ctk.CTkButton(self, text="◀", width=36, height=30, command=self._prev).pack(side="right", padx=2)
        ctk.CTkButton(self, text="▶", width=36, height=30, command=self._next).pack(side="right", padx=2)

    def set_filter_handler(self, filter_fn: Callable[[Any, str], bool]) -> None:
        self._filter_fn = filter_fn

    def _apply_filter(self) -> None:
        fn = getattr(self, "_filter_fn", None)
        self.pager.set_filter(self._filter_var.get(), filter_fn=fn)
        self._on_change()

    def _prev(self) -> None:
        if self.pager.prev_page():
            self._on_change()

    def _next(self) -> None:
        if self.pager.next_page():
            self._on_change()

    def refresh_info(self) -> None:
        self._info.configure(text=self.pager.info_text())

    def reset_filter(self) -> None:
        self._filter_var.set("")
