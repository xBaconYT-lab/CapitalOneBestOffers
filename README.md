# Capital One Best Dollar Offers

A small local website that pulls Capital One Shopping's public "Trending Offers" feed every day, keeps only the
**fixed-dollar cashback** offers (the "$20 back" kind, not "4% back"), and ranks them by real value:

```
value = cashback ÷ cheapest purchase that unlocks it
```

So "$20 back on a $7.99 Paramount+ plan" (2.5× back, +$12 profit) ranks above "$100 back on a $200 subscription" (0.5×),
which is still listed, just lower.

## Run it

```bash
python3 server.py
```

Then open <http://localhost:8787>. No dependencies beyond Python 3.9+.

- Data refreshes automatically when it is older than 6 hours (page load + background timer) and with the **Refresh** button.
- `PORT=9000 REFRESH_HOURS=12 FEED_CALLS=8 python3 server.py` to tweak.
- `python3 scraper.py` runs one pull from the terminal and prints the top offers.

## Where the "min spend" comes from

Capital One Shopping does not publish a minimum purchase price, so each tier's estimate is resolved in this order:

1. **Your override** – click any min-spend amount in the UI (saved in your browser).
2. **parsed** – a hard threshold stated in the offer's fine print, e.g. "Only eligible for orders over $100".
3. **curated** – `data/min_spend.json`, an editable table of entry-level prices (cheapest plan / typical first order).
4. **estimated** – keyword heuristics on the tier name ("DashPass Sign Up" → monthly subscription, "New Service Contracts" → one month of service).
5. **unknown** – a flat fallback, flagged so you know to set it.

Edit `data/min_spend.json` to add merchants; changes apply on the next refresh.

## Files

| File | Purpose |
| --- | --- |
| `scraper.py` | Fetches the feed (several sampled calls + events + carousel), merges, scores, writes `data/offers.json` and `data/history/<date>.json` |
| `minspend.py` | Min-spend resolver (fine-print parser + table + heuristics) |
| `turbo.py` | Decoder for the server-rendered feed embedded in the homepage (fallback data source) |
| `server.py` | Stdlib HTTP server: static site + `/api/offers`, `/api/refresh`, `/api/status`, `/api/history` |
| `static/` | The web page (vanilla HTML/CSS/JS) |
| `data/min_spend.json` | Editable estimate table |

## Notes

- Offers are mostly for new customers; the fine print is shown under **Details**.
- "Get offer" uses the same tracking link Capital One's own homepage uses; it is regenerated on every refresh because the links expire after about a day.
- Store and category pages on capitaloneshopping.com are region-locked, so the feed is the only data source; it is a sample of a larger pool, which is why the scraper calls it several times and merges the results.
