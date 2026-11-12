#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Render personalised drafts from the approved prospects + the chosen templates. Deterministic, so every user
gets the same quality the first Vizitor run had (clean names, one evidence line per company, checks).

  render <campaign> --templates <campaign>/templates/<date>.json
         ( --by-segment "Seg A=T1,Seg B=T3" | --split "T1:20,T2:rest" | --ab "T1,T4" | --all T2 )
         [--status approved] [--out drafts.json]

Templates JSON:  {"T1": {"subject": "...", "body": "...", "proof": {"IN": "...", "default": "..."}}, ...}
Placeholders (single or double braces):
  {name}           "Jitender" (only from a named business address) else "<Clean Company> team" else "team"
  {company}        cleaned company name          {city} / {where} / {inplace}  "Pune" / " in Pune" / " in Pune"
  {evidence_line}  one TRUE sentence built from the company's own site (score evidence)
  {proof}          template's proof text for the prospect's country (or default)
  {signature}      from campaign config
Evidence wording comes from <campaign>/brain/score_profile.json "phrases" (optional):
  {"phrases": {"portfolio": {"access_control": "access control"}, "buyers": {"industrial": "factories"},
               "templates": {"Facility management": "You run {portfolio} for {buyers}{where}.",
                             "default": "You install {portfolio}{brands} for {buyers}{where}."}}}
Prints a preview and refuses on: unresolved placeholders, missing email, duplicate recipient, body > 140 words.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CHANNEL_PARTNERSHIP_HOME", Path.home() / ".channel-partnership"))
COUNTRY = {"IN": "India", "AE": "the UAE", "SA": "Saudi Arabia", "NG": "Nigeria", "KE": "Kenya", "GB": "the UK", "SG": "Singapore",
           "US": "the US", "AU": "Australia", "CA": "Canada", "ZA": "South Africa", "QA": "Qatar", "OM": "Oman", "BH": "Bahrain", "KW": "Kuwait"}
CITY_FIX = {"Bombay": "Mumbai", "Bangalore": "Bengaluru", "Gurgaon": "Gurugram", "Madras": "Chennai", "Calcutta": "Kolkata"}
LEGAL = r"\b(pte\.?\s*ltd\.?|pvt\.?\s*ltd\.?|private\s+limited|private|limited|ltd\.?|llc|llp|inc\.?|gmbh|s\.?a\.?|plc)\s*$"
STUFF = re.compile(r"cctv camera|installation|supplier|dealer|near me|\bbest\b|services? in\b|\bcheap\b|\bno\.?\s?1\b", re.I)
ROLE_LOCALS = {"info", "sales", "admin", "support", "contact", "enquiry", "enquiries", "corporate", "hello", "careers", "md", "bd", "ceo",
               "team", "office", "mail", "service", "services", "marketing", "accounts", "help", "partners", "partner", "business"}
BRANDS = ["HID", "ZKTeco", "eSSL", "Honeywell", "Hikvision", "CP Plus", "Matrix", "Suprema", "Bosch", "Dahua", "Axis", "Realtime",
          "Paxton", "Genetec", "Lenel"]


def lst(xs):
    xs = [x for x in dict.fromkeys(xs) if x]
    return "" if not xs else xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def clean_company(r) -> str | None:
    n = re.split(r"\s*[|(–—]\s*|\s+-\s+|-\s+|,", r.get("company_name") or "")[0].strip()
    for _ in range(2):
        n = re.sub(LEGAL, "", n, flags=re.I).strip(" .-&")
    n = re.sub(r"\b(LLC|LLP|PTE)\b.*$", "", n).strip(" .-&")
    if not re.search(r"[A-Za-z]", n):  # non-Latin listing name -> brand from domain
        lab = (r.get("domain") or "").split(".")[0]
        return lab.replace("-", " ").title() if lab and len(lab) <= 14 else None
    if STUFF.search(n):  # keyword-stuffed Maps listing, not a real name
        return None
    while len(n) > 32 and " " in n:
        n = n.rsplit(" ", 1)[0]
    return n.title() if n.isupper() and len(n) > 4 else n


def first_name(r) -> str | None:
    email = r.get("primary_email") or ""
    local, _, dom = email.partition("@")
    if dom in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com"):
        return None
    m = re.match(r"^([a-z]{3,12})(?:[._-][a-z]+)?$", local)
    return m.group(1).capitalize() if m and m.group(1) not in ROLE_LOCALS else None


def place(r) -> str:
    c = (r.get("city_or_region") or "").split(",")[0].strip()
    return CITY_FIX.get(c, c) or COUNTRY.get((r.get("country") or "").upper(), "")


def evidence_line(r, phrases) -> str:
    b = r.get("score_breakdown") or {}
    pmap = phrases.get("portfolio", {})
    bmap = phrases.get("buyers", {"offices": "offices", "industrial": "factories", "institutions": "campuses",
                                  "hospitality_retail_banking": "hotels"})

    def groups(key):
        txt = str((b.get(key) or [0, ""])[1]).split(":", 1)[-1]
        return [g.strip() for g in txt.split(",") if g.strip() and "none" not in g]

    portfolio = [pmap.get(g, g.replace("_", " ")) for g in groups("complementary_portfolio")]
    portfolio = [p for p in portfolio if p]  # a phrase of "" means: never mention this group
    buyers = [bmap.get(g, g.replace("_", " ")) for g in groups("serves_our_buyer")][:3]
    brands = [x for x in BRANDS if x in str((b.get("partner_capacity") or [0, ""])[1])][:2]
    pl = place(r)
    tpls = phrases.get("templates", {})
    tpl = tpls.get(r.get("partner_segment") or "", tpls.get("default", "You install {portfolio}{brands} for {buyers}{where}."))
    if r.get("partner_segment") == "Facility management" and "Facility management" not in tpls:
        tpl = "You run facility services for {buyers}{where}."
        portfolio = [p for p in portfolio if "facility" not in p]
    return tpl.format(portfolio=lst(portfolio[:2]) or "security systems", brands=f" ({lst(brands)} among others)" if brands else "",
                      buyers=lst(buyers) or "commercial sites", where=f" in {pl}" if pl else "")


def plan(prospects, a) -> dict:
    if a.all:
        return {r["id"]: a.all for r in prospects}
    if a.by_segment:
        m = dict(kv.split("=", 1) for kv in a.by_segment.split(","))
        missing = {r.get("partner_segment") for r in prospects} - set(m)
        if missing and "*" not in m:
            sys.exit(f"--by-segment has no template for: {missing}. Add them or a '*=Tn' fallback.")
        return {r["id"]: m.get(r.get("partner_segment"), m.get("*")) for r in prospects}
    if a.split:
        out, i = {}, 0
        for part in a.split.split(","):
            t, n = part.split(":")
            take = len(prospects) - i if n.strip() == "rest" else int(n)
            for r in prospects[i:i + take]:
                out[r["id"]] = t.strip()
            i += take
        return out
    if a.ab:
        arms = [x.strip() for x in a.ab.split(",")]
        out, k = {}, {}
        for r in prospects:  # alternate within each segment so arms are comparable
            s = r.get("partner_segment")
            out[r["id"]] = arms[k.get(s, 0) % len(arms)]
            k[s] = k.get(s, 0) + 1
        return out
    sys.exit("choose one of --by-segment / --split / --ab / --all")


def cmd_render(a):
    cdir = ROOT / a.campaign
    cfg = json.loads((cdir / "config.json").read_text())
    sig = (cfg.get("signature") or cfg.get("sender_name") or "").replace("\\n", "\n")
    if not sig:
        sys.exit("NO_SIGNATURE: set it first (brain.py config <c> --set signature=...)")
    templates = json.loads(Path(a.templates).read_text())
    prof_p = cdir / "brain" / "score_profile.json"
    phrases = json.loads(prof_p.read_text()).get("phrases", {}) if prof_p.exists() else {}
    want = set(a.status.split(","))
    prospects = [json.loads(l) for l in (cdir / "prospects.jsonl").read_text().splitlines() if l.strip()]
    prospects = sorted([r for r in prospects if r["status"] in want], key=lambda r: -(r.get("score") or 0))
    assign = plan(prospects, a)
    out, errors, seen = [], [], set()
    for r in prospects:
        tid = assign.get(r["id"])
        t = templates.get(tid)
        if not t:
            errors.append(f"{r['company_name']}: template {tid} not found")
            continue
        to = r.get("primary_email")
        if not to:
            errors.append(f"{r['company_name']}: no email")
            continue
        if to in seen:
            errors.append(f"{r['company_name']}: duplicate recipient {to}")
            continue
        seen.add(to)
        comp = clean_company(r)
        pl = place(r)
        proof = t.get("proof", {})
        vals = {"name": first_name(r) or (f"{comp} team" if comp else "team"), "company": comp or "your team", "city": pl,
                "where": f" in {pl}" if pl else "", "inplace": f" in {pl}" if pl else "", "evidence_line": evidence_line(r, phrases),
                "ev": evidence_line(r, phrases), "proof": proof.get((r.get("country") or "").upper(), proof.get("default", "")),
                "signature": sig, "sig": sig}

        def fill(s):
            s = re.sub(r"\{\{\s*(\w+)\s*\}\}", r"{\1}", s)
            return re.sub(r"\{(\w+)\}", lambda m: str(vals[m.group(1)]) if m.group(1) in vals else m.group(0), s)

        subj, body = fill(t["subject"]), fill(t["body"])
        left = re.findall(r"\{\w+\}", subj + body)
        if left:
            errors.append(f"{r['company_name']}: unresolved {left}")
            continue
        if len(body.split()) > 140:
            errors.append(f"{r['company_name']}: body {len(body.split())} words (>140)")
            continue
        out.append({"prospect_id": r["id"], "to": to, "subject": subj, "body": body, "template_id": tid})
    dest = Path(a.out) if a.out else cdir / "runs" / "drafts.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(json.dumps({"drafts": len(out), "file": str(dest), "errors": errors,
                      "by_template": {t: sum(1 for o in out if o["template_id"] == t) for t in sorted({o["template_id"] for o in out})},
                      "preview": [f"[{o['template_id']}] {o['to']} | {o['body'].splitlines()[0]} | {o['body'].splitlines()[2][:100]}" for o in out]},
                     indent=1, ensure_ascii=False))
    if errors and not out:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("render"); s.add_argument("campaign"); s.add_argument("--templates", required=True)
    s.add_argument("--by-segment"); s.add_argument("--split"); s.add_argument("--ab"); s.add_argument("--all")
    s.add_argument("--status", default="approved"); s.add_argument("--out"); s.set_defaults(f=cmd_render)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
