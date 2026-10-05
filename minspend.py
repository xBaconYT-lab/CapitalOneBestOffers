"""Estimate the cheapest qualifying purchase for an offer tier.

Capital One Shopping never publishes a minimum purchase price, so we combine:
  1. a hard threshold parsed from the offer's exclusion text ("orders over $100"),
  2. a curated per-merchant table (data/min_spend.json),
  3. keyword heuristics on the tier name / merchant name,
  4. a fallback.
The result is always labelled with its source so the UI can show how trustworthy it is.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE_PATH = os.path.join(HERE, "data", "min_spend.json")

_MONEY = r"\$\s?(\d[\d,]*(?:\.\d+)?)"
THRESHOLD_PATTERNS = [
    re.compile(r"orders?\s+(?:of|over|above|totaling|totalling)\s+" + _MONEY + r"(?:\s*(?:or more|\+))?", re.I),
    re.compile(r"minimum\s+(?:purchase|order|spend|subtotal)\s+(?:of\s+)?" + _MONEY, re.I),
    re.compile(r"spend\s+(?:at least\s+|a minimum of\s+|over\s+)?" + _MONEY, re.I),
    re.compile(r"purchases?\s+(?:of|over|above)\s+" + _MONEY + r"(?:\s*(?:or more|\+))?", re.I),
    re.compile(_MONEY + r"\s*\+?\s*(?:minimum|or more|and up)", re.I),
    re.compile(r"(?:orders?|purchases?|subtotal)\s+(?:must be|that are|totaling)?\s*(?:at least|over|above|greater than)\s+" + _MONEY, re.I),
]


def load_table(path=TABLE_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        table = json.load(fh)
    # Pre-compile keyword rules and alias lookups.
    alias_index = {}
    for domain, entry in table.get("merchants", {}).items():
        alias_index[_norm(domain)] = domain
        label = domain.split(".")[0]
        alias_index.setdefault(_norm(label), domain)
        for alias in entry.get("aliases", []):
            alias_index.setdefault(_norm(alias), domain)
    table["_alias_index"] = alias_index
    for rule in table.get("tier_keywords", []) + table.get("merchant_keywords", []):
        rule["_re"] = re.compile(rule["match"], re.I)
    return table


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def parse_threshold(exclusions):
    """Return the highest hard minimum-order threshold found in the exclusion text, or None."""
    if not exclusions:
        return None
    found = []
    for pattern in THRESHOLD_PATTERNS:
        for match in pattern.finditer(exclusions):
            # Skip "under $400" / "less than $50" style exclusions – they are not order minimums.
            window = exclusions[max(0, match.start() - 25):match.start()].lower()
            if re.search(r"(under|less than|below|up to|maximum of|max\.?|capped at)\s*$", window):
                continue
            try:
                found.append(float(match.group(1).replace(",", "")))
            except ValueError:
                pass
    return max(found) if found else None


def find_merchant(table, domain, merchant_name):
    merchants = table.get("merchants", {})
    idx = table["_alias_index"]
    for candidate in (domain, merchant_name):
        key = _norm(candidate)
        if key and key in idx:
            return idx[key], merchants[idx[key]]
    if domain:
        label = _norm(domain.split(".")[0])
        if label in idx:
            return idx[label], merchants[idx[label]]
    return None, None


def resolve(table, domain, merchant_name, tier_name="", headline="", exclusions=""):
    """Return dict(min_spend, source, note) for one tier of an offer."""
    base, source, note = None, None, ""
    match_domain, entry = find_merchant(table, domain, merchant_name)

    if entry:
        tiers = entry.get("tiers") or {}
        text = tier_name or ""
        for pattern, value in tiers.items():
            if text and re.search(pattern, text, re.I):
                base, source, note = float(value), "curated", f"{entry.get('note', '')} · tier rule '{pattern}'".strip(" ·")
                break
        if base is None and entry.get("min_spend") is not None:
            base, source, note = float(entry["min_spend"]), "curated", entry.get("note", "")

    if base is None:
        for rule in table.get("tier_keywords", []):
            if tier_name and rule["_re"].search(tier_name):
                base, source, note = float(rule["min_spend"]), "estimated", rule.get("note", "")
                break
    if base is None:
        for rule in table.get("merchant_keywords", []):
            hay = f"{merchant_name} {domain}"
            if rule["_re"].search(hay):
                base, source, note = float(rule["min_spend"]), "estimated", rule.get("note", "")
                break
    if base is None:
        for rule in table.get("tier_keywords", []):
            if headline and rule["_re"].search(headline):
                base, source, note = float(rule["min_spend"]), "estimated", rule.get("note", "")
                break
    if base is None:
        base, source, note = float(table.get("fallback", 50)), "unknown", "No estimate available – set it yourself"

    threshold = parse_threshold(exclusions)
    if threshold is not None and threshold >= base:
        return {"min_spend": threshold, "source": "parsed", "note": f"Offer text requires orders over ${threshold:g}"}
    return {"min_spend": base, "source": source, "note": note}


if __name__ == "__main__":
    t = load_table()
    print(resolve(t, "paramountplus.com", "Paramount+", "", "Save at Paramount+", "Only eligible on first paid subscription."))
    print(resolve(t, "mintmobile.com", "mintmobile.com", "Mint Unlimited", "", "Only eligible for orders over $100."))
    print(resolve(t, "doordash.com", "DoorDash", "DashPass Sign Up", "", ""))
    print(resolve(t, "example.com", "Some Random Mobile", "", "", ""))
    print(resolve(t, "verizonwireless.com", "Verizon", "New Service Contracts", "", "Excludes devices under $400."))
