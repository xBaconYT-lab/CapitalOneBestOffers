"""Estimate the cheapest qualifying purchase for an offer tier, reading the offer's fine print.

Capital One Shopping never publishes a minimum purchase price, so we combine:
  1. the offer's own terms: a hard order threshold ("orders over $100") and any commitment
     ("subscribe for 2 consecutive months", "stay connected for another 40 days"),
  2. a curated per-merchant table of entry-level prices (data/min_spend.json),
  3. keyword heuristics on the tier name / merchant name,
  4. a fallback.
The result is labelled with its source so the UI can show how trustworthy it is.
"""
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
TABLE_PATH = os.path.join(HERE, "data", "min_spend.json")

_MONEY = r"\$\s?(\d[\d,]*(?:\.\d+)?)"
_NUM = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve|eighteen|twenty-four)"
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "twelve": 12, "eighteen": 18, "twenty-four": 24}

THRESHOLD_PATTERNS = [
    re.compile(r"orders?\s+(?:of|over|above|totaling|totalling)\s+" + _MONEY + r"(?:\s*(?:or more|\+))?", re.I),
    re.compile(r"minimum\s+(?:purchase|order|spend|subtotal)\s+(?:of\s+)?" + _MONEY, re.I),
    re.compile(r"spend\s+(?:at least\s+|a minimum of\s+|over\s+)?" + _MONEY, re.I),
    re.compile(r"purchases?\s+(?:of|over|above)\s+" + _MONEY + r"(?:\s*(?:or more|\+))?", re.I),
    re.compile(_MONEY + r"\s*\+?\s*(?:minimum|or more|and up)", re.I),
    re.compile(r"(?:orders?|purchases?|subtotal)\s+(?:must be|that are|totaling)?\s*(?:at least|over|above|greater than)\s+" + _MONEY, re.I),
]

# How long the customer must keep paying before the bonus is earned.
COMMITMENT_PATTERNS = [
    # "subscribe for 2 consecutive months", "remain active for 3 months", "stay connected for another 40 days"
    re.compile(r"(?:subscribe[ds]?|remain|stay|keep|maintain|active|connected|enrolled|paid|subscription|service)\b[^.;]{0,40}?\bfor\s+(?:at least\s+|a minimum of\s+|another\s+|an additional\s+)?" + _NUM + r"\s*(?:consecutive\s+|full\s+|additional\s+)?(months?|days?|weeks?|billing cycles?|years?)\b", re.I),
    # "2 consecutive months", "three consecutive billing cycles"
    re.compile(_NUM + r"\s+consecutive\s+(months?|days?|weeks?|billing cycles?|years?)\b", re.I),
    # "12-month contract", "two-year agreement", "minimum 3 month term"
    re.compile(r"(?:minimum (?:of )?|at least )?" + _NUM + r"[-\s](month|year)s?\s*(?:contract|term|commitment|agreement|plan|subscription|service|membership)", re.I),
    # "a minimum of 3 months", "at least 90 days of service"
    re.compile(r"(?:minimum of|at least|a minimum of|no less than)\s+" + _NUM + r"\s+(months?|years?|days?|weeks?)\b", re.I),
]
ANNUAL_REQUIRED = re.compile(r"(?:only (?:eligible|valid|available) (?:on|for|with) (?:an? )?(?:annual|yearly)|(?:annual|yearly) (?:plans?|subscriptions?|memberships?) only|must (?:purchase|buy|subscribe to|select) (?:an? )?(?:annual|yearly))", re.I)

CONDITION_TAGS = [
    ("New customers only", re.compile(r"\bnew (?:customers?|subscribers?|members?|users?|accounts?|clients?)\b|first[- ]time (?:customers?|purchasers?|buyers?|subscribers?)", re.I)),
    ("First order only", re.compile(r"\bfirst (?:paid )?(?:order|purchase|subscription)\b|first[- ]time purchase", re.I)),
    ("No free trial", re.compile(r"not eligible for (?:free )?trials?|cannot be combined with (?:a )?free trials?|free trials? (?:are |is )?not eligible|not eligible for sign-?ups?|after the free trial", re.I)),
    ("No renewals/upgrades", re.compile(r"not eligible for (?:plan )?renewals?|not eligible (?:for|on) (?:plan )?(?:upgrades?|renewals?)|renewals? (?:are |is )?not eligible|contract renewals", re.I)),
    ("One-time bonus", re.compile(r"one[- ]time only|does not recur|one[- ]time (?:bonus|reward|payout)", re.I)),
    ("Payment validation required", re.compile(r"payment validation required|active subscription (?:and payment validation )?required", re.I)),
    ("Not for gift cards", re.compile(r"gift cards?", re.I)),
    ("Promo codes may void offer", re.compile(r"promotional codes? not provided by capital one", re.I)),
    ("US residents only", re.compile(r"residents? of the u\.?s\.?|u\.?s\.? residents?", re.I)),
    ("18+ only", re.compile(r"\b18\+|18 (?:years|or older)", re.I)),
]


def _to_int(token):
    token = token.lower()
    return _WORDS.get(token) or int(token)


def _to_months(n, unit):
    unit = unit.lower()
    if unit.startswith("year"):
        return n * 12
    if unit.startswith("day"):
        return max(1, math.ceil(n / 30.0))
    if unit.startswith("week"):
        return max(1, math.ceil(n / 4.0))
    return n  # months / billing cycles


def parse_threshold(exclusions):
    """Return the highest hard minimum-order threshold found in the exclusion text, or None."""
    if not exclusions:
        return None
    found = []
    for pattern in THRESHOLD_PATTERNS:
        for match in pattern.finditer(exclusions):
            window = exclusions[max(0, match.start() - 25):match.start()].lower()
            if re.search(r"(under|less than|below|up to|maximum of|max\.?|capped at)\s*$", window):
                continue
            try:
                found.append(float(match.group(1).replace(",", "")))
            except ValueError:
                pass
    return max(found) if found else None


def parse_conditions(exclusions):
    """Read the fine print and return structured requirements.

    {
      "threshold": 100.0 | None,          # minimum order size in dollars
      "commitment_months": 2 | None,      # how many months you must keep paying
      "commitment_text": "subscribe for 2 consecutive months",
      "device_min": 400.0 | None,         # device purchases must be at least this
      "max_lines": 4 | None,
      "tags": ["New customers only", "Commitment: 2 months", ...]
    }
    """
    text = exclusions or ""
    out = {"threshold": parse_threshold(text), "commitment_months": None, "commitment_text": None,
           "device_min": None, "max_lines": None, "tags": []}

    best = (0, None)
    for pattern in COMMITMENT_PATTERNS:
        for m in pattern.finditer(text):
            try:
                months = _to_months(_to_int(m.group(1)), m.group(2))
            except (ValueError, IndexError):
                continue
            if months > best[0]:
                best = (months, m.group(0).strip())
    if ANNUAL_REQUIRED.search(text) and best[0] < 12:
        best = (12, ANNUAL_REQUIRED.search(text).group(0))
    if best[0] > 1:
        out["commitment_months"], out["commitment_text"] = best
        out["tags"].append(f"Keep it {best[0]} months")

    m = re.search(r"devices?\s+(?:under|below|less than|priced under)\s+" + _MONEY, text, re.I)
    if m:
        out["device_min"] = float(m.group(1).replace(",", ""))
        out["tags"].append(f"Devices must be ${m.group(1)}+")
    m = re.search(r"maximum of\s+" + _NUM + r"\s+lines", text, re.I)
    if m:
        out["max_lines"] = _to_int(m.group(1))
        out["tags"].append(f"Max {out['max_lines']} lines")
    if out["threshold"]:
        out["tags"].append(f"Order ${out['threshold']:g}+")

    for label, pattern in CONDITION_TAGS:
        if pattern.search(text) and label not in out["tags"]:
            out["tags"].append(label)
    return out


def load_table(path=TABLE_PATH):
    with open(path, "r", encoding="utf-8") as fh:
        table = json.load(fh)
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


def base_estimate(table, domain, merchant_name, tier_name="", headline=""):
    """Cheapest single purchase / one month of service, before reading the fine print."""
    match_domain, entry = find_merchant(table, domain, merchant_name)
    if entry:
        for pattern, value in (entry.get("tiers") or {}).items():
            if tier_name and re.search(pattern, tier_name, re.I):
                return float(value), "curated", f"{entry.get('note', '')} · tier rule '{pattern}'".strip(" ·")
        if entry.get("min_spend") is not None:
            return float(entry["min_spend"]), "curated", entry.get("note", "")
    for rule in table.get("tier_keywords", []):
        if tier_name and rule["_re"].search(tier_name):
            return float(rule["min_spend"]), "estimated", rule.get("note", "")
    for rule in table.get("merchant_keywords", []):
        if rule["_re"].search(f"{merchant_name} {domain}"):
            return float(rule["min_spend"]), "estimated", rule.get("note", "")
    for rule in table.get("tier_keywords", []):
        if headline and rule["_re"].search(headline):
            return float(rule["min_spend"]), "estimated", rule.get("note", "")
    return float(table.get("fallback", 50)), "unknown", "No estimate available – set it yourself"


def resolve(table, domain, merchant_name, tier_name="", headline="", exclusions="", conditions=None):
    """Return dict(min_spend, base, months, source, note) for one tier of an offer.

    min_spend = max(fine-print threshold, base price × months you must keep paying)
    """
    cond = conditions if conditions is not None else parse_conditions(exclusions)
    base, source, note = base_estimate(table, domain, merchant_name, tier_name, headline)
    months = cond.get("commitment_months") or 1
    total = base * months
    if months > 1:
        note = f"{note or 'estimate'} × {months} months – terms say \"{cond.get('commitment_text')}\""
    threshold = cond.get("threshold")
    if threshold is not None and threshold > total:
        return {"min_spend": threshold, "base": base, "months": months, "source": "parsed",
                "note": f"Terms require orders over ${threshold:g}"}
    return {"min_spend": total, "base": base, "months": months, "source": source, "note": note}


if __name__ == "__main__":
    t = load_table()
    tests = [
        ("paramountplus.com", "Paramount+", "", "Only eligible on first paid subscription. Active subscription and payment validation required after the free trial period. Not eligible for signups."),
        ("mintmobile.com", "Mint Mobile", "Mint Unlimited", "Not eligible for plan renewals or on starter kits. Only eligible for orders over $100."),
        ("directv.com", "DIRECTV", "Choice", "User must subscribe for 2 consecutive months to receive a payout on DIRECTV products. Active subscription and payment validation required. Devices are ineligible for a payout."),
        ("xfinity.com", "Xfinity", "", "Only eligible when a customer connects new services. Customers must connect their service within 40 days from sign-up, and stay connected for another 40 days. Limit one new line activation per customer."),
        ("verizonwireless.com", "Verizon", "New Service Contracts", "Only eligible for new customers, add a line, prepaid customers and 5G Home activations. Only eligible for a maximum of four lines. Excludes devices under $400."),
        ("example.com", "Some Fiber Internet", "", "Must maintain service for a minimum of three months. Offer valid only for 18+ residents of the U.S."),
    ]
    for domain, name, tier, excl in tests:
        c = parse_conditions(excl)
        r = resolve(t, domain, name, tier, "", excl, c)
        print(f"{name:<22} min ${r['min_spend']:<8g} base ${r['base']:<7g} x{r['months']} [{r['source']}] tags={c['tags']}")
