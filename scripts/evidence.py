#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Evidence-based partner scoring (references/scoring.md), so every point has a quote from the company's own site.

  collect <campaign> [--status verified,risky] [--workers 6]
      fetch homepage + up to 3 internal pages (about/clients/services/solutions/products) per prospect,
      keep the sentences that prove each rubric line, store them on the prospect record
  score   <campaign> --profile <profile.json>
      apply the 100-point rubric with a product-specific keyword profile; writes score + score_breakdown

Lightweight on purpose: plain HTTP (no browser), ~6 parallel fetches, low RAM. A JS-only site yields no evidence,
which scores 0 on those lines (conservative). Claude reviews the borderline band by hand.

Profile JSON (per campaign, written by Claude from the brain; see references/scoring.md):
  {"buyer_terms": {...group: [terms]}, "portfolio_terms": {...}, "decision_terms": [...],
   "capacity_terms": [...], "brands": [...], "competitor_terms": [...], "geo_ok": ["IN","AE",...],
   "residential_terms": [...]}
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import html
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("CHANNEL_PARTNERSHIP_HOME", Path.home() / ".channel-partnership"))
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
SUBPAGE = re.compile(r"about|client|customer|service|solution|product|industr|portfolio|project|who-we", re.I)
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE  # many small-business sites have broken certs; we only read public text


def load(c):
    p = ROOT / c / "prospects.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def save(c, rows):
    p = ROOT / c / "prospects.jsonl"
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(p)


def fetch(url: str, timeout=12) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            if "html" not in (r.headers.get("Content-Type") or "html"):
                return ""
            return r.read(800_000).decode(r.headers.get_content_charset() or "utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def text_of(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(h)).strip()


def links(h: str, base: str) -> list[str]:
    host = urllib.parse.urlparse(base).hostname
    out = []
    for href in re.findall(r'href=["\']([^"\'#]+)', h, re.I):
        u = urllib.parse.urljoin(base, href)
        pu = urllib.parse.urlparse(u)
        if pu.hostname == host and SUBPAGE.search(pu.path) and not re.search(r"\.(pdf|jpg|png|zip)$", pu.path, re.I):
            out.append(u.split("?")[0])
    return list(dict.fromkeys(out))[:3]


def collect_one(r: dict) -> dict:
    site = r.get("website")
    if not site:
        return {"pages": 0, "text": ""}
    home = fetch(site)
    pages, texts = (1 if home else 0), [text_of(home)]
    for u in links(home, site):
        h = fetch(u)
        if h:
            pages += 1
            texts.append(text_of(h))
    return {"pages": pages, "text": " ".join(texts)[:120_000]}


def cmd_collect(a):
    rows = load(a.campaign)
    want = set(a.status.split(","))
    todo = [r for r in rows if r["status"] in want and not r.get("site_text_pages")]
    cache = ROOT / a.campaign / "site_text"
    cache.mkdir(exist_ok=True)
    with cf.ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(collect_one, r): r for r in todo}
        for f in cf.as_completed(futs):
            r, res = futs[f], f.result()
            r["site_text_pages"] = res["pages"]
            (cache / f"{re.sub(r'[^a-z0-9.]+', '_', r['id'].lower())}.txt").write_text(res["text"])
    save(a.campaign, rows)
    print(json.dumps({"fetched": len(todo), "no_text": sum(1 for r in todo if not r["site_text_pages"])}))


def sentences_with(text: str, terms: list[str], limit=2) -> list[str]:
    out = []
    for s in re.split(r"(?<=[.!?])\s+|\s{2,}|•|\|", text):
        s2 = s.strip()
        if 20 < len(s2) < 260 and any(re.search(rf"\b{re.escape(t)}", s2, re.I) for t in terms):
            out.append(s2)
            if len(out) >= limit:
                break
    return out


def hits(text: str, terms: list[str]) -> list[str]:
    return [t for t in terms if re.search(rf"\b{re.escape(t)}", text, re.I)]


def cmd_score(a):
    prof = json.loads(Path(a.profile).read_text())
    rows = load(a.campaign)
    cache = ROOT / a.campaign / "site_text"
    n = 0
    for r in rows:
        if r["status"] not in set(a.status.split(",")):
            continue
        f = cache / f"{re.sub(r'[^a-z0-9.]+', '_', r['id'].lower())}.txt"
        text = f.read_text() if f.exists() else ""
        b = {}
        groups = [g for g, terms in prof["buyer_terms"].items() if hits(text, terms)]
        b["serves_our_buyer"] = [{0: 0, 1: 10, 2: 18}.get(len(groups), 25),
                                 f"buyer types on site: {', '.join(groups) or 'none found'}"]
        pg = [g for g, terms in prof["portfolio_terms"].items() if hits(text + " " + (r.get("category") or ""), terms)]
        b["complementary_portfolio"] = [{0: 0, 1: 8, 2: 14}.get(len(pg), 20), f"sells: {', '.join(pg) or 'none found'}"]
        dm = hits(text, prof["decision_terms"])
        b["reaches_decision_makers"] = [15 if len(dm) >= 2 else 8 if dm else 0, f"mentions: {', '.join(dm[:4]) or 'none'}"]
        geo_ok = (r.get("country") or "").upper() in prof["geo_ok"]
        b["geographic_fit"] = [10 if geo_ok else 0, f"{r.get('city_or_region')}, {r.get('country')}"]
        cred = 0
        why = []
        if (r.get("rating") or 0) >= 4 and (r.get("reviews") or 0) >= 20:
            cred += 5; why.append(f"{r['rating']}★/{r['reviews']} reviews")
        elif (r.get("rating") or 0) >= 4:
            cred += 3; why.append(f"{r['rating']}★/{r.get('reviews')} reviews")
        if re.search(r"\b(since|established|estd\.?|founded)\s+(in\s+)?(19|20)\d\d|\bISO\s?\d{4}|\d+\+?\s+years", text, re.I):
            cred += 3; why.append("years/ISO stated")
        if re.search(r"our (clients|customers)|clientele|trusted by", text, re.I):
            cred += 2; why.append("client list")
        b["credibility"] = [min(cred, 10), "; ".join(why) or "little evidence"]
        cap = hits(text, prof["capacity_terms"]) + hits(text, prof["brands"])
        b["partner_capacity"] = [min(10, 4 * len(cap)), f"{', '.join(cap[:5]) or 'none found'}"]
        pe = next((e for e in r.get("emails", []) if e["email"] == r.get("primary_email")), {})
        b["reachability"] = [{"valid": 10, "risky": 6}.get(pe.get("verification"), 3 if r.get("business_phone") else 0),
                             f"{r.get('primary_email')} ({pe.get('verification')})"]
        score = sum(v[0] for v in b.values())
        flags = []
        comp = hits(text, prof.get("competitor_terms", []))
        if comp:
            flags.append(f"already sells/mentions: {', '.join(comp[:3])}")
        res = hits(text, prof.get("residential_terms", []))
        if res and not groups:
            flags.append("looks residential-only")
            score = min(score, 40)
        if not text:
            flags.append("site text not readable (JS-only or blocked); evidence lines scored 0")
        r["score"], r["score_breakdown"], r["flags"] = score, b, flags
        r["evidence_quotes"] = sentences_with(text, [t for ts in prof["buyer_terms"].values() for t in ts] + prof["capacity_terms"] + prof["brands"], 3)
        n += 1
    save(a.campaign, rows)
    print(json.dumps({"scored": n}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("collect"); s.add_argument("campaign"); s.add_argument("--status", default="verified,risky")
    s.add_argument("--workers", type=int, default=6); s.set_defaults(f=cmd_collect)
    s = sp.add_parser("score"); s.add_argument("campaign"); s.add_argument("--profile", required=True)
    s.add_argument("--status", default="verified,risky"); s.set_defaults(f=cmd_score)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
