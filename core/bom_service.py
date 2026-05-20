"""BOM / định mức lookup — tái sử dụng logic từ check_bom.py."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from check_bom import (
    BomSearcher,
    DatabaseManager as BomDatabaseManager,
    ExcelParser,
    extract_customer_code_from_product_code,
    extract_item_code_from_product_code,
    normalize_key,
    normalize_text,
)
from core.utils import normalize_dg_case


@dataclass
class BomResolveResult:
    dg_case: str
    file_path: str
    sheet_name: str
    cell: str
    customer_folder: str
    customer_name: str
    customer_code: str
    item_code: str
    message: str


@dataclass
class CustomerInfo:
    id: int
    name: str
    code: str
    folder_link: str


class BomLookupService:
    """Tìm file định mức theo DG Case + thư mục khách (giống tab Check Excel trong check_bom)."""

    def __init__(self, db: BomDatabaseManager | None = None):
        self.db = db or BomDatabaseManager()
        self.searcher = BomSearcher(self.db)
        self.parser = ExcelParser(self.db)

    def list_customers(self) -> list[CustomerInfo]:
        rows = self.db.get_customers()
        return [
            CustomerInfo(
                id=int(r[0]),
                name=str(r[1]),
                code=normalize_text(r[2]),
                folder_link=normalize_text(r[3]),
            )
            for r in rows
        ]

    def customer_by_code(self, code: str) -> CustomerInfo | None:
        key = normalize_key(code)
        for c in self.list_customers():
            if normalize_key(c.code) == key:
                return c
        return None

    def auto_customer_folder(
        self, production_no: str, customer_name: str = ""
    ) -> CustomerInfo | None:
        code = extract_customer_code_from_product_code(production_no)
        if code:
            found = self.customer_by_code(code)
            if found:
                return found
        if customer_name:
            key = normalize_key(customer_name)
            for c in self.list_customers():
                if normalize_key(c.name) == key or normalize_key(c.code) == key:
                    return c
        return None

    def resolve_bom_for_dg_case(
        self,
        dg_case: str,
        customer_folder: str,
        *,
        production_no: str = "",
        progress_cb: callable | None = None,
    ) -> BomResolveResult:
        dg = normalize_dg_case(dg_case)
        if not dg:
            raise ValueError("DG Case trống.")

        item_code = extract_item_code_from_product_code(production_no)
        file_path, sheet_name, cell = self.searcher.resolve_mapping(
            dg,
            customer_folder,
            item_code=item_code,
            progress_cb=progress_cb,
        )

        cust = self.auto_customer_folder(production_no)
        return BomResolveResult(
            dg_case=dg,
            file_path=file_path,
            sheet_name=sheet_name,
            cell=cell,
            customer_folder=customer_folder,
            customer_name=cust.name if cust else "",
            customer_code=cust.code if cust else extract_customer_code_from_product_code(production_no),
            item_code=item_code,
            message=f"Tìm thấy {dg} tại {Path(file_path).name} / sheet {sheet_name} / ô {cell}",
        )

    def load_bom_sheet_lines(self, file_path: str, sheet_name: str) -> pd.DataFrame:
        return self.parser.load_bom_sheet(file_path, sheet_name)

    def lookup_from_ol_row(self, ol_row: pd.Series, progress_cb: callable | None = None) -> BomResolveResult:
        dg = normalize_text(ol_row.get("dg_case", ""))
        prod = normalize_text(ol_row.get("production_no", ""))
        customer = normalize_text(ol_row.get("customer", ""))

        cust = self.auto_customer_folder(prod, customer)
        if not cust or not Path(cust.folder_link).exists():
            raise ValueError(
                f"Chưa cấu hình thư mục phần cho khách "
                f"(mã SP: {prod or '—'}, khách: {customer or '—'}). "
                "Thêm khách hàng trong tab Cài đặt hoặc mở Check BOM."
            )
        return self.resolve_bom_for_dg_case(
            dg,
            cust.folder_link,
            production_no=prod,
            progress_cb=progress_cb,
        )
