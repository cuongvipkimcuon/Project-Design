"""Quy tắc Detail — team (cloud/admin) + local (user riêng)."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any, Literal

from core.database import HubDatabase
from core.dg_case_lookup import customer_context_for_line
from core.emg_scanner_reader import lookup_uniform_serial
from core.utils import normalize_text

SETUP_KEY_LEGACY = "supplier_detail_rules"
SETUP_KEY_TEAM = "supplier_detail_rules_team"
SETUP_KEY_TEAM_HASH = "supplier_detail_rules_team_hash"
SETUP_KEY_LOCAL = "supplier_detail_rules_local"

RULE_FIXED = "fixed"
RULE_EMG_SERIAL = "emg_serial"
RULE_PICTOGRAM = "pictogram"
RULE_SCOPE_TEAM = "team"
RULE_SCOPE_LOCAL = "local"

DEFAULT_PICTO_SIZE_CM = {"S": 10, "M": 12, "L": 17}
EMG_SERIAL_SCAN_LIMIT = 10

DEFAULT_RULES_DOC = [
    {"prefix": "705…", "type": "Serial EMG", "detail": "case_no + scan_type IN, ~10 kết quả giống serial"},
    {"prefix": "704…", "type": "Text cố định", "detail": "Check Poly or Satin"},
    {"prefix": "720…", "type": "Pictogram", "detail": "Pictogram size {ký tự cuối} ({cm}cm)"},
]

RuleScope = Literal["team", "local"]


def _material_key(material_code: str) -> str:
    return normalize_text(material_code).replace(" ", "")


def _filter_tokens(raw: object) -> list[str]:
    return [normalize_text(p).lower() for p in str(raw or "").split(",") if normalize_text(p)]


def _values_match_filter(filter_raw: object, values: list[str]) -> bool:
    tokens = _filter_tokens(filter_raw)
    if not tokens:
        return True
    hay = [normalize_text(v).lower() for v in values if normalize_text(v)]
    if not hay:
        return False
    for token in tokens:
        for val in hay:
            if token == val or token in val or val.startswith(token):
                return True
    return False


def _rule_specificity(rule: dict[str, Any]) -> int:
    score = 0
    if normalize_text(rule.get("customer_filter")):
        score += 1
    if normalize_text(rule.get("production_no_filter")):
        score += 1
    if normalize_text(rule.get("logo_filter")):
        score += 1
    return score


def _parse_rules(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        data = []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict) and normalize_text(r.get("material_prefix"))]


def _sort_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = list(rules)
    out.sort(
        key=lambda r: (
            -len(_material_key(r.get("material_prefix", ""))),
            -_rule_specificity(r),
            int(r.get("sort_order") or 0),
            normalize_text(r.get("name")),
        )
    )
    return out


def _migrate_legacy_local(db: HubDatabase) -> None:
    local = db.get_setup(SETUP_KEY_LOCAL, "")
    if local:
        return
    legacy = db.get_setup(SETUP_KEY_LEGACY, "")
    if not legacy:
        return
    db.set_setup(SETUP_KEY_LOCAL, legacy, sync_cloud=False)
    db.set_setup(SETUP_KEY_LEGACY, "", sync_cloud=False)


def load_team_detail_rules(db: HubDatabase) -> list[dict[str, Any]]:
    raw = db.get_setup(SETUP_KEY_TEAM, "[]")
    rules = _parse_rules(raw)
    for rule in rules:
        rule.setdefault("scope", RULE_SCOPE_TEAM)
    return _sort_rules(rules)


def load_local_detail_rules(db: HubDatabase) -> list[dict[str, Any]]:
    _migrate_legacy_local(db)
    raw = db.get_setup(SETUP_KEY_LOCAL, "[]")
    rules = _parse_rules(raw)
    for rule in rules:
        rule["scope"] = RULE_SCOPE_LOCAL
    return _sort_rules(rules)


def load_detail_rules(db: HubDatabase) -> list[dict[str, Any]]:
    """Team (cloud/admin) + local (user) — dùng khi autofill."""
    team = load_team_detail_rules(db)
    local = load_local_detail_rules(db)
    merged = team + local
    return _sort_rules(merged)


def save_team_detail_rules(db: HubDatabase, rules: list[dict[str, Any]]) -> None:
    payload = []
    for rule in rules:
        item = dict(rule)
        item["scope"] = RULE_SCOPE_TEAM
        payload.append(item)
    db.set_setup(SETUP_KEY_TEAM, json.dumps(payload, ensure_ascii=False), sync_cloud=False)


def save_local_detail_rules(db: HubDatabase, rules: list[dict[str, Any]]) -> None:
    payload = []
    for rule in rules:
        item = dict(rule)
        item["scope"] = RULE_SCOPE_LOCAL
        payload.append(item)
    db.set_setup(SETUP_KEY_LOCAL, json.dumps(payload, ensure_ascii=False), sync_cloud=False)


def new_rule(
    *,
    name: str = "",
    material_prefix: str = "",
    customer_filter: str = "",
    production_no_filter: str = "",
    logo_filter: str = "",
    rule_type: str = RULE_FIXED,
    detail_text: str = "",
    pictogram_sizes: dict[str, int] | None = None,
    enabled: bool = True,
    scope: RuleScope = RULE_SCOPE_LOCAL,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:12],
        "name": normalize_text(name) or "Quy tắc mới",
        "material_prefix": normalize_text(material_prefix),
        "customer_filter": normalize_text(customer_filter),
        "production_no_filter": normalize_text(production_no_filter),
        "logo_filter": normalize_text(logo_filter),
        "rule_type": rule_type if rule_type in (RULE_FIXED, RULE_EMG_SERIAL, RULE_PICTOGRAM) else RULE_FIXED,
        "detail_text": normalize_text(detail_text),
        "pictogram_sizes": dict(pictogram_sizes or DEFAULT_PICTO_SIZE_CM),
        "enabled": bool(enabled),
        "sort_order": 0,
        "scope": scope,
    }


def rule_scope(rule: dict[str, Any]) -> str:
    scope = normalize_text(rule.get("scope"))
    return scope if scope in (RULE_SCOPE_TEAM, RULE_SCOPE_LOCAL) else RULE_SCOPE_LOCAL


def rule_matches_line(
    rule: dict[str, Any],
    material_code: str,
    *,
    line: dict[str, Any] | None = None,
    db: HubDatabase | None = None,
    ol_df=None,
    bom_df=None,
) -> bool:
    mat = _material_key(material_code)
    if not mat:
        return False
    prefix = _material_key(rule.get("material_prefix", ""))
    if not prefix or not mat.startswith(prefix):
        return False

    base_line = line or {"material_code": material_code}
    ctx = customer_context_for_line(base_line, db=db, ol_df=ol_df, bom_df=bom_df)

    if not _values_match_filter(
        rule.get("customer_filter"),
        [ctx.get("customer", ""), ctx.get("customer_code", "")],
    ):
        return False

    if not _values_match_filter(
        rule.get("production_no_filter"),
        [ctx.get("production_no", ""), ctx.get("product_code", "")],
    ):
        return False

    if not _values_match_filter(rule.get("logo_filter"), [ctx.get("logo", "")]):
        return False

    return True


def find_custom_rule(
    material_code: str,
    rules: list[dict[str, Any]],
    *,
    line: dict[str, Any] | None = None,
    db: HubDatabase | None = None,
    ol_df=None,
    bom_df=None,
) -> dict[str, Any] | None:
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        if rule_matches_line(
            rule,
            material_code,
            line=line,
            db=db,
            ol_df=ol_df,
            bom_df=bom_df,
        ):
            return rule
    return None


def format_rule_conditions(rule: dict[str, Any]) -> str:
    parts: list[str] = []
    customer = normalize_text(rule.get("customer_filter"))
    prod = normalize_text(rule.get("production_no_filter"))
    logo = normalize_text(rule.get("logo_filter"))
    if customer:
        parts.append(f"KH:{customer}")
    if prod:
        parts.append(f"Mã:{prod}")
    if logo:
        parts.append(f"Logo:{logo}")
    return " · ".join(parts)


def render_detail_template(template: str, ctx: dict[str, str]) -> str:
    text = normalize_text(template)
    if not text:
        return ""
    out = text
    for key, val in ctx.items():
        out = out.replace("{" + key + "}", val or "")
    return out.strip()


def _pictogram_detail(material_code: str, size_map: dict[str, int]) -> tuple[str, str, str]:
    parts = [p for p in material_code.split(".") if p]
    if not parts:
        return "", "", ""
    suffix = parts[-1].upper()
    if len(suffix) != 1:
        return "", "", ""
    cm = size_map.get(suffix)
    if cm is None:
        return "", "", ""
    return suffix, str(cm), f"Pictogram size {suffix} ({cm}cm)"


def apply_custom_rule(
    rule: dict[str, Any],
    material_code: str,
    dg_case: str,
    *,
    db: HubDatabase | None = None,
    ol_df=None,
    bom_df=None,
    line: dict[str, Any] | None = None,
) -> str:
    mat = _material_key(material_code)
    base_line = line or {"material_code": material_code, "dg_case": dg_case}
    ctx = customer_context_for_line(base_line, db=db, ol_df=ol_df, bom_df=bom_df)
    ctx["material"] = mat
    ctx["dg_case"] = normalize_text(dg_case)

    rule_type = normalize_text(rule.get("rule_type")) or RULE_FIXED
    if rule_type == RULE_EMG_SERIAL:
        serial = lookup_uniform_serial(dg_case, db=db, limit=EMG_SERIAL_SCAN_LIMIT)
        ctx["serial"] = serial
        tpl = normalize_text(rule.get("detail_text"))
        if tpl:
            return render_detail_template(tpl, ctx) or serial
        return serial

    if rule_type == RULE_PICTOGRAM:
        sizes = rule.get("pictogram_sizes") or DEFAULT_PICTO_SIZE_CM
        if not isinstance(sizes, dict):
            sizes = DEFAULT_PICTO_SIZE_CM
        size_map = {str(k).upper(): int(v) for k, v in sizes.items()}
        suffix, cm, default = _pictogram_detail(mat, size_map)
        ctx["size"] = suffix
        ctx["cm"] = cm
        tpl = normalize_text(rule.get("detail_text"))
        if tpl:
            rendered = render_detail_template(tpl, ctx)
            if rendered:
                return rendered
        return default

    tpl = normalize_text(rule.get("detail_text"))
    return render_detail_template(tpl, ctx)


def _upsert_in_list(rules: list[dict[str, Any]], rule: dict[str, Any]) -> list[dict[str, Any]]:
    rid = normalize_text(rule.get("id"))
    payload = deepcopy(rule)
    if not rid:
        payload = new_rule(**{k: payload.get(k) for k in payload if k not in ("id", "scope")})
        rid = payload["id"]
    replaced = False
    out: list[dict[str, Any]] = []
    for item in rules:
        if normalize_text(item.get("id")) == rid:
            out.append(payload)
            replaced = True
        else:
            out.append(item)
    if not replaced:
        out.append(payload)
    return out


def upsert_rule(
    db: HubDatabase,
    rule: dict[str, Any],
    *,
    scope: RuleScope | None = None,
) -> list[dict[str, Any]]:
    target = scope or rule_scope(rule)
    if target == RULE_SCOPE_TEAM:
        rules = _upsert_in_list(load_team_detail_rules(db), rule)
        save_team_detail_rules(db, rules)
        return load_detail_rules(db)
    rules = _upsert_in_list(load_local_detail_rules(db), rule)
    save_local_detail_rules(db, rules)
    return load_detail_rules(db)


def delete_rule(
    db: HubDatabase,
    rule_id: str,
    *,
    scope: RuleScope | None = None,
) -> list[dict[str, Any]]:
    rid = normalize_text(rule_id)
    if scope in (RULE_SCOPE_TEAM, None):
        team = [r for r in load_team_detail_rules(db) if normalize_text(r.get("id")) != rid]
        if len(team) != len(load_team_detail_rules(db)):
            save_team_detail_rules(db, team)
            return load_detail_rules(db)
    if scope in (RULE_SCOPE_LOCAL, None):
        local = [r for r in load_local_detail_rules(db) if normalize_text(r.get("id")) != rid]
        if len(local) != len(load_local_detail_rules(db)):
            save_local_detail_rules(db, local)
    return load_detail_rules(db)
