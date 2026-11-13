"""US CPSC SaferProducts Recall REST API watcher."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from watchkit.core import Hit, Item, Source

CPSC_RECALL_API_URL = "https://www.saferproducts.gov/RestWebServices/Recall?format=json"


def _text(val: Any) -> str:
    return str(val).strip() if val is not None else ""


def _items(val: Any) -> list[Any]:
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def _field_names(val: Any, *keys: str) -> list[str]:
    names: list[str] = []
    for item in _items(val):
        if isinstance(item, dict):
            found = next((_text(item.get(k)) for k in keys if _text(item.get(k))), "")
            if found:
                names.append(found)
        elif _text(item):
            names.append(_text(item))
    return names


def _count(val: Any) -> int:
    """Keep counts only; never retain narrative details."""
    if val in (None, ""):
        return 0
    if isinstance(val, list):
        return len(val)
    if isinstance(val, dict):
        for k in ("Count", "count", "Number", "number"):
            if k in val:
                return _count(val[k])
        return 1
    try:
        return int(val)
    except (TypeError, ValueError):
        return 1


def _normalize_cpsc_watchlist(raw_watchlist: Any) -> list[dict[str, Any]]:
    """Parse flexible watchlist formats into product/manufacturer keyword rules."""
    rules: list[dict[str, Any]] = []
    if isinstance(raw_watchlist, dict):
        raw_watchlist = [raw_watchlist]
    elif not isinstance(raw_watchlist, (list, tuple)):
        raw_watchlist = []

    for entry in raw_watchlist:
        if isinstance(entry, dict):
            prods = entry.get("products") or entry.get("product") or []
            mfgs = (
                entry.get("manufacturers")
                or entry.get("manufacturer")
                or entry.get("countries")
                or entry.get("country")
                or []
            )
            keywords = entry.get("keywords") or entry.get("keyword") or []

            prod_list = [prods] if isinstance(prods, str) else list(prods)
            mfg_list = [mfgs] if isinstance(mfgs, str) else list(mfgs)
            kw_list = [keywords] if isinstance(keywords, str) else list(keywords)

            rules.append({
                "products": [p.strip().casefold() for p in prod_list if p.strip()],
                "manufacturers": [m.strip().casefold() for m in mfg_list if m.strip()],
                "keywords": [k.strip().casefold() for k in kw_list if k.strip()],
            })
        elif isinstance(entry, str):
            line = entry.strip()
            if not line:
                continue
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]
                r: dict[str, list[str]] = {"products": [], "manufacturers": [], "keywords": []}
                for part in parts:
                    if part.lower().startswith("product:"):
                        vals = part.split(":", 1)[1].split(",")
                        r["products"].extend(v.strip().casefold() for v in vals if v.strip())
                    elif part.lower().startswith("manufacturer:") or part.lower().startswith("country:"):
                        vals = part.split(":", 1)[1].split(",")
                        r["manufacturers"].extend(v.strip().casefold() for v in vals if v.strip())
                    else:
                        r["keywords"].append(part.casefold())
                rules.append(r)
            else:
                rules.append({"products": [], "manufacturers": [], "keywords": [line.casefold()]})
    return rules


class CPSCRecallWatcher:
    """US CPSC SaferProducts Recall REST API watcher."""

    name = "cpsc_recalls"

    def __init__(
        self,
        url: str = CPSC_RECALL_API_URL,
        cache_path: Path | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.url = url
        self.cache_path = cache_path
        self.timeout = timeout
        self.source = Source(url=self.url, cache_path=self.cache_path, timeout=self.timeout)

    def fetch(self, offline_path: Path | None = None) -> str:
        return self.source.fetch(offline_path=offline_path)

    def parse(self, raw: Any) -> list[Item]:
        if isinstance(raw, str):
            doc = json.loads(raw)
        elif isinstance(raw, (dict, list)):
            doc = raw
        else:
            raise ValueError("CPSC raw data must be a JSON string, list, or dict")

        rows: list[dict[str, Any]] = []
        if isinstance(doc, list):
            rows = [r for r in doc if isinstance(r, dict)]
        elif isinstance(doc, dict):
            for k in ("Recalls", "recalls", "Recall", "recall"):
                if k in doc and isinstance(doc[k], list):
                    rows = [r for r in doc[k] if isinstance(r, dict)]
                    break

        items: list[Item] = []
        for raw_entry in rows:
            recall_num = _text(raw_entry.get("RecallNumber") or raw_entry.get("RecallID"))
            recall_date = _text(raw_entry.get("RecallDate"))
            title = _text(raw_entry.get("Title") or raw_entry.get("Description"))

            products = []
            for prod in _items(raw_entry.get("Products")):
                if isinstance(prod, dict):
                    products.append({
                        "name": _text(prod.get("Name")),
                        "model": _text(
                            prod.get("Model") or prod.get("Models") or prod.get("ModelNumber")
                        ),
                        "type": _text(prod.get("Type") or prod.get("Description")),
                        "units": _text(prod.get("NumberOfUnits") or prod.get("Units")),
                    })

            hazards = _field_names(raw_entry.get("Hazards"), "Name", "Description")
            remedies = _field_names(
                raw_entry.get("Remedies") or raw_entry.get("RemedyOptions"), "Name", "Description"
            )
            retailers = _field_names(raw_entry.get("Retailers"), "Name", "Retailer")
            made_in = _field_names(raw_entry.get("ManufacturerCountries"), "Country", "Name")
            upcs = _field_names(raw_entry.get("ProductUPCs"), "UPC", "Code", "Name")
            url = _text(raw_entry.get("URL") or raw_entry.get("Url"))

            item = Item(
                id=recall_num or title,
                title=title,
                date=recall_date,
                data={
                    "recall_number": recall_num,
                    "date": recall_date,
                    "title": title,
                    "products": products,
                    "hazards": hazards,
                    "remedies": remedies,
                    "retailers": retailers,
                    "manufacturer_countries": made_in,
                    "upcs": upcs,
                    "url": url,
                    "injury_count": _count(raw_entry.get("Injuries")),
                    "death_count": _count(raw_entry.get("Deaths")),
                },
            )
            items.append(item)
        return items

    def match(self, items: list[Item], watchlist: Any) -> list[Hit]:
        rules = _normalize_cpsc_watchlist(watchlist)
        if not rules:
            return []

        hits: list[Hit] = []
        for item in items:
            title_text = item.title.casefold()
            prods = item.data.get("products", [])
            prod_haystack = " ".join(
                f"{p.get('name', '')} {p.get('model', '')} {p.get('type', '')}" for p in prods
            ).casefold() + f" {title_text}"

            mfgs = item.data.get("manufacturer_countries", [])
            retailers = item.data.get("retailers", [])
            mfg_haystack = " ".join([*mfgs, *retailers]).casefold()

            hazards = item.data.get("hazards", [])
            hazard_haystack = " ".join(hazards).casefold()

            all_haystack = f"{prod_haystack} {mfg_haystack} {hazard_haystack}"

            for rule in rules:
                rule_prods = rule["products"]
                rule_mfgs = rule["manufacturers"]
                rule_kws = rule["keywords"]

                matched_prod = True
                if rule_prods:
                    matched_prod = any(p in prod_haystack for p in rule_prods)

                matched_mfg = True
                if rule_mfgs:
                    matched_mfg = any(m in mfg_haystack for m in rule_mfgs)

                matched_kw = True
                if rule_kws:
                    matched_kw = any(k in all_haystack for k in rule_kws)

                # If rule specified products or mfgs, both active criteria must match
                is_hit = False
                reasons: list[str] = []

                if rule_prods and rule_mfgs:
                    if matched_prod and matched_mfg:
                        is_hit = True
                        reasons.append(
                            f"商品關鍵字命中且製造/銷售地命中: prods={rule_prods}, mfgs={rule_mfgs}"
                        )
                elif rule_prods:
                    if matched_prod:
                        is_hit = True
                        reasons.append(f"商品關鍵字命中: {rule_prods}")
                elif rule_mfgs:
                    if matched_mfg:
                        is_hit = True
                        reasons.append(f"製造/銷售地關鍵字命中: {rule_mfgs}")
                elif rule_kws:
                    if matched_kw:
                        is_hit = True
                        reasons.append(f"關鍵字命中: {rule_kws}")

                if is_hit:
                    hits.append(
                        Hit(
                            item=item,
                            matched_rule=f"CPSC Rule: prods={rule_prods}, mfgs={rule_mfgs}, kws={rule_kws}",
                            reasons=reasons,
                            extra={
                                "recall_number": item.data.get("recall_number"),
                                "hazards": ", ".join(hazards),
                                "manufacturer_countries": ", ".join(mfgs),
                                "retailers": ", ".join(retailers),
                                "url": item.data.get("url"),
                            },
                        )
                    )
                    break

        return hits
