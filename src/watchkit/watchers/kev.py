"""CISA Known Exploited Vulnerabilities (KEV) catalog watcher."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from watchkit.core import Hit, Item, Source

CISA_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

_CORPORATE_SUFFIXES = {
    "ag",
    "co",
    "company",
    "corp",
    "corporation",
    "foundation",
    "gmbh",
    "group",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "ltd",
    "networks",
    "software",
    "systems",
    "technologies",
    "technology",
}

VENDOR_ALIASES = {
    "ms": "microsoft",
    "微軟": "microsoft",
    "思科": "cisco",
    "合勤": "zyxel",
    "海康": "hikvision",
    "海康威視": "hikvision",
    "華碩": "asus",
    "趨勢科技": "trend micro",
    "甲骨文": "oracle",
    "蘋果": "apple",
    "谷歌": "google",
    "dlink": "d link",
    "paloalto": "palo alto",
    "vmware by broadcom": "vmware",
    "fortigate": "fortinet",
    "fortios": "fortinet",
    "moveit": "progress",
}

PRODUCT_ALIASES = {
    "chrome": ("chromium",),
    "edge": ("chromium",),
}


def normalize(value: str) -> str:
    """Normalize text with NFKC, lowercase, and collapse punctuation into spaces."""
    if not isinstance(value, str):
        return ""
    folded = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.findall(r"[^\W_]+", folded, flags=re.UNICODE))


def _vendor_tokens(value: str) -> tuple[str, ...]:
    norm = normalize(value)
    aliased = VENDOR_ALIASES.get(norm, norm)
    tokens = aliased.split()
    while tokens and tokens[-1] in _CORPORATE_SUFFIXES:
        tokens.pop()
    return tuple(tokens)


def _vendor_matches(actual: str, wanted: str) -> bool:
    """Compare normalized vendor tokens, ignoring corporate suffixes."""
    actual_tokens = _vendor_tokens(actual)
    wanted_tokens = _vendor_tokens(wanted)
    return bool(actual_tokens and wanted_tokens and actual_tokens == wanted_tokens)


def _product_matches(actual: str, wanted: str) -> bool:
    """Substring matching on product names with alias support."""
    actual_norm = normalize(actual)
    if not actual_norm:
        return False
    wanted_norm = normalize(wanted)
    if not wanted_norm:
        return False

    aliases = (wanted_norm, *PRODUCT_ALIASES.get(wanted_norm, ()))
    for candidate in aliases:
        if candidate in actual_norm or actual_norm in candidate:
            return True
    return False


def _normalize_watchlist(raw_watchlist: Any) -> list[dict[str, Any]]:
    """Convert flexible watchlist inputs into normalized rules."""
    rules: list[dict[str, Any]] = []
    if isinstance(raw_watchlist, dict):
        raw_watchlist = [raw_watchlist]
    elif not isinstance(raw_watchlist, (list, tuple)):
        raw_watchlist = []

    for entry in raw_watchlist:
        if isinstance(entry, dict):
            vendor = str(entry.get("vendor", "")).strip()
            products = entry.get("products", "*")
            if not vendor:
                continue
            if products != "*" and isinstance(products, str):
                products = [p.strip() for p in products.split(",") if p.strip()]
            rules.append({"vendor": vendor, "products": products})
        elif isinstance(entry, str):
            line = entry.strip()
            if not line:
                continue
            if ":" in line:
                vendor_part, prod_part = line.split(":", 1)
                prods = [p.strip() for p in prod_part.split(",") if p.strip()]
                rules.append({"vendor": vendor_part.strip(), "products": prods or "*"})
            else:
                rules.append({"vendor": line, "products": "*"})
    return rules


class KEVWatcher:
    """Public CISA Known Exploited Vulnerabilities catalog watcher."""

    name = "kev"

    def __init__(
        self,
        url: str = CISA_KEV_URL,
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
            data = json.loads(raw)
        elif isinstance(raw, dict):
            data = raw
        else:
            raise ValueError("KEV catalog raw data must be a JSON string or dict")

        vulnerabilities = data.get("vulnerabilities", [])
        if not isinstance(vulnerabilities, list):
            return []

        items: list[Item] = []
        for vuln in vulnerabilities:
            if not isinstance(vuln, dict):
                continue
            cve_id = str(vuln.get("cveID", "")).strip()
            vendor = str(vuln.get("vendorProject", "")).strip()
            product = str(vuln.get("product", "")).strip()
            vuln_name = str(vuln.get("vulnerabilityName", "")).strip()
            date_added = str(vuln.get("dateAdded", "")).strip()

            title = f"{vendor} {product}: {vuln_name}".strip()
            item = Item(
                id=cve_id or title,
                title=title,
                date=date_added,
                data={
                    "cve_id": cve_id,
                    "vendor": vendor,
                    "product": product,
                    "vulnerability_name": vuln_name,
                    "date_added": date_added,
                    "due_date": str(vuln.get("dueDate", "")).strip(),
                    "required_action": str(vuln.get("requiredAction", "")).strip(),
                    "ransomware": str(vuln.get("knownRansomwareCampaignUse", "")).strip(),
                    "short_description": str(vuln.get("shortDescription", "")).strip(),
                    "notes": str(vuln.get("notes", "")).strip(),
                    "cwes": vuln.get("cwes", []),
                },
            )
            items.append(item)
        return items

    def match(self, items: list[Item], watchlist: Any) -> list[Hit]:
        rules = _normalize_watchlist(watchlist)
        if not rules:
            return []

        hits: list[Hit] = []
        for item in items:
            vendor = item.data.get("vendor", "")
            product = item.data.get("product", "")

            matched = False
            matched_rule_desc = ""
            reasons: list[str] = []

            for rule in rules:
                wanted_vendor = rule["vendor"]
                wanted_products = rule["products"]

                if not _vendor_matches(vendor, wanted_vendor):
                    continue

                if wanted_products == "*":
                    matched = True
                    matched_rule_desc = f"Vendor: {wanted_vendor} (all products)"
                    reasons.append(f"供應商 '{vendor}' 命中自選規則 '{wanted_vendor}'")
                    break

                if isinstance(wanted_products, list):
                    for wp in wanted_products:
                        if _product_matches(product, wp):
                            matched = True
                            matched_rule_desc = f"Vendor: {wanted_vendor}, Product: {wp}"
                            reasons.append(
                                f"供應商 '{vendor}' 命中 '{wanted_vendor}' 且產品 '{product}' 命中 '{wp}'"
                            )
                            break
                    if matched:
                        break

            if matched:
                hits.append(
                    Hit(
                        item=item,
                        matched_rule=matched_rule_desc,
                        reasons=reasons,
                        extra={
                            "cve_id": item.data.get("cve_id"),
                            "vendor": vendor,
                            "product": product,
                            "due_date": item.data.get("due_date"),
                            "ransomware": item.data.get("ransomware"),
                            "required_action": item.data.get("required_action"),
                        },
                    )
                )

        return hits
