"""Pull today's Capital One Shopping offer pool and rank it by value.

Usage:  python3 scraper.py [--calls 8] [--country US] [--quiet]
Writes: data/offers.json  and  data/history/YYYY-MM-DD.json
"""
import argparse
import datetime as dt
import http.cookiejar
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import minspend
import turbo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
HISTORY_DIR = os.path.join(DATA_DIR, "history")
OFFERS_PATH = os.path.join(DATA_DIR, "offers.json")

BASE = "https://capitaloneshopping.com"
FEED_URL = BASE + "/api/v1/feed"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


def ssl_context():
    """Build an SSL context that works even on python.org macOS builds whose cert store is empty."""
    import ssl
    ctx = ssl.create_default_context()
    if os.environ.get("C1_INSECURE") == "1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    try:
        import certifi  # type: ignore
        ctx.load_verify_locations(certifi.where())
        return ctx
    except Exception:
        pass
    for cafile in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/usr/local/etc/openssl/cert.pem", "/opt/homebrew/etc/openssl@3/cert.pem"):
        if os.path.exists(cafile):
            try:
                ctx.load_verify_locations(cafile)
                return ctx
            except Exception:
                continue
    return ctx


class Session:
    """Tiny cookie-aware HTTP client (stdlib only). The feed API needs the wb_session cookie."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl_context()),
            urllib.request.HTTPCookieProcessor(self.jar),
        )

    def get(self, url, timeout=30):
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        with self.opener.open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    def post_json(self, url, payload, timeout=30):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": BASE,
            "Referer": BASE + "/",
        })
        with self.opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))


def feed_payload(country):
    return {
        "contentProps": {},
        "context": {
            "country": country,
            "location": {},
            "page": {"path": "/", "url": BASE + "/", "referrer": "", "search": "",
                     "title": "Capital One Shopping: Coupons, Loyalty, and Deals"},
            "userAgent": USER_AGENT,
        },
    }


SITEMAP_URL = BASE + "/sitemap-merchant.xml"


def fetch_store_domains(session, log=print):
    """Domains that have a public store page at /s/<domain>/coupon (from the merchant sitemap)."""
    try:
        xml = session.get(SITEMAP_URL)
    except Exception as exc:
        log(f"  (merchant sitemap unavailable: {exc})")
        return set()
    domains = set(re.findall(r"/s/([^/<]+)/", xml))
    log(f"  merchant sitemap: {len(domains)} store pages")
    return domains


def store_url(domain):
    return f"{BASE}/s/{domain}/coupon" if domain else None


def fetch_pool(calls=8, country="US", log=print):
    """Each feed call returns a ~100 item sample of a larger pool, so call it several times and union."""
    session = Session()
    log("Loading homepage for session cookie + server-rendered feed…")
    html = session.get(BASE + "/")
    raw = []
    try:
        loader = turbo.loader_data(html) or {}
        home = (loader.get("routes/__app/index") or {}).get("HomePage") or {}
        initial = home.get("initialFeedData") or {}
        raw.extend(_collect(initial, "ssr"))
        log(f"  server-rendered feed: {len(raw)} entries")
    except Exception as exc:  # SSR decoding is only a bonus source
        log(f"  (could not decode server-rendered feed: {exc})")

    store_domains = fetch_store_domains(session, log)
    payload = feed_payload(country)

    def one_call(i):
        try:
            return i, session.post_json(FEED_URL, payload), None
        except Exception as exc:
            return i, None, exc

    # The API is slow (~5-7 s per call) but happy to be called a few times at once.
    with ThreadPoolExecutor(max_workers=min(4, max(1, calls))) as pool:
        results = list(pool.map(one_call, range(calls)))
    ok = 0
    for i, data, exc in sorted(results, key=lambda r: r[0]):
        if exc is not None or not isinstance(data, dict):
            log(f"  feed call {i + 1}/{calls} failed: {exc}")
            continue
        ok += 1
        raw.extend(_collect(data, f"api{i + 1}"))
        log(f"  feed call {i + 1}/{calls}: {len(data.get('items') or [])} items, "
            f"{len(data.get('events') or [])} events, {len(data.get('webCarouselEvents') or [])} carousel")
    if ok == 0 and not raw:
        raise RuntimeError("every feed call failed – is capitaloneshopping.com reachable?")
    return raw, store_domains


def _collect(data, batch):
    """Flatten every list in a feed response that can hold an offer."""
    out = []
    for key in ("items", "events", "webCarouselEvents", "luxuryItems", "bonusOffers"):
        for item in data.get(key) or []:
            if isinstance(item, dict):
                out.append((key, batch, item))
    headline = data.get("headlineOffers") or {}
    for key in ("live", "upcoming"):
        for item in headline.get(key) or []:
            if isinstance(item, dict):
                out.append((f"headline_{key}", batch, item))
    return out


# ---------- normalisation ----------

def parse_money(text):
    """'$87.50' -> 87.5 ; 'up to $16' -> 16 ; '4%' -> 4 ; returns (value, kind)"""
    if not text:
        return None, None
    text = str(text)
    m = re.search(r"\$\s?(\d[\d,]*(?:\.\d+)?)", text)
    if m:
        return float(m.group(1).replace(",", "")), "fixed"
    m = re.search(r"(\d+(?:\.\d+)?)\s?%", text)
    if m:
        return float(m.group(1)), "percentage"
    return None, None


def normalise(entry_source, batch, item):
    stats = item.get("stats") or {}
    cashback_text = stats.get("cashback") or stats.get("cashbackV2")
    amount, kind = parse_money(cashback_text)
    if amount is None:
        return None
    reward_type = stats.get("rewardType") or kind
    track = ((item.get("__mirage") or {}).get("trackProps") or {})
    domain = track.get("tld") or item.get("domain") or ""
    if not domain:
        for img_key in ("primaryImage", "secondaryImage"):
            m = re.search(r"logos\?domain=([^&]+)", item.get(img_key) or "")
            if m:
                domain = m.group(1)
                break
    merchant = item.get("merchantName") or (item.get("eventData") or {}).get("name") or domain or "Unknown"

    tiers = []
    seen = set()
    for cat in stats.get("cashbackCategories") or []:
        value, _ = parse_money(cat.get("cashback"))
        name = (cat.get("name") or "").strip()
        key = (re.sub(r"[^a-z0-9]", "", name.lower()), value)
        if value is None or key in seen:
            continue
        seen.add(key)
        tiers.append({"name": name, "amount": value})
    if not tiers:
        tiers.append({"name": "", "amount": amount})
    tiers.sort(key=lambda t: -t["amount"])

    event = item.get("eventData") or {}
    event_href = event.get("href") or (item.get("href") if str(item.get("href", "")).startswith("/") else None)
    href = item.get("href") if str(item.get("href", "")).startswith("http") else None
    logo = item.get("secondaryImage") if item.get("itemLevel") in ("product", "promotion") and item.get("secondaryImage") else item.get("primaryImage")
    if domain and "logos?domain=" not in (logo or ""):
        logo = f"https://images.capitaloneshopping.com/api/v1/logos?domain={domain}&height=400&type=cropped&fallback=true"

    return {
        "merchant": merchant.strip(),
        "domain": domain,
        "logo": logo,
        "cashback_text": cashback_text,
        "reward_type": "fixed" if reward_type == "fixed" else "percentage",
        "amount": amount,
        "max_payout": stats.get("rewardMaxPayout"),
        "tiers": tiers,
        "headline": item.get("primaryText") or f"Save at {merchant}",
        "pill": (item.get("pill") or {}).get("text"),
        "filter_label": item.get("filterLabel"),
        "item_type": item.get("type"),
        "item_level": item.get("itemLevel"),
        "sources": [entry_source],
        "batches": [batch],
        "ends_at": item.get("end"),
        "event_name": event.get("name"),
        "event_href": (BASE + event_href) if event_href else None,
        "exclusions": stats.get("exclusionsText") or "",
        "href": href,
    }


def merge(normalised):
    """Dedupe by merchant domain + reward text; keep the richest record."""
    merged = {}
    for offer in normalised:
        key = f"{offer['domain'] or offer['merchant'].lower()}|{offer['reward_type']}|{offer['amount']:g}"
        offer["pills"] = [offer["pill"]] if offer.get("pill") else []
        if key not in merged:
            offer["id"] = key
            merged[key] = offer
            continue
        cur = merged[key]
        if offer.get("pill") and offer["pill"] not in cur["pills"]:
            cur["pills"].append(offer["pill"])
        for field in ("sources", "batches"):
            for v in offer[field]:
                if v not in cur[field]:
                    cur[field].append(v)
        if len(offer["tiers"]) > len(cur["tiers"]):
            cur["tiers"] = offer["tiers"]
        for field in ("href", "event_href", "ends_at", "exclusions", "pill", "event_name", "max_payout"):
            if not cur.get(field) and offer.get(field):
                cur[field] = offer[field]
        if offer.get("item_level") == "merchant" and cur.get("item_level") != "merchant":
            cur["headline"], cur["item_level"], cur["logo"] = offer["headline"], offer["item_level"], offer["logo"]
    return list(merged.values())


def score(offers, table, store_domains=()):
    for offer in offers:
        cond = minspend.parse_conditions(offer["exclusions"])
        offer["conditions"] = cond
        offer["parsed_threshold"] = cond["threshold"]
        # The sitemap is region-locked from some countries; when we can't read it, trust the known URL pattern.
        offer["store_url"] = store_url(offer["domain"]) if (not store_domains or offer["domain"] in store_domains) else None
        offer["store_url_verified"] = bool(store_domains) and offer["domain"] in store_domains
        for tier in offer["tiers"]:
            if offer["reward_type"] == "fixed":
                est = minspend.resolve(table, offer["domain"], offer["merchant"], tier["name"], offer["headline"], offer["exclusions"], cond)
                tier.update({"min_spend": est["min_spend"], "min_spend_base": est["base"], "min_spend_months": est["months"],
                             "min_spend_source": est["source"], "min_spend_note": est["note"]})
                ms = tier["min_spend"]
                tier["ratio"] = (tier["amount"] / ms) if ms > 0 else None  # None => free, infinite value
                tier["net"] = tier["amount"] - ms
            else:
                tier.update({"min_spend": None, "min_spend_source": "n/a", "min_spend_note": "Percentage offer – value scales with what you spend"})
                tier["ratio"] = tier["amount"] / 100.0
                tier["net"] = None
        best = max(range(len(offer["tiers"])), key=lambda i: (offer["tiers"][i]["ratio"] is None, offer["tiers"][i]["ratio"] or 0, offer["tiers"][i]["amount"]))
        offer["best_tier_index"] = best
        best_tier = offer["tiers"][best]
        offer["score"] = 1e9 if best_tier["ratio"] is None else best_tier["ratio"]
    offers.sort(key=lambda o: (-(o["score"]), -o["amount"]))
    for rank, offer in enumerate(offers, 1):
        offer["rank"] = rank
    return offers


def mark_new(offers, today):
    """Flag offers that were not in the most recent earlier history file."""
    previous = None
    if os.path.isdir(HISTORY_DIR):
        for name in sorted(os.listdir(HISTORY_DIR), reverse=True):
            if name.endswith(".json") and name[:-5] < today:
                previous = os.path.join(HISTORY_DIR, name)
                break
    prev_ids = set()
    if previous:
        try:
            with open(previous, "r", encoding="utf-8") as fh:
                prev_ids = {o["id"] for o in json.load(fh).get("offers", [])}
        except Exception:
            prev_ids = set()
    for offer in offers:
        offer["new_today"] = bool(prev_ids) and offer["id"] not in prev_ids
    return os.path.basename(previous)[:-5] if previous else None


def run(calls=8, country="US", log=print):
    table = minspend.load_table()
    raw, store_domains = fetch_pool(calls=calls, country=country, log=log)
    normalised = [n for n in (normalise(*r) for r in raw) if n]
    offers = score(merge(normalised), table, store_domains)
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone().strftime("%Y-%m-%d")
    compared_to = mark_new(offers, today)
    result = {
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_local": now.astimezone().isoformat(timespec="seconds"),
        "source": FEED_URL,
        "country": country,
        "feed_calls": calls,
        "raw_entries": len(raw),
        "unique_offers": len(offers),
        "fixed_offers": sum(1 for o in offers if o["reward_type"] == "fixed"),
        "compared_to": compared_to,
        "offers": offers,
    }
    os.makedirs(HISTORY_DIR, exist_ok=True)
    tmp = OFFERS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    os.replace(tmp, OFFERS_PATH)
    with open(os.path.join(HISTORY_DIR, f"{today}.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    log(f"Saved {len(offers)} unique offers ({result['fixed_offers']} dollar offers) → {OFFERS_PATH}")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calls", type=int, default=8, help="how many feed samples to union (default 8)")
    ap.add_argument("--country", default="US")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    try:
        res = run(calls=args.calls, country=args.country, log=(lambda *a, **k: None) if args.quiet else print)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    if not args.quiet:
        print("\nTop dollar offers by value:")
        for o in [x for x in res["offers"] if x["reward_type"] == "fixed"][:12]:
            t = o["tiers"][o["best_tier_index"]]
            ratio = "free" if t["ratio"] is None else f"{t['ratio']:.2f}x"
            months = f"x{t['min_spend_months']}" if t.get('min_spend_months', 1) > 1 else "  "
            print(f"  #{o['rank']:<3} {o['merchant'][:26]:<26} {o['cashback_text']:<13} min ~${t['min_spend']:<7g} {months} {ratio:<7} [{t['min_spend_source']}] {', '.join(o['conditions']['tags'][:3])}")
