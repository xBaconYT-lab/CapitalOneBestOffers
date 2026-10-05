"""Build a static copy of the site into dist/ (for GitHub Pages, Cloudflare Pages, any static host).

    python3 build_static.py          # expects data/offers.json to exist (run scraper.py first)
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(HERE, "dist")


def main():
    offers = os.path.join(HERE, "data", "offers.json")
    if not os.path.exists(offers):
        raise SystemExit("data/offers.json is missing – run `python3 scraper.py` first")
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.copytree(os.path.join(HERE, "static"), DIST)
    os.makedirs(os.path.join(DIST, "data"), exist_ok=True)
    shutil.copy2(offers, os.path.join(DIST, "data", "offers.json"))
    shutil.copy2(os.path.join(HERE, "config.json"), os.path.join(DIST, "config.json"))
    open(os.path.join(DIST, ".nojekyll"), "w").close()
    with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8") as fh:
        domain = (json.load(fh).get("custom_domain") or "").strip()
    if domain:
        with open(os.path.join(DIST, "CNAME"), "w") as fh:
            fh.write(domain + "\n")
    print(f"built {DIST}" + (f" (CNAME {domain})" if domain else ""))


if __name__ == "__main__":
    main()
