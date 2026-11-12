#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["dnspython>=2.6"]
# ///
"""Prospect ledger: ingest -> clean -> dedupe -> verify -> review -> hand to drafting.

  ingest   <campaign> --file maps.json --segment "CCTV/security" [--country IN --city Pune --source-query "..."]
  mx       <campaign>                      # free DNS MX check on every unverified email domain
  verify-export <campaign> --out emails.json   # emails still needing paid verification
  verify-import <campaign> --file verifier_output.json
  update   <campaign> --file patch.json    # [{"id":..., "score":.., "score_breakdown":{..}, "status":..}, ...]
  table    <campaign> [--status verified,risky] [--limit 50] [--csv out.csv]
  set      <campaign> --status approved|rejected|... ids...
  stats    <campaign>

Email policy (see references/compliance.md): we keep only addresses the BUSINESS ITSELF
publishes (its website / its Maps listing). We never guess patterns, never buy enrichment of
individuals, and drop third-party addresses (web agencies, plugin vendors, sentry, wix...).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("CHANNEL_PARTNERSHIP_HOME", Path.home() / ".channel-partnership"))

FREEMAIL = {"gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in", "hotmail.com", "outlook.com", "live.com",
            "rediffmail.com", "ymail.com", "icloud.com", "aol.com", "zoho.com", "zohomail.in", "protonmail.com", "proton.me", "gmx.com", "mail.com"}
ROLE = {"info", "sales", "contact", "hello", "enquiry", "enquiries", "inquiry", "support", "admin", "office", "business",
        "partners", "partner", "partnerships", "marketing", "bd", "biz", "team", "mail", "care", "service", "services", "projects", "ceo", "director", "md"}
ROLE_RANK = {"partners": 0, "partner": 0, "partnerships": 0, "bd": 1, "business": 1, "sales": 1, "director": 1, "md": 1, "ceo": 1,
             "info": 2, "contact": 2, "hello": 2, "enquiry": 2, "enquiries": 2, "inquiry": 2, "office": 3, "marketing": 3,
             "admin": 4, "support": 6, "care": 6, "service": 5, "services": 5}
JUNK = re.compile(r"(\.(png|jpe?g|gif|webp|svg)$)|example\.|sentry|wixpress|domain\.com|email\.com|yourname|yourmail|"
                  r"noreply|no-reply|donotreply|@2x|u003e|\.local$|test@|user@|name@|privacy@|abuse@|webmaster@|postmaster@|careers?@|jobs?@|hr@|recruit\w*@|resume@|cv@|"
                  r"@(ipsum|domainname|company|yourdomain|yourcompany|mysite|website|gmai|gmal|gamil|yaho)\.|themes?\.(net|com)$", re.I)
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def ledger(c):
    return ROOT / c / "prospects.jsonl"


def load(c):
    p = ledger(c)
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def save(c, rows):
    p = ledger(c)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(p)


def suppressed():
    s = set()
    for f in ROOT.glob("*/suppression.txt"):
        s |= {ln.split("\t")[0].strip().lower() for ln in f.read_text().splitlines() if ln.strip()}
    return s


def reg_domain(url_or_host: str | None) -> str | None:
    if not url_or_host:
        return None
    h = urlparse(url_or_host if "//" in url_or_host else "//" + url_or_host).hostname or ""
    h = h.lower().removeprefix("www.")
    parts = h.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "net", "org", "gov", "ac", "edu"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else h or None


def classify(email: str, site_dom: str | None) -> tuple[str, str]:
    e = email.strip().lower()
    if not EMAIL_RE.match(e) or JUNK.search(e):
        return "junk", ""
    local, dom = e.split("@", 1)
    kind = "role" if re.sub(r"[^a-z]", "", local) in ROLE or local in ROLE else "named"
    if site_dom and reg_domain(dom) == site_dom:
        return "business", kind
    if dom in FREEMAIL:
        return "published_freemail", kind
    if site_dom and _same_brand(reg_domain(dom) or dom, site_dom):
        return "business", kind  # company's own sister domain: .ae vs .sa, trivest-group vs trivestgroup
    return "third_party", kind


def _label(d: str) -> str:
    return re.sub(r"[^a-z0-9]", "", d.split(".")[0])


def _same_brand(a: str, b: str) -> bool:
    """Same company, different domain? Only when the brand label clearly matches. Group or partner
    domains with a different name stay third-party: a wrong guess means emailing the wrong company."""
    import difflib

    la, lb = _label(a), _label(b)
    if len(la) < 4 or len(lb) < 4:
        return False
    if la == lb:
        return True
    short, long_ = sorted((la, lb), key=len)
    if len(short) >= 6 and long_.startswith(short):
        return True
    return difflib.SequenceMatcher(None, la, lb).ratio() >= 0.85


def rank(email: dict) -> tuple:
    cls_rank = {"business": 0, "published_freemail": 2}.get(email["class"], 9)
    local = email["email"].split("@")[0]
    return (cls_rank, ROLE_RANK.get(local, 2 if email["kind"] == "named" else 4))


def cmd_ingest(a):
    items = json.loads(Path(a.file).read_text())
    rows = load(a.campaign)
    by_dom = {r["domain"]: r for r in rows if r.get("domain")}
    by_place = {r.get("place_id"): r for r in rows if r.get("place_id")}
    sup = suppressed()
    stats = Counter()
    for it in items:
        if it.get("permanentlyClosed") or it.get("temporarilyClosed"):
            stats["closed"] += 1
            continue
        site = it.get("website")
        dom = reg_domain(site)
        if dom and any(x in dom for x in ("facebook.com", "instagram.com", "justdial.com", "indiamart.com", "linkedin.com", "google.com", "wa.me", "sulekha.com")):
            dom = None  # a directory page is not the company's own site
        pid = it.get("placeId")
        if (dom and dom in by_dom) or (pid and pid in by_place):
            stats["duplicate"] += 1
            continue
        emails, seen = [], set()
        for e in (it.get("emails") or []):
            e = e.strip().lower()
            if e in seen:
                continue
            seen.add(e)
            cls, kind = classify(e, dom)
            if cls in ("junk", "third_party"):
                stats[f"email_dropped_{cls}"] += 1
                continue
            if e in sup or e.split("@")[1] in sup:
                stats["email_suppressed"] += 1
                continue
            emails.append({"email": e, "class": cls, "kind": kind, "source": site or it.get("url"), "verification": "unverified"})
        emails.sort(key=rank)
        rec = {
            "id": (dom or pid or it.get("title", "x"))[:60],
            "company_name": it.get("title"),
            "website": site if dom else None,
            "domain": dom,
            "place_id": pid,
            "maps_url": it.get("url"),
            "category": it.get("categoryName"),
            "categories": it.get("categories"),
            "address": it.get("address"),
            "city_or_region": it.get("city") or a.city,
            "state": it.get("state"),
            "country": it.get("countryCode") or a.country,
            "business_phone": it.get("phone") or it.get("phoneUnformatted"),
            "rating": it.get("totalScore"),
            "reviews": it.get("reviewsCount"),
            "linkedin": (it.get("linkedIns") or [None])[0],
            "partner_segment": a.segment,
            "emails": emails,
            "primary_email": emails[0]["email"] if emails else None,
            "evidence_urls": [u for u in (site, it.get("url")) if u],
            "source_query": a.source_query,
            "research_date": now()[:10],
            "status": "discovered" if emails else "no_email",
            "score": None,
            "human_approval_required": True,
        }
        rows.append(rec)
        if dom:
            by_dom[dom] = rec
        if pid:
            by_place[pid] = rec
        stats["added"] += 1
        stats["with_email" if emails else "without_email"] += 1
    save(a.campaign, rows)
    print(json.dumps(dict(stats), indent=2))


def cmd_mx(a):
    import dns.resolver

    rows = load(a.campaign)
    cache = {}
    n = 0
    for r in rows:
        for e in r.get("emails", []):
            if e["verification"] != "unverified":
                continue
            d = e["email"].split("@")[1]
            if d not in cache:
                try:
                    cache[d] = bool(dns.resolver.resolve(d, "MX", lifetime=8))
                except Exception:  # noqa: BLE001
                    cache[d] = False
            if not cache[d]:
                e["verification"] = "invalid_no_mx"
                n += 1
        good = [e for e in r.get("emails", []) if not e["verification"].startswith("invalid")]
        r["primary_email"] = good[0]["email"] if good else None
        if not good and r["status"] == "discovered":
            r["status"] = "no_email"
    save(a.campaign, rows)
    print(json.dumps({"domains_checked": len(cache), "emails_invalidated": n}))


def cmd_verify_export(a):
    rows = load(a.campaign)
    # discovered = fresh from discovery; user_added / approved = companies or emails the user added or edited in review
    out = sorted({r["primary_email"] for r in rows if r.get("primary_email") and r["status"] in ("discovered", "user_added", "approved", "queued_next_run")
                  and next((e for e in r["emails"] if e["email"] == r["primary_email"]), {}).get("verification") == "unverified"})
    Path(a.out).write_text(json.dumps({"emails": out}, indent=1))
    print(json.dumps({"emails_to_verify": len(out), "file": a.out}))


def _norm_verdict(item: dict) -> str:
    # Prefer the verifier's own status field (bounceverify: valid / risky / unknown / invalid).
    st = str(item.get("status") or item.get("result") or "").lower().replace("-", "_")
    known = {"valid": "valid", "deliverable": "valid", "ok": "valid", "safe": "valid",
             "risky": "risky", "unknown": "risky", "catch_all": "risky", "accept_all": "risky",
             "invalid": "invalid", "undeliverable": "invalid", "disposable": "invalid", "spamtrap": "invalid"}
    if st in known:
        return known[st]
    blob =" ".join(str(item.get(k, "")) for k in ("result", "status", "verdict", "state", "deliverability", "reason")).lower()
    if any(w in blob for w in ("undeliverable", "invalid", "bounce", "does not exist", "disposable", "syntax")):
        return "invalid"
    if any(w in blob for w in ("catch", "accept_all", "accept-all", "risky", "unknown", "role")) and "deliverable" not in blob.replace("undeliverable", ""):
        return "risky"
    if any(w in blob for w in ("deliverable", "valid", "ok", "safe")):
        return "valid"
    if item.get("isValid") is True or item.get("valid") is True:
        return "valid"
    if item.get("isValid") is False or item.get("valid") is False:
        return "invalid"
    return "risky"


def cmd_verify_import(a):
    data = json.loads(Path(a.file).read_text())
    verdicts = {}
    for it in data:
        e = (it.get("email") or it.get("address") or it.get("emailAddress") or "").lower()
        if e:
            verdicts[e] = (_norm_verdict(it), it)
    rows = load(a.campaign)
    c = Counter()
    for r in rows:
        for e in r.get("emails", []):
            if e["email"] in verdicts:
                e["verification"], raw = verdicts[e["email"]]
                e["verification_raw"] = {k: raw.get(k) for k in list(raw)[:8]}
                c[e["verification"]] += 1
        ok = [e for e in r.get("emails", []) if e["verification"] in ("valid", "risky", "unverified")]
        ok.sort(key=lambda e: ({"valid": 0, "risky": 1, "unverified": 2}[e["verification"]], rank(e)))
        r["primary_email"] = ok[0]["email"] if ok else None
        if r["status"] in ("discovered", "no_email", "verified", "risky"):
            pv = ok[0]["verification"] if ok else None
            r["status"] = {"valid": "verified", "risky": "risky"}.get(pv, "no_email" if not ok else "discovered")
    save(a.campaign, rows)
    print(json.dumps(dict(c)))


def cmd_update(a):
    patch = {p["id"]: p for p in json.loads(Path(a.file).read_text())}
    rows = load(a.campaign)
    n = 0
    for r in rows:
        if r["id"] in patch:
            r.update({k: v for k, v in patch[r["id"]].items() if k != "id"})
            n += 1
    save(a.campaign, rows)
    print(json.dumps({"updated": n, "unknown_ids": sorted(set(patch) - {r['id'] for r in rows})}))


def cmd_set(a):
    rows = load(a.campaign)
    ids = set(a.ids)
    for r in rows:
        if r["id"] in ids or (a.all_status and r["status"] == a.all_status):
            r["status"] = a.status
            r.setdefault("history", []).append({"ts": now(), "status": a.status, "note": a.note})
    save(a.campaign, rows)
    print(json.dumps({"set": a.status, "n": len(ids) if ids else "by status"}))


def cmd_table(a):
    rows = load(a.campaign)
    want = set(a.status.split(",")) if a.status else None
    sel = [r for r in rows if not want or r["status"] in want]
    sel.sort(key=lambda r: -(r.get("score") or 0))
    sel = sel[: a.limit]
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["#", "id", "company", "segment", "city", "country", "email", "email_class", "verification", "phone", "score", "website", "status"])
            for i, r in enumerate(sel, 1):
                pe = next((e for e in r["emails"] if e["email"] == r.get("primary_email")), {})
                w.writerow([i, r["id"], r["company_name"], r.get("partner_segment"), r.get("city_or_region"), r.get("country"), r.get("primary_email"),
                            pe.get("class"), pe.get("verification"), r.get("business_phone"), r.get("score"), r.get("website"), r["status"]])
        print(f"wrote {len(sel)} rows to {a.csv}")
        return
    print("| # | Company | Segment | City | Email | Check | Score | Website |")
    print("|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(sel, 1):
        pe = next((e for e in r["emails"] if e["email"] == r.get("primary_email")), {})
        flag = pe.get("verification", "-") + (" (freemail)" if pe.get("class") == "published_freemail" else "")
        print(f"| {i} | {r['company_name']} | {r.get('partner_segment') or ''} | {r.get('city_or_region') or ''} | {r.get('primary_email') or '—'} | {flag} | {r.get('score') if r.get('score') is not None else '—'} | {r.get('domain') or '—'} |")


def cmd_stats(a):
    rows = load(a.campaign)
    print(json.dumps({"total": len(rows), "by_status": Counter(r["status"] for r in rows),
                      "by_segment": Counter(r.get("partner_segment") for r in rows),
                      "by_city": Counter(r.get("city_or_region") for r in rows)}, indent=2, default=dict))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("ingest"); s.add_argument("campaign"); s.add_argument("--file", required=True); s.add_argument("--segment", required=True)
    s.add_argument("--country"); s.add_argument("--city"); s.add_argument("--source-query"); s.set_defaults(f=cmd_ingest)
    s = sp.add_parser("mx"); s.add_argument("campaign"); s.set_defaults(f=cmd_mx)
    s = sp.add_parser("verify-export"); s.add_argument("campaign"); s.add_argument("--out", required=True); s.set_defaults(f=cmd_verify_export)
    s = sp.add_parser("verify-import"); s.add_argument("campaign"); s.add_argument("--file", required=True); s.set_defaults(f=cmd_verify_import)
    s = sp.add_parser("update"); s.add_argument("campaign"); s.add_argument("--file", required=True); s.set_defaults(f=cmd_update)
    s = sp.add_parser("set"); s.add_argument("campaign"); s.add_argument("--status", required=True); s.add_argument("--note")
    s.add_argument("--all-status"); s.add_argument("ids", nargs="*"); s.set_defaults(f=cmd_set)
    s = sp.add_parser("table"); s.add_argument("campaign"); s.add_argument("--status"); s.add_argument("--limit", type=int, default=100)
    s.add_argument("--csv"); s.set_defaults(f=cmd_table)
    s = sp.add_parser("stats"); s.add_argument("campaign"); s.set_defaults(f=cmd_stats)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
