#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Compare what the agent drafted with what the user actually sent. This is the training signal.

  report    --campaign c            diff every sent-but-not-yet-learned draft; print a structured
                                    report for Claude to turn into lessons; append run metrics
  mark-sent --campaign c --id ID --file sent.txt   (outbox mode: the user pastes what they sent;
                                    first line "Subject: ..." optional)
  autonomy  --campaign c            is the agent good enough to be offered sending rights?

Edit ratio = 1 - similarity(draft body, sent body). 0 = sent untouched, 1 = fully rewritten.
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("CHANNEL_PARTNERSHIP_HOME", Path.home() / ".channel-partnership"))


def load(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def save(p, rows):
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(p)


def norm(t: str) -> str:
    t = re.sub(r"\r", "", t or "")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def sentences(t: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", norm(t))
    return [p.strip() for p in parts if p.strip()]


def edit_ratio(a: str, b: str) -> float:
    return round(1 - difflib.SequenceMatcher(None, norm(a), norm(b)).ratio(), 3)


GREETING = re.compile(r"^(hi|hello|hey|dear|greetings|namaste)\b.{0,60}$", re.I)


def _opening(sents: list[str]) -> str:
    """First real sentence, skipping the greeting line."""
    body = [s for s in sents if not GREETING.match(s)]
    return body[0].lower() if body else ""


def diff_one(r: dict) -> dict:
    d, s = r.get("body", ""), r.get("sent_body", "")
    ds, ss = sentences(d), sentences(s)
    sm = difflib.SequenceMatcher(None, ds, ss)
    removed, added, rewritten = [], [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "delete":
            removed += ds[i1:i2]
        elif op == "insert":
            added += ss[j1:j2]
        elif op == "replace":
            for k in range(max(i2 - i1, j2 - j1)):
                a = ds[i1 + k] if i1 + k < i2 else ""
                b = ss[j1 + k] if j1 + k < j2 else ""
                if a and b:
                    rewritten.append({"from": a, "to": b})
                elif a:
                    removed.append(a)
                else:
                    added.append(b)
    return {
        "draft_id": r["id"], "to": r["to"], "template_id": r.get("template_id"),
        "edit_ratio": edit_ratio(d, s),
        "subject": None if (r.get("sent_subject") or r["subject"]).strip() == r["subject"].strip()
        else {"from": r["subject"], "to": r.get("sent_subject")},
        "words": {"draft": len(d.split()), "sent": len(s.split())},
        "opening_changed": _opening(ds) != _opening(ss),
        "removed": removed, "added": added, "rewritten": rewritten,
    }


def cmd_report(a):
    p = ROOT / a.campaign / "drafts.jsonl"
    rows = load(p)
    todo = [r for r in rows if r.get("status") in ("sent", "replied", "bounced", "opted_out") and r.get("sent_body") is not None and not r.get("learned")]
    deleted = [r for r in rows if r.get("status") == "deleted" and not r.get("learned")]
    diffs = [diff_one(r) for r in todo if r.get("sent_by") != "agent"]
    for r in todo + deleted:
        r["learned"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    save(p, rows)

    ratios = [x["edit_ratio"] for x in diffs]
    by_t = defaultdict(list)
    for x in diffs:
        by_t[x["template_id"]].append(x["edit_ratio"])
    # Recurring edits across emails are the real lessons; one-offs are usually prospect-specific.
    # Template sentences are personalised per prospect, so exact matching misses the pattern
    # ("I came across Acme..." vs "I came across Beta..."): cluster fuzzily, count distinct emails.
    def clusters(pairs):  # pairs: [(email_idx, text, payload)]
        groups: list[dict] = []
        for idx, text, payload in pairs:
            for g in groups:
                if difflib.SequenceMatcher(None, g["rep"].lower(), text.lower()).ratio() >= 0.6:
                    g["emails"].add(idx)
                    g["examples"].append(payload)
                    break
            else:
                groups.append({"rep": text, "emails": {idx}, "examples": [payload]})
        return sorted(({"pattern": g["rep"], "emails": len(g["emails"]), "examples": g["examples"][:3]}
                       for g in groups if len(g["emails"]) > 1), key=lambda g: -g["emails"])[:15]

    rem = clusters([(i, s, s) for i, x in enumerate(diffs) for s in x["removed"]])
    add = clusters([(i, s, s) for i, x in enumerate(diffs) for s in x["added"]])
    rw = clusters([(i, y["from"], y) for i, x in enumerate(diffs) for y in x["rewritten"]])
    subj = clusters([(i, x["subject"]["from"], x["subject"]) for i, x in enumerate(diffs) if x["subject"]])
    metrics = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sent_by_user": len(diffs), "deleted_drafts": len(deleted),
        "median_edit_ratio": round(statistics.median(ratios), 3) if ratios else None,
        "untouched": sum(1 for r in ratios if r < 0.02),
        "by_template": {k: {"n": len(v), "median_edit": round(statistics.median(v), 3)} for k, v in by_t.items()},
    }
    if diffs or deleted:
        with (ROOT / a.campaign / "metrics.jsonl").open("a") as f:
            f.write(json.dumps(metrics) + "\n")
    print(json.dumps({
        "metrics": metrics,
        "recurring": {
            "removed_in_multiple_emails": rem,
            "added_in_multiple_emails": add,
            "rewritten_in_multiple_emails": rw,
            "subject_changed_in_multiple_emails": subj,
            "shorter_in_most_emails": sum(x["words"]["sent"] < x["words"]["draft"] * 0.9 for x in diffs) > len(diffs) / 2 if diffs else False,
            "opening_changed_in_most_emails": sum(x["opening_changed"] for x in diffs) > len(diffs) / 2 if diffs else False,
        },
        "deleted_drafts": [{"to": r["to"], "prospect_id": r.get("prospect_id"), "template_id": r.get("template_id"), "subject": r["subject"]} for r in deleted],
        "per_email": diffs[: a.max_items],
    }, indent=1, ensure_ascii=False))


def cmd_mark_sent(a):
    p = ROOT / a.campaign / "drafts.jsonl"
    rows = load(p)
    txt = Path(a.file).read_text()
    subj = None
    m = re.match(r"\s*Subject:\s*(.+)\n", txt)
    if m:
        subj, txt = m.group(1).strip(), txt[m.end():]
    for r in rows:
        if r["id"] == a.id:
            r |= {"status": "sent", "sent_body": txt.strip(), "sent_subject": subj or r["subject"],
                  "sent_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    save(p, rows)
    print(json.dumps({"marked_sent": a.id}))


def cmd_autonomy(a):
    rows = load(ROOT / a.campaign / "drafts.jsonl")
    cfg_p = ROOT / a.campaign / "config.json"
    cfg = json.loads(cfg_p.read_text()) if cfg_p.exists() else {}
    user_sent = [r for r in rows if r.get("sent_body") is not None and r.get("sent_by") != "agent"]
    last = sorted(user_sent, key=lambda r: r.get("sent_at") or "")[-a.window:]
    decided = [r for r in rows if r.get("status") in ("sent", "replied", "bounced", "opted_out", "deleted")]
    recent_decided = sorted(decided, key=lambda r: r.get("resolved") or r.get("sent_at") or "")[-a.window:]
    runs = len({r.get("run") for r in user_sent})
    ratios = [edit_ratio(r["body"], r["sent_body"]) for r in last]
    med = statistics.median(ratios) if ratios else 1.0
    del_rate = sum(r["status"] == "deleted" for r in recent_decided) / max(1, len(recent_decided))
    sent_all = [r for r in rows if r.get("status") in ("sent", "replied", "bounced", "opted_out")]
    bounce = sum(r["status"] == "bounced" for r in sent_all) / max(1, len(sent_all))
    gates = {
        f"at least {a.window} user-reviewed sends": (len(last) >= a.window, len(last)),
        "at least 3 separate runs": (runs >= 3, runs),
        "median edit ratio <= 0.05": (med <= 0.05, round(med, 3)),
        "deleted-draft rate <= 10%": (del_rate <= 0.10, round(del_rate, 3)),
        "bounce rate <= 2%": (bounce <= 0.02, round(bounce, 3)),
    }
    ready = all(v[0] for v in gates.values())
    print(json.dumps({"current_autonomy": cfg.get("autonomy", "draft_only"),
                      "gates": {k: {"pass": v[0], "value": v[1]} for k, v in gates.items()},
                      "eligible_for_next_level": ready,
                      "advice": "Offer the user the next autonomy level (they decide)." if ready else "Stay at the current level; keep learning."}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("report"); s.add_argument("--campaign", required=True); s.add_argument("--max-items", type=int, default=40); s.set_defaults(f=cmd_report)
    s = sp.add_parser("mark-sent"); s.add_argument("--campaign", required=True); s.add_argument("--id", required=True); s.add_argument("--file", required=True); s.set_defaults(f=cmd_mark_sent)
    s = sp.add_parser("autonomy"); s.add_argument("--campaign", required=True); s.add_argument("--window", type=int, default=30); s.set_defaults(f=cmd_autonomy)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
