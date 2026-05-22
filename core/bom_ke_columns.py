"""Ten cot bang ke dinh muc — map Excel -> DataFrame.

- order_qty: so luong don hang khach dat (cot G)
- npl_qty_per_unit: so luong NPL can cho 1 san pham (cot O, SL DM1)
- npl_qty_order: so luong NPL can cho ca don hang (cot P)
"""

from __future__ import annotations

# Chi so cot Excel (0-based), dong du lieu tu row 9
COL_DG_CASE = 0
COL_ORDER_DATE = 1
COL_PRODUCT_CODE = 3
COL_ORDER_QTY = 6
COL_MA_NPL = 9
COL_TEN_NPL = 10
COL_MO_TA = 11
COL_DON_VI_TINH = 13
COL_NPL_QTY_PER_UNIT = 14
COL_NPL_QTY_ORDER = 15

ORDER_QTY = "order_qty"
NPL_QTY_PER_UNIT = "npl_qty_per_unit"
NPL_QTY_ORDER = "npl_qty_order"

# SQLite cot cu (migration doi ten)
LEGACY_DB_COLUMNS = {
    ORDER_QTY: "qty_divisor",
    NPL_QTY_PER_UNIT: "so_luong_dm_1",
    NPL_QTY_ORDER: "so_luong",
}
