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

## Put it online (so others can use it)

The site is static-friendly: `build_static.py` copies the page plus `data/offers.json` into `dist/`, and
`.github/workflows/pages.yml` re-runs the scraper **every 6 hours** on GitHub Actions and publishes `dist/` to GitHub Pages.

1. Push this folder to a GitHub repository (public or private; Pages on private repos needs a paid plan).
2. In the repo: **Settings → Pages → Source: GitHub Actions**. The first workflow run publishes the site at
   `https://<user>.github.io/<repo>/`.
3. Custom domain, e.g. `cap1shop.tintax.org`: in **Settings → Pages → Custom domain** enter the host name, then add a
   DNS record at your DNS provider: `CNAME cap1shop → <user>.github.io` (on Cloudflare the quickest path to HTTPS is to set the record to **Proxied** and SSL/TLS mode
   to **Full**: Cloudflare then serves its own certificate immediately. With "DNS only" you instead wait for GitHub to
   issue a certificate, then tick *Enforce HTTPS*.) `config.json` → `custom_domain` writes the matching CNAME file.
4. `config.json` → `referral_url`: paste your Capital One Shopping referral link and the "Join" button in the claim
   dialog will use it.

Alternatives: `Dockerfile` runs the dynamic server (with the Refresh button) on Fly.io / Render / a VPS, or run
`server.py` on a Mac and expose it with a Cloudflare Tunnel.

### Visitors never leave through our link

"Get offer" opens a dialog that sends the visitor to the merchant's page **on capitaloneshopping.com**
(`/s/<domain>/coupon`) where they press *Get this offer* while signed in to their own account. The tracking links the
feed hands out are tied to the session that fetched them, so they are not used for visitors.

## Your Capital One *Offers* (card-linked) too

Capital One runs two programs. **Capital One Shopping** (capitaloneshopping.com) is the free portal this site scrapes.
**Capital One Offers** (capitaloneoffers.com/feed) are card-linked deals for cardholders, behind the bank login and
personalised per card, so no server can fetch them. The **＋ My card offers** button therefore lets you paste them in from your own browser:

- **Paste**: select-all / copy the Offers page and paste it into the dialog.

Imported offers are tagged "Your card offer", ranked by the same rule (min spend from `data/min_spend.json`, no fine
print is available), and stored in `localStorage` only. "Get offer" on them points to capitaloneoffers.com where you
press *Add to card*.

## Where the "min spend" comes from

Capital One Shopping does not publish a minimum purchase price, so each tier's estimate is resolved in this order:

1. **Your override** – click any min-spend amount in the UI (saved in your browser).
2. **parsed** – a hard threshold stated in the offer's fine print, e.g. "Only eligible for orders over $100".
   The fine print is also read for commitments: "subscribe for 2 consecutive months" or "stay connected for another
   40 days" multiplies the monthly estimate by that many months, and requirements such as "new customers only" or
   "devices must be $400+" are shown as tags on the card (`minspend.parse_conditions`).
3. **curated** – `data/min_spend.json`, an editable table of entry-level prices (cheapest plan / typical first order).
4. **estimated** – keyword heuristics on the tier name ("DashPass Sign Up" → monthly subscription, "New Service Contracts" → one month of service).
5. **unknown** – a flat fallback, flagged so you know to set it.

Edit `data/min_spend.json` to add merchants; changes apply on the next refresh.

## Files

| File | Purpose |
| --- | --- |
| `scraper.py` | Fetches the feed (several sampled calls + events + carousel), merges, scores, writes `data/offers.json` and `data/history/<date>.json` |
| `minspend.py` | Min-spend resolver: fine-print parser (thresholds, commitments, requirement tags) + table + heuristics |
| `build_static.py` | Builds `dist/` for static hosting (GitHub Pages, Cloudflare Pages…) |
| `.github/workflows/pages.yml` | Scheduled scrape + publish to GitHub Pages every 6 hours |
| `config.json` | Site name, referral link, custom domain |
| `Dockerfile` | Container for the dynamic server |
| `turbo.py` | Decoder for the server-rendered feed embedded in the homepage (fallback data source) |
| `server.py` | Stdlib HTTP server: static site + `/api/offers`, `/api/refresh`, `/api/status`, `/api/history` |
| `static/` | The web page (vanilla HTML/CSS/JS) |
| `data/min_spend.json` | Editable estimate table |

## Notes

- Offers are mostly for new customers; the fine print is shown under **Details**.
- "Get offer" uses the same tracking link Capital One's own homepage uses; it is regenerated on every refresh because the links expire after about a day.
- Store and category pages on capitaloneshopping.com are region-locked, so the feed is the only data source; it is a sample of a larger pool, which is why the scraper calls it several times and merges the results.
