#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Gmail drafts + sent-mail sync through the official `gws` CLI (googleworkspace/cli).

  status                                   is gws installed and authenticated?
  create  --campaign c --file drafts.json [--outbox-only]
          drafts.json = [{"prospect_id","to","subject","body","template_id"}]
          Creates real Gmail DRAFTS (never sends). --outbox-only writes .eml files instead
          (use when Gmail is not connected; the user sends from their own client).
  sync    --campaign c                     after the user says "sent": find what was actually sent,
                                           what was deleted, replies, bounces, opt-outs
  send    --campaign c --ids d1 d2 ...     ONLY when config.autonomy != draft_only. Respects daily cap.

Ledger: ~/.channel-partnership/<campaign>/drafts.jsonl  (one row per draft, updated in place)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(os.environ.get("CHANNEL_PARTNERSHIP_HOME", Path.home() / ".channel-partnership"))
OPT_OUT = re.compile(r"\b(unsubscribe|remove me|opt[ -]?out|not interested|stop (emailing|sending)|don'?t (email|contact))\b", re.I)


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def gws(*args, body=None, params=None, ok404=False):
    if not shutil.which("gws"):
        sys.exit("NO_GWS: install the gws binary (see references/setup.md) or use --outbox-only")
    cmd = ["gws", *args]
    if params is not None:
        cmd += ["--params", json.dumps(params)]
    if body is not None:
        cmd += ["--json", json.dumps(body)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = (p.stdout or "").strip()
    if p.returncode != 0:
        if ok404 and ("404" in out + p.stderr or "not found" in (out + p.stderr).lower()):
            return None
        sys.exit(f"GWS_ERROR ({' '.join(args)}): {(p.stderr or out)[:600]}")
    try:
        return json.loads(out) if out else {}
    except json.JSONDecodeError:
        return {"raw": out}


def ledger(c):
    return ROOT / c / "drafts.jsonl"


def load(c):
    p = ledger(c)
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def save(c, rows):
    p = ledger(c)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(p)


def config(c):
    p = ROOT / c / "config.json"
    return json.loads(p.read_text()) if p.exists() else {}


def suppress(values, reason):
    f = ROOT / "_operator" / "suppression.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a") as fh:
        for v in values:
            fh.write(f"{v.lower()}\t{reason}\t{now()}\n")


def suppressed():
    s = set()
    for f in ROOT.glob("*/suppression.txt"):
        s |= {ln.split("\t")[0].strip().lower() for ln in f.read_text().splitlines() if ln.strip()}
    return s


def build_raw(to, subject, body, cfg) -> tuple[str, EmailMessage]:
    m = EmailMessage()
    m["To"] = to
    m["Subject"] = subject
    if cfg.get("sender_email"):
        m["From"] = f'{cfg.get("sender_name", "")} <{cfg["sender_email"]}>'.strip()
    m.set_content(body)
    return base64.urlsafe_b64encode(m.as_bytes()).decode(), m


def body_text(payload) -> str:
    """Plain-text body of a Gmail message payload, quoted reply history stripped."""
    def walk(p):
        if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(p["body"]["data"] + "==").decode("utf-8", "replace")
        for part in p.get("parts", []) or []:
            t = walk(part)
            if t:
                return t
        return ""
    t = walk(payload)
    if not t and payload.get("body", {}).get("data"):
        t = re.sub(r"<[^>]+>", " ", base64.urlsafe_b64decode(payload["body"]["data"] + "==").decode("utf-8", "replace"))
    t = re.split(r"\n\s*On .{5,120}wrote:\s*\n", t)[0]
    return "\n".join(l for l in t.splitlines() if not l.startswith(">")).strip()


def header(msg, name):
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def cmd_status(a):
    if not shutil.which("gws"):
        print(json.dumps({"gws": False}))
        return
    p = subprocess.run(["gws", "auth", "status"], capture_output=True, text=True)
    prof = subprocess.run(["gws", "gmail", "users", "getProfile", "--params", '{"userId":"me"}'], capture_output=True, text=True)
    print(json.dumps({"gws": True, "auth_status": (p.stdout or p.stderr).strip()[:400],
                      "gmail_profile": (prof.stdout.strip()[:300] if prof.returncode == 0 else f"NOT CONNECTED: {prof.stderr.strip()[:200]}")}, indent=2))


def cmd_create(a):
    cfg = config(a.campaign)
    items = json.loads(Path(a.file).read_text())
    rows = load(a.campaign)
    sup = suppressed()
    already = {(r["to"].lower()) for r in rows if r.get("status") in ("drafted", "sent", "replied")}
    out_dir = ROOT / a.campaign / "outbox" / dt.date.today().isoformat()
    made, skipped = 0, []
    for it in items:
        to = it["to"].strip().lower()
        if to in sup or to.split("@")[1] in sup:
            skipped.append((to, "suppressed"))
            continue
        if to in already and not a.allow_repeat:
            skipped.append((to, "already drafted/contacted"))
            continue
        raw, msg = build_raw(to, it["subject"], it["body"], cfg)
        row = {"prospect_id": it.get("prospect_id"), "to": to, "subject": it["subject"], "body": it["body"],
               "template_id": it.get("template_id"), "run": a.run or dt.date.today().isoformat(), "created": now()}
        if a.outbox_only:
            out_dir.mkdir(parents=True, exist_ok=True)
            fn = out_dir / f"{re.sub(r'[^a-z0-9]+', '_', to)}.eml"
            fn.write_bytes(msg.as_bytes())
            row |= {"id": f"eml:{fn.name}", "status": "drafted", "channel": "outbox", "file": str(fn)}
        else:
            d = gws("gmail", "users", "drafts", "create", params={"userId": "me"}, body={"message": {"raw": raw}})
            row |= {"id": d.get("id"), "message_id": (d.get("message") or {}).get("id"),
                    "thread_id": (d.get("message") or {}).get("threadId"), "status": "drafted", "channel": "gmail"}
        rows.append(row)
        already.add(to)
        made += 1
    save(a.campaign, rows)
    # keep the prospect ledger in step: drafted companies are not re-offered in the next review sheet
    pp = ROOT / a.campaign / "prospects.jsonl"
    if pp.exists():
        drafted_ids = {r.get("prospect_id") for r in rows if r.get("status") == "drafted"}
        prows = [json.loads(l) for l in pp.read_text().splitlines() if l.strip()]
        for pr in prows:
            if pr["id"] in drafted_ids and pr.get("status") in ("approved", "verified", "risky", "user_added"):
                pr["status"] = "drafted"
        tmp = pp.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in prows))
        tmp.replace(pp)
    print(json.dumps({"drafted": made, "skipped": skipped, "where": str(out_dir) if a.outbox_only else "Gmail > Drafts"}, indent=2))


def cmd_sync(a):
    rows = load(a.campaign)
    me = (gws("gmail", "users", "getProfile", params={"userId": "me"}) or {}).get("emailAddress", "").lower()
    changes = {"sent": 0, "deleted": 0, "still_draft": 0, "replied": 0, "bounced": 0, "opted_out": 0}
    for r in rows:
        if r.get("channel") != "gmail":
            continue
        if r["status"] == "drafted":
            d = gws("gmail", "users", "drafts", "get", params={"userId": "me", "id": r["id"], "format": "minimal"}, ok404=True)
            if d:
                changes["still_draft"] += 1
                continue
            since = r["created"][:10].replace("-", "/")
            q = f'in:sent to:{r["to"]} after:{since}'
            lst = gws("gmail", "users", "messages", "list", params={"userId": "me", "q": q, "maxResults": 5}) or {}
            msgs = lst.get("messages") or []
            if not msgs:
                r["status"] = "deleted"  # the user threw the draft away = a rejection signal
                r["resolved"] = now()
                changes["deleted"] += 1
                continue
            m = gws("gmail", "users", "messages", "get", params={"userId": "me", "id": msgs[-1]["id"], "format": "full"})
            r |= {"status": "sent", "sent_id": m["id"], "thread_id": m.get("threadId"), "sent_subject": header(m, "Subject"),
                  "sent_body": body_text(m.get("payload", {})), "sent_at": dt.datetime.fromtimestamp(int(m["internalDate"]) / 1000, dt.timezone.utc).isoformat(timespec="seconds")}
            changes["sent"] += 1
        if r["status"] in ("sent",) and r.get("thread_id"):
            t = gws("gmail", "users", "threads", "get", params={"userId": "me", "id": r["thread_id"], "format": "full"}, ok404=True) or {}
            for m in t.get("messages", [])[1:]:
                frm = header(m, "From").lower()
                if me and me in frm:
                    continue
                txt = body_text(m.get("payload", {}))
                if "mailer-daemon" in frm or "postmaster" in frm or "delivery status notification" in header(m, "Subject").lower():
                    r["status"] = "bounced"
                    suppress([r["to"]], "bounced")
                    changes["bounced"] += 1
                elif OPT_OUT.search(txt[:600]):
                    r["status"] = "opted_out"
                    r["reply_snippet"] = txt[:500]
                    suppress([r["to"]], "opted out")
                    changes["opted_out"] += 1
                else:
                    r["status"] = "replied"
                    r["reply_snippet"] = txt[:800]
                    changes["replied"] += 1
                break
    save(a.campaign, rows)
    print(json.dumps(changes, indent=2))


def cmd_send(a):
    cfg = config(a.campaign)
    if cfg.get("autonomy", "draft_only") == "draft_only":
        sys.exit("REFUSED: autonomy is draft_only. The user must explicitly raise it (see references/learning-loop.md).")
    rows = load(a.campaign)
    today = dt.date.today().isoformat()
    sent_today = sum(1 for r in rows if (r.get("sent_at") or "").startswith(today))
    cap = int(cfg.get("daily_send_cap", 25))
    ids = set(a.ids)
    sup = suppressed()
    n = 0
    for r in rows:
        if r["id"] in ids and r["status"] == "drafted" and r.get("channel") == "gmail":
            if sent_today + n >= cap:
                print(f"daily cap {cap} reached; stopping", file=sys.stderr)
                break
            if r["to"] in sup:
                continue
            m = gws("gmail", "users", "drafts", "send", params={"userId": "me"}, body={"id": r["id"]})
            r |= {"status": "sent", "sent_id": m.get("id"), "thread_id": m.get("threadId"), "sent_subject": r["subject"],
                  "sent_body": r["body"], "sent_at": now(), "sent_by": "agent"}
            n += 1
    save(a.campaign, rows)
    print(json.dumps({"sent": n, "cap": cap}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("status"); s.set_defaults(f=cmd_status)
    s = sp.add_parser("create"); s.add_argument("--campaign", required=True); s.add_argument("--file", required=True)
    s.add_argument("--outbox-only", action="store_true"); s.add_argument("--allow-repeat", action="store_true"); s.add_argument("--run")
    s.set_defaults(f=cmd_create)
    s = sp.add_parser("sync"); s.add_argument("--campaign", required=True); s.set_defaults(f=cmd_sync)
    s = sp.add_parser("send"); s.add_argument("--campaign", required=True); s.add_argument("--ids", nargs="+", required=True); s.set_defaults(f=cmd_send)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
