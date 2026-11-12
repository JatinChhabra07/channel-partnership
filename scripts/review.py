#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["openpyxl>=3.1"]
# ///
"""Human review sheet between scoring and drafting. The user decides who gets an email; the agent only recommends.

  export <campaign> [--recommend 25] [--min-score 0] [--open]
      writes <campaign>/runs/<date>/review.xlsx with 3 tabs:
        "How to use"     plain-language instructions
        "Review"         every scored company with an email, best first. Decision column is pre-filled:
                         approve (top N recommended), hold (good, next run), reject (weak/flags). User changes it.
        "Add companies"  blank rows where the user adds companies they know (company, website, email, ...)
      and remembers which rows it exported (deleted rows count as rejected).
  import <campaign> [--file review.xlsx]
      applies decisions, edited emails, deletions and added companies to the ledger; prints a summary plus the
      rejection reasons (Claude turns those into targeting lessons). Added companies come back as status
      "user_added": run verification + evidence + score on them, then they are approved (the user chose them).

Refuses to import while the file is still open in LibreOffice/Excel (lock file present): unsaved edits would be lost.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CHANNEL_PARTNERSHIP_HOME", Path.home() / ".channel-partnership"))
DECISIONS = ("approve", "hold", "reject")
REVIEWABLE = ("verified", "risky", "queued_next_run", "approved", "user_added", "discovered")
COLS = ["Decision", "Reason (if reject)", "Score", "Company", "Segment", "City", "Country", "Email", "Email check",
        "Why this score", "Flags", "Website", "Phone", "Your notes", "ID"]
ADD_COLS = ["Company", "Website", "Email", "Segment", "City", "Country", "Why you added it"]
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def ledger(c):
    return ROOT / c / "prospects.jsonl"


def load(c):
    return [json.loads(l) for l in ledger(c).read_text().splitlines() if l.strip()]


def save(c, rows):
    tmp = ledger(c).with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(ledger(c))


def today_dir(c) -> Path:
    d = ROOT / c / "runs" / dt.date.today().isoformat()
    d.mkdir(parents=True, exist_ok=True)
    return d


def why(r) -> str:
    b = r.get("score_breakdown") or {}
    parts = []
    for k, label in (("serves_our_buyer", "buyers"), ("complementary_portfolio", "sells"), ("partner_capacity", "capacity"), ("credibility", "credibility")):
        if k in b:
            parts.append(f"{label} {b[k][0]}: {str(b[k][1]).split(': ', 1)[-1][:60]}")
    return " | ".join(parts)


def default_decision(r, rank, n_rec) -> str:
    if r.get("status") in ("approved",):
        return "approve"
    s = r.get("score") or 0
    if rank <= n_rec and s >= 65:
        return "approve"
    if s >= 50:
        return "hold"
    return "reject"


def cmd_export(a):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    rows = [r for r in load(a.campaign) if r.get("status") in REVIEWABLE and r.get("primary_email") and (r.get("score") or 0) >= a.min_score]
    rows.sort(key=lambda r: -(r.get("score") or 0))
    segments = sorted({r.get("partner_segment") for r in load(a.campaign) if r.get("partner_segment")})
    wb = Workbook()
    howto = wb.active
    howto.title = "How to use"
    lines = [
        "HOW TO REVIEW (about 5 minutes)",
        "",
        "1. Go to the 'Review' tab. Every company I found with an email is there, best score first.",
        f"2. Column A 'Decision' is pre-filled with my recommendation: 'approve' = email in this run (top {a.recommend}),",
        "   'hold' = good, keep for the next run, 'reject' = do not contact.",
        "3. Change any Decision using the dropdown. If you reject one, write a short reason in column B",
        "   (e.g. 'only does home CCTV', 'competitor', 'too small'). I learn from these reasons.",
        "4. You can correct an email address in the 'Email' column, or delete a whole row (= reject).",
        "5. Know a company that should be on the list? Add it in the 'Add companies' tab (company + website or email).",
        "   I will verify its email, check its website and score it, then include it.",
        "6. Save the file (if asked, choose 'Keep current format' / .xlsx) and CLOSE it.",
        "7. Come back to the chat and say 'reviewed'.",
        "",
        "Nothing is emailed until you have reviewed the drafts in Gmail yourself.",
    ]
    for i, l in enumerate(lines, 1):
        howto.cell(i, 1, l).font = Font(bold=(i == 1), size=13 if i == 1 else 11)
    howto.column_dimensions["A"].width = 120

    ws = wb.create_sheet("Review")
    ws.append(COLS)
    fills = {"approve": "D9F2D9", "hold": "FFF4CC", "reject": "F8D7DA"}
    exported, defaults = [], {}
    for rank, r in enumerate(rows, 1):
        pe = next((e for e in r.get("emails", []) if e["email"] == r.get("primary_email")), {})
        dec = default_decision(r, rank, a.recommend)
        ws.append([dec, "", r.get("score"), r.get("company_name"), r.get("partner_segment"), (r.get("city_or_region") or "").split(",")[0],
                   r.get("country"), r.get("primary_email"), pe.get("verification", "") + (" (gmail)" if pe.get("class") == "published_freemail" else ""),
                   why(r), "; ".join(r.get("flags") or []), r.get("website"), r.get("business_phone"), "", r["id"]])
        ws.cell(ws.max_row, 1).fill = PatternFill("solid", fgColor=fills[dec])
        exported.append(r["id"])
        defaults[r["id"]] = dec
    dv = DataValidation(type="list", formula1='"approve,hold,reject"', allow_blank=False, showDropDown=False)
    ws.add_data_validation(dv)
    dv.add(f"A2:A{max(2, ws.max_row)}")
    for col, w in zip("ABCDEFGHIJKLMNO", (11, 24, 7, 38, 20, 14, 8, 36, 14, 70, 30, 34, 16, 30, 26)):
        ws.column_dimensions[col].width = w
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    add = wb.create_sheet("Add companies")
    add.append(ADD_COLS)
    for c in add[1]:
        c.font = Font(bold=True)
    sdv = DataValidation(type="list", formula1='"' + ",".join(s.replace(",", " ") for s in segments)[:250] + '"', allow_blank=True)
    add.add_data_validation(sdv)
    sdv.add("D2:D200")
    for col, w in zip("ABCDEFG", (34, 34, 34, 22, 16, 10, 40)):
        add.column_dimensions[col].width = w

    out = Path(a.out) if a.out else today_dir(a.campaign) / "review.xlsx"
    wb.save(out)
    (out.parent / "review_export.json").write_text(json.dumps({"file": str(out), "ids": exported, "defaults": defaults, "exported_at": dt.datetime.now().isoformat(timespec="seconds")}))
    counts = {d: 0 for d in DECISIONS}
    for rank, r in enumerate(rows, 1):
        counts[default_decision(r, rank, a.recommend)] += 1
    opened = False
    if a.open:
        for opener in ("xdg-open", "open", "wslview"):
            if shutil.which(opener):
                opened = subprocess.Popen([opener, str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) is not None
                break
    print(json.dumps({"sheet": str(out), "rows": len(rows), "prefilled": counts, "opened": opened}, indent=2))


def _lock_files(p: Path):
    return [x for x in p.parent.glob(f".~lock.{p.name}#")] + [x for x in p.parent.glob(f"~${p.name}")]


def cmd_import(a):
    from openpyxl import load_workbook

    exp_p = None
    if a.file:
        f = Path(a.file)
    else:
        cands = sorted((ROOT / a.campaign / "runs").glob("*/review.xlsx"), key=lambda p: p.stat().st_mtime)
        if not cands:
            sys.exit("NO_SHEET: run export first")
        f = cands[-1]
    if _lock_files(f):
        sys.exit("FILE_STILL_OPEN: the sheet is still open in LibreOffice/Excel. Ask the user to save and close it, then import again.")
    exp_p = f.parent / "review_export.json"
    exp = json.loads(exp_p.read_text()) if exp_p.exists() else {}
    exported, defaults = set(exp.get("ids", [])), exp.get("defaults", {})
    overrides = []  # where the user disagreed with the agent's recommendation: the real training signal
    wb = load_workbook(f, data_only=True)
    ws = wb["Review"]
    hdr = [str(c.value or "").strip() for c in ws[1]]
    ix = {h: i for i, h in enumerate(hdr)}
    for need in ("Decision", "ID", "Email"):
        if need not in ix:
            sys.exit(f"BAD_SHEET: column '{need}' missing; was the header row edited?")
    rows = load(a.campaign)
    by_id = {r["id"]: r for r in rows}
    seen, summary, reasons, problems = set(), {"approve": 0, "hold": 0, "reject": 0, "deleted_rows": 0, "email_edits": 0, "added": 0}, [], []
    now = dt.datetime.now().isoformat(timespec="seconds")
    for row in ws.iter_rows(min_row=2, values_only=True):
        rid = row[ix["ID"]]
        if not rid:
            continue
        r = by_id.get(str(rid))
        if not r:
            problems.append(f"unknown ID {rid} (row ignored)")
            continue
        seen.add(r["id"])
        dec = str(row[ix["Decision"]] or "").strip().lower()
        if dec not in DECISIONS:
            problems.append(f"{r['company_name']}: decision '{dec}' not understood, kept as hold")
            dec = "hold"
        new_email = str(row[ix["Email"]] or "").strip().lower()
        if new_email and new_email != (r.get("primary_email") or ""):
            if EMAIL_RE.match(new_email):
                r.setdefault("emails", []).insert(0, {"email": new_email, "class": "user_provided", "kind": "user", "source": "review sheet", "verification": "unverified"})
                r["primary_email"] = new_email
                r["email_edited_by_user"] = True
                summary["email_edits"] += 1
            else:
                problems.append(f"{r['company_name']}: '{new_email}' is not a valid email, kept the old one")
        note = row[ix["Your notes"]] if "Your notes" in ix else None
        if note:
            r["user_notes"] = str(note)
        reason = str(row[ix["Reason (if reject)"]] or "").strip() if "Reason (if reject)" in ix else ""
        r["status"] = {"approve": "approved", "hold": "queued_next_run", "reject": "rejected"}[dec]
        r.setdefault("history", []).append({"ts": now, "status": r["status"], "note": f"review sheet{': ' + reason if reason else ''}"})
        summary[dec] += 1
        rec = defaults.get(r["id"])
        if rec and rec != dec:
            overrides.append({"company": r["company_name"], "score": r.get("score"), "recommended": rec, "user_chose": dec,
                              "reason": reason or None, "segment": r.get("partner_segment"), "city": r.get("city_or_region")})
        if dec == "reject" and (reason or rec != "reject"):  # only the user's own rejections are feedback
            reasons.append({"company": r["company_name"], "segment": r.get("partner_segment"), "city": r.get("city_or_region"),
                            "score": r.get("score"), "reason": reason or "(no reason given)"})
    for rid in exported - seen:
        r = by_id.get(rid)
        if r:
            r["status"] = "rejected"
            r.setdefault("history", []).append({"ts": now, "status": "rejected", "note": "row deleted in review sheet"})
            summary["deleted_rows"] += 1
            reasons.append({"company": r["company_name"], "segment": r.get("partner_segment"), "city": r.get("city_or_region"),
                            "score": r.get("score"), "reason": "row deleted (no reason)"})
    # added companies
    if "Add companies" in wb.sheetnames:
        add = wb["Add companies"]
        ah = [str(c.value or "").strip() for c in add[1]]
        ai = {h: i for i, h in enumerate(ah)}
        doms = {r.get("domain") for r in rows if r.get("domain")}
        sys.path.insert(0, str(Path(__file__).parent))
        from prospects import reg_domain  # same domain logic as ingest

        for row in add.iter_rows(min_row=2, values_only=True):
            get = lambda k: str(row[ai[k]] or "").strip() if k in ai and ai[k] < len(row) else ""  # noqa: E731
            name, site, email = get("Company"), get("Website"), get("Email").lower()
            if not (name or site or email):
                continue
            if email and not EMAIL_RE.match(email):
                problems.append(f"added '{name or site}': '{email}' is not a valid email")
                email = ""
            if not site and not email:
                problems.append(f"added '{name}': needs a website or an email, skipped")
                continue
            if site and not site.startswith("http"):
                site = "https://" + site
            if not site and email and email.split("@")[1] not in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com"):
                site = "https://" + email.split("@")[1]  # so evidence collection can read their site
            dom = reg_domain(site) if site else reg_domain(email.split("@")[1])
            if dom in doms:
                problems.append(f"added '{name or dom}': already in the list (domain {dom}), skipped")
                continue
            rec = {"id": dom or name[:60], "company_name": name or dom, "website": site or None, "domain": dom,
                   "partner_segment": get("Segment") or None, "city_or_region": get("City") or None, "country": (get("Country") or "").upper() or None,
                   "emails": ([{"email": email, "class": "user_provided", "kind": "user", "source": "review sheet", "verification": "unverified"}] if email else []),
                   "primary_email": email or None, "evidence_urls": [u for u in (site,) if u], "source_query": "user added in review sheet",
                   "user_notes": get("Why you added it") or None, "research_date": dt.date.today().isoformat(),
                   "status": "user_added", "score": None, "human_approval_required": True,
                   "history": [{"ts": now, "status": "user_added", "note": "added in review sheet"}]}
            rows.append(rec)
            doms.add(dom)
            summary["added"] += 1
    save(a.campaign, rows)
    print(json.dumps({"sheet": str(f), "summary": summary, "user_overrides": overrides, "rejection_reasons": reasons, "problems": problems,
                      "next": ("verify + evidence + score the user_added companies, then approve them" if summary["added"] else "draft for approved companies")},
                     indent=1, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("export"); s.add_argument("campaign"); s.add_argument("--recommend", type=int, default=25)
    s.add_argument("--min-score", type=int, default=0); s.add_argument("--out"); s.add_argument("--open", action="store_true"); s.set_defaults(f=cmd_export)
    s = sp.add_parser("import"); s.add_argument("campaign"); s.add_argument("--file"); s.set_defaults(f=cmd_import)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
