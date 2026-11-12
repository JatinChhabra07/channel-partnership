#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["mem0ai>=2.0.0,<3.0.0", "fastembed>=0.4"]
# ///
"""The channel-partnership brain.

Two layers, on purpose:
  1. A local ledger (plain JSONL / Markdown under ~/.channel-partnership/<campaign>/).
     This is the source of truth. It is deterministic: suppression lists, who was
     contacted, and promoted rules must never be "summarised away".
  2. Self-hosted mem0 (scripts/localmem.py: FastEmbed + embedded Qdrant on disk, no key, no cloud)
     as the semantic recall layer, mirrored from the ledger with infer=False so mem0 stores our
     exact text. If the store is busy or missing, the skill still works from the ledger alone.

Scopes:
  campaign:<slug>   facts about one product/program (Vizitor's features, ICP, program rules)
  operator          how THIS user writes and decides, across every campaign

Usage: brain.py <command> [args]   (run `brain.py -h`)
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CHANNEL_PARTNERSHIP_HOME", Path.home() / ".channel-partnership"))
GLOBAL = "_operator"
PROMOTE_AT = 2  # a lesson seen in 2 independent emails (or confirmed by the user) becomes a rule


# ---------------------------------------------------------------- helpers
def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48] or "campaign"


def cdir(campaign: str) -> Path:
    d = ROOT / (GLOBAL if campaign == GLOBAL else slugify(campaign))
    return d


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    tmp.replace(p)


def append_jsonl(p: Path, row: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def hid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:10]


# ---------------------------------------------------------------- mem0 mirror
_client = None


def mem0():
    """Return the self-hosted mem0 Memory or None. Never raises: mem0 is the recall layer, not the ledger."""
    global _client
    if _client is not None:
        return _client or None
    load_env()
    if os.environ.get("CHANNEL_PARTNERSHIP_NO_MEM0"):
        _client = False
        return None
    sys.path.insert(0, str(Path(__file__).parent))
    import io
    import contextlib
    import logging

    logging.disable(logging.WARNING)  # mem0 logs spaCy/telemetry noise on import
    with contextlib.redirect_stderr(io.StringIO()):
        from localmem import open_memory

        _client = open_memory() or False
    logging.disable(logging.NOTSET)
    if not _client:
        print("[brain] local mem0 store busy or not installed; using the ledger only", file=sys.stderr)
    return _client or None


def mem0_user(campaign: str = "") -> str:
    """ONE mem0 user for the whole brain, shared with the claude-code-mem0 plugin (MEM0_USER_ID), so the
    plugin's per-prompt recall surfaces campaign facts and rules too. Campaign/scope live in the text
    prefix and metadata instead of separate user ids."""
    load_env()
    return os.environ.get("MEM0_USER_ID") or "channel-partnership"


def scope_tag(campaign: str) -> str:
    return "operator" if campaign == GLOBAL else slugify(campaign)


def mirror(campaign: str, text: str, meta: dict) -> str | None:
    c = mem0()
    if not c:
        return None
    try:
        r = c.add(
            [{"role": "user", "content": f"[{scope_tag(campaign)}] {text}"}],
            user_id=mem0_user(),
            metadata=meta | {"campaign": scope_tag(campaign), "origin": "channel-partnership-ledger"},
            infer=False,
        )
        res = r.get("results") if isinstance(r, dict) else r
        if isinstance(res, list) and res:
            return res[0].get("id")
    except Exception as e:  # noqa: BLE001
        print(f"[brain] mem0 add failed: {e}", file=sys.stderr)
    return None


def mem0_delete(mid: str | None) -> None:
    c = mem0()
    if c and mid:
        try:
            c.delete(mid)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- commands
def cmd_init(a):
    d = cdir(a.campaign)
    (d / "brain").mkdir(parents=True, exist_ok=True)
    (d / "runs").mkdir(exist_ok=True)
    cfg_p = d / "config.json"
    cfg = json.loads(cfg_p.read_text()) if cfg_p.exists() else {}
    cfg.setdefault("campaign", slugify(a.campaign))
    cfg.setdefault("created", now())
    cfg.setdefault("autonomy", "draft_only")  # draft_only -> assisted_send -> auto_send
    cfg.setdefault("daily_send_cap", 25)
    if a.product_url:
        cfg["product_url"] = a.product_url
    cfg_p.write_text(json.dumps(cfg, indent=2))
    for f in ("suppression.txt",):
        (d / f).touch()
    cdir(GLOBAL).mkdir(parents=True, exist_ok=True)
    (cdir(GLOBAL) / "suppression.txt").touch()
    print(json.dumps({"campaign_dir": str(d), "mem0": bool(mem0()), "config": cfg}, indent=2))


def cmd_config(a):
    p = cdir(a.campaign) / "config.json"
    cfg = json.loads(p.read_text()) if p.exists() else {}
    for kv in a.set or []:
        k, v = kv.split("=", 1)
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            pass
        cfg[k] = v
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2))
    print(json.dumps(cfg, indent=2))


def cmd_fact(a):
    """Facts = things that are TRUE about the product/program/market, each with a source."""
    d = cdir(a.campaign)
    p = d / "brain" / "facts.jsonl"
    rows = read_jsonl(p)
    if a.action == "add":
        if not a.source:
            sys.exit("a fact needs --source (URL, file, or 'user said on <date>'): unsourced facts rot the brain")
        key = hid(a.kind, a.text.lower())
        if any(r["id"] == key for r in rows):
            print(json.dumps({"skipped": "duplicate", "id": key}))
            return
        row = {"id": key, "kind": a.kind, "text": a.text, "source": a.source, "added": now(), "status": "active"}
        row["mem0_id"] = mirror(a.campaign, f"[{a.kind}] {a.text}", {"type": "fact", "kind": a.kind, "source": a.source, "ledger_id": key})
        rows.append(row)
        write_jsonl(p, rows)
        print(json.dumps({"added": key}))
    elif a.action == "retire":
        for r in rows:
            if r["id"] == a.id:
                r["status"] = "retired"
                r["retired_reason"] = a.text or ""
                mem0_delete(r.get("mem0_id"))
        write_jsonl(p, rows)
        print(json.dumps({"retired": a.id}))
    else:
        for r in rows:
            if r.get("status") == "active" and (not a.kind or r["kind"] == a.kind):
                print(f"{r['id']}  [{r['kind']}] {r['text']}  <{r['source']}>")


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _render_rules(campaign: str) -> None:
    d = cdir(campaign)
    rows = read_jsonl(d / "brain" / "lessons.jsonl")
    rules = [r for r in rows if r.get("status") == "rule"]
    lines = [
        f"# Learned rules — {campaign}",
        "",
        "Generated by brain.py from lessons.jsonl. Edit lessons with `brain.py lesson`, not this file.",
        "Each rule was observed in >= %d independent edits or confirmed by the user." % PROMOTE_AT,
        "",
    ]
    for area in sorted({r["area"] for r in rules}):
        lines.append(f"## {area}")
        for r in sorted((x for x in rules if x["area"] == area), key=lambda x: -x["count"]):
            lines.append(f"- {r['text']}  _(seen {r['count']}x{', user-confirmed' if r.get('confirmed') else ''})_")
        lines.append("")
    (d / "brain" / "rules.md").write_text("\n".join(lines))


def cmd_lesson(a):
    """Lessons = observations about what the user changes/rejects. Promoted to rules by evidence."""
    scope = GLOBAL if a.scope == "operator" else a.campaign
    d = cdir(scope)
    p = d / "brain" / "lessons.jsonl"
    rows = read_jsonl(p)
    if a.action == "add":
        best, score = None, 0.0
        for r in rows:
            if r.get("status") in ("rule", "candidate") and r["area"] == a.area:
                s = _similar(r["text"], a.text)
                if s > score:
                    best, score = r, s
        if best and score >= 0.72:
            best["count"] += 1
            best.setdefault("evidence", []).append(a.evidence or "")
            best["last_seen"] = now()
            ev = "merged"
            row = best
        else:
            row = {"id": hid(a.area, a.text), "area": a.area, "text": a.text, "count": 1,
                   "evidence": [a.evidence or ""], "status": "candidate", "first_seen": now(), "last_seen": now()}
            rows.append(row)
            ev = "new"
        if a.confirmed:
            row["confirmed"] = True
        if row["status"] == "candidate" and (row["count"] >= PROMOTE_AT or row.get("confirmed")):
            row["status"] = "rule"
            row["mem0_id"] = mirror(scope, f"[rule:{row['area']}] {row['text']}",
                                    {"type": "rule", "area": row["area"], "ledger_id": row["id"]})
            ev += "+promoted"
        write_jsonl(p, rows)
        _render_rules(scope)
        print(json.dumps({"event": ev, "id": row["id"], "count": row["count"], "status": row["status"]}))
    elif a.action in ("confirm", "reject"):
        for r in rows:
            if r["id"] == a.id:
                if a.action == "confirm":
                    r["confirmed"] = True
                    if r["status"] != "rule":
                        r["status"] = "rule"
                        r["mem0_id"] = mirror(scope, f"[rule:{r['area']}] {r['text']}", {"type": "rule", "area": r["area"], "ledger_id": r["id"]})
                else:
                    r["status"] = "rejected"
                    mem0_delete(r.get("mem0_id"))
        write_jsonl(p, rows)
        _render_rules(scope)
        print(json.dumps({a.action: a.id}))
    else:
        for r in sorted(rows, key=lambda x: (x["status"] != "rule", -x["count"])):
            if r["status"] != "rejected":
                print(f"{r['id']}  {r['status']:<9} x{r['count']}  [{r['area']}] {r['text']}")


def cmd_suppress(a):
    """Suppression is global and campaign-local. Anyone who opted out/bounced is never drafted again."""
    files = [cdir(GLOBAL) / "suppression.txt"] + ([cdir(a.campaign) / "suppression.txt"] if a.campaign else [])
    if a.action == "add":
        target = files[0] if a.scope == "global" else files[-1]
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a") as f:
            for v in a.values:
                f.write(f"{v.strip().lower()}\t{a.reason or ''}\t{now()}\n")
        print(json.dumps({"suppressed": a.values, "file": str(target)}))
    else:
        sup = set()
        for f in files:
            if f.exists():
                sup |= {ln.split("\t")[0] for ln in f.read_text().splitlines() if ln.strip()}
        for v in a.values:
            v = v.strip().lower()
            dom = v.split("@")[-1]
            print(f"{v}\t{'SUPPRESSED' if (v in sup or dom in sup) else 'ok'}")


def cmd_recall(a):
    out = {"query": a.query, "mem0": [], "local": []}
    c = mem0()
    if c:
        try:
            r = c.search(a.query, filters={"user_id": mem0_user()}, top_k=a.k * 2)
            keep = (scope_tag(a.campaign), "operator")
            for m in r.get("results", []):
                camp = (m.get("metadata") or {}).get("campaign")
                if camp in keep or camp is None:  # None = conversation memories saved by the plugin hooks
                    out["mem0"].append({"scope": camp or "conversation", "memory": m.get("memory"), "score": m.get("score")})
            out["mem0"] = out["mem0"][: a.k]
        except Exception as e:  # noqa: BLE001
            out["mem0_error"] = str(e)
    words = [w for w in re.findall(r"\w+", a.query.lower()) if len(w) > 3]
    for scope in (a.campaign, GLOBAL):
        for name in ("facts.jsonl", "lessons.jsonl"):
            for r in read_jsonl(cdir(scope) / "brain" / name):
                t = r.get("text", "").lower()
                if r.get("status") in ("active", "rule", "candidate") and sum(w in t for w in words) >= max(1, len(words) // 3):
                    out["local"].append({"scope": scope, "file": name, "text": r["text"], "status": r.get("status")})
    print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_context(a):
    """The one thing to load at the start of every run: what we know, how this user writes, what to avoid."""
    d = cdir(a.campaign)
    cfg = json.loads((d / "config.json").read_text()) if (d / "config.json").exists() else {}
    print(f"# Brain context — {a.campaign}  ({now()[:10]})\n")
    print("## Config\n```json\n" + json.dumps(cfg, indent=2) + "\n```\n")
    for name, title in (("company.md", "Company / product"), ("icp.md", "Target partners (ICP)"), ("program.md", "Partner program rules")):
        f = d / "brain" / name
        if f.exists():
            print(f"## {title}\n{f.read_text().strip()}\n")
    facts = [r for r in read_jsonl(d / "brain" / "facts.jsonl") if r.get("status") == "active"]
    if facts:
        print(f"## Sourced facts ({len(facts)})")
        for r in facts[: a.max_facts]:
            print(f"- [{r['kind']}] {r['text']}  <{r['source']}>")
        print()
    for scope, title in ((GLOBAL, "Operator rules (all campaigns)"), (a.campaign, "Campaign rules")):
        f = cdir(scope) / "brain" / "rules.md"
        if f.exists():
            body = "\n".join(ln for ln in f.read_text().splitlines()[5:])
            if body.strip():
                print(f"## {title}\n{body.strip()}\n")
        cands = [r for r in read_jsonl(cdir(scope) / "brain" / "lessons.jsonl") if r.get("status") == "candidate"]
        if cands:
            print(f"## Candidate lessons, not yet rules ({title.split(' (')[0]}) — apply with judgement")
            for r in cands[:15]:
                print(f"- [{r['area']}] {r['text']} (x{r['count']}, id {r['id']})")
            print()
    pros = read_jsonl(d / "prospects.jsonl")
    drafts = read_jsonl(d / "drafts.jsonl")
    if pros or drafts:
        from collections import Counter
        print("## Pipeline")
        print("prospects by status:", dict(Counter(p.get("status") for p in pros)))
        print("drafts by status:", dict(Counter(x.get("status") for x in drafts)))
        m = read_jsonl(d / "metrics.jsonl")
        if m:
            print("last run metrics:", json.dumps(m[-1]))


def cmd_sync(a):
    """Backfill mem0 from the ledger: every active fact, every rule, and the brain pages, not yet mirrored."""
    if not mem0():
        sys.exit("NO_MEM0: local store unavailable (run scripts/doctor.sh) or busy (another session holds it; retry)")
    n = 0
    for scope in (a.campaign, GLOBAL):
        for name, ok in (("facts.jsonl", ("active",)), ("lessons.jsonl", ("rule",))):
            p = cdir(scope) / "brain" / name
            rows = read_jsonl(p)
            for r in rows:
                if r.get("status") in ok and not r.get("mem0_id"):
                    tag = f"[{r['kind']}]" if name == "facts.jsonl" else f"[rule:{r['area']}]"
                    meta = {"type": "fact", "kind": r["kind"], "source": r["source"]} if name == "facts.jsonl" else {"type": "rule", "area": r["area"]}
                    r["mem0_id"] = mirror(scope, f"{tag} {r['text']}", meta | {"ledger_id": r["id"]}) or ""
                    n += bool(r["mem0_id"])
            if rows:
                write_jsonl(p, rows)
    seen_p = cdir(a.campaign) / "brain" / ".mem0_pages.json"
    seen = json.loads(seen_p.read_text()) if seen_p.exists() else {}
    current = set()
    for page in ("company.md", "program.md", "icp.md"):
        f = cdir(a.campaign) / "brain" / page
        if f.exists():
            for chunk in [c.strip() for c in f.read_text().split("\n\n") if c.strip()]:
                h = hid(page, chunk)
                current.add(h)
                if h in seen:
                    continue
                mid = mirror(a.campaign, f"[{page}] {chunk}", {"type": "page", "page": page, "synced": now()})
                if mid:
                    seen[h] = mid
                    n += 1
    # a page paragraph that was edited or deleted must not keep answering from mem0
    removed = 0
    for h in [h for h in seen if h not in current]:
        mem0_delete(seen.pop(h))
        removed += 1
    seen_p.write_text(json.dumps(seen))
    print(json.dumps({"mirrored_to_mem0": n, "stale_removed": removed}))
    return


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("sync-mem0"); s.add_argument("campaign"); s.set_defaults(f=cmd_sync)

    s = sp.add_parser("init"); s.add_argument("campaign"); s.add_argument("--product-url"); s.set_defaults(f=cmd_init)
    s = sp.add_parser("config"); s.add_argument("campaign"); s.add_argument("--set", nargs="*"); s.set_defaults(f=cmd_config)

    s = sp.add_parser("fact"); s.add_argument("action", choices=["add", "list", "retire"]); s.add_argument("campaign")
    s.add_argument("--kind", choices=["product", "program", "icp", "market", "constraint", "proof", "brand"], default=None)
    s.add_argument("--text"); s.add_argument("--source"); s.add_argument("--id"); s.set_defaults(f=cmd_fact)

    s = sp.add_parser("lesson"); s.add_argument("action", choices=["add", "list", "confirm", "reject"]); s.add_argument("campaign")
    s.add_argument("--area", choices=["subject", "opening", "value_prop", "cta", "tone", "length", "claims", "targeting", "personalisation", "signoff", "other"], default="other")
    s.add_argument("--text"); s.add_argument("--evidence"); s.add_argument("--id")
    s.add_argument("--scope", choices=["campaign", "operator"], default="campaign")
    s.add_argument("--confirmed", action="store_true"); s.set_defaults(f=cmd_lesson)

    s = sp.add_parser("suppress"); s.add_argument("action", choices=["add", "check"]); s.add_argument("values", nargs="+")
    s.add_argument("--campaign"); s.add_argument("--reason"); s.add_argument("--scope", choices=["global", "campaign"], default="global")
    s.set_defaults(f=cmd_suppress)

    s = sp.add_parser("recall"); s.add_argument("campaign"); s.add_argument("query"); s.add_argument("-k", type=int, default=8); s.set_defaults(f=cmd_recall)
    s = sp.add_parser("context"); s.add_argument("campaign"); s.add_argument("--max-facts", type=int, default=60); s.set_defaults(f=cmd_context)

    a = ap.parse_args()
    if a.cmd == "fact" and a.action == "add" and (not a.kind or not a.text):
        sys.exit("fact add needs --kind and --text")
    if a.cmd == "lesson" and a.action == "add" and not a.text:
        sys.exit("lesson add needs --text")
    a.f(a)


if __name__ == "__main__":
    main()
