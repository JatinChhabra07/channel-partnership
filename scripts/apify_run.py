#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Apify with a hard spending cap. Stdlib only (no global apify-cli install needed).

  estimate  --actor compass/crawler-google-places --events place-scraped=200,contact-details-scraped=200
            Reads the actor's live pricing and YOUR plan tier, prints the worst-case cost.
  run       --actor ... --input input.json --max-charge 2.50 [--max-items N] --out results.json --campaign slug
            Starts the run with maxTotalChargeUsd (Apify stops the run at the cap), polls, saves the
            dataset, and logs the actual charge to <campaign>/runs.jsonl.
  me        Plan tier + remaining monthly credit.

Token: APIFY_TOKEN (or APIFY_API_TOKEN) from env or ~/.channel-partnership/.env.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("CHANNEL_PARTNERSHIP_HOME", Path.home() / ".channel-partnership"))
API = "https://api.apify.com/v2"


def token() -> str:
    env = ROOT / ".env"
    if env.exists():
        for ln in env.read_text().splitlines():
            if "=" in ln and not ln.lstrip().startswith("#"):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    t = os.environ.get("APIFY_TOKEN") or os.environ.get("APIFY_API_TOKEN")
    if not t:
        sys.exit("NO_APIFY_TOKEN: ask the user for it (console.apify.com/settings/integrations) and save it to ~/.channel-partnership/.env as APIFY_TOKEN=...")
    return t


def call(method: str, path: str, body=None, params=None, auth=True):
    q = dict(params or {})
    url = f"{API}{path}" + ("?" + urllib.parse.urlencode(q) if q else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    if auth:
        req.add_header("Authorization", f"Bearer {token()}")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"APIFY_HTTP_{e.code}: {e.read().decode()[:500]}")


def actor_id(a: str) -> str:
    return a.replace("/", "~")


def plan_tier() -> str:
    try:
        me = call("GET", "/users/me")["data"]
        plan = me.get("plan") or {}
        tier = (plan.get("tier") or plan.get("id") or "FREE").upper()
        for t in ("DIAMOND", "PLATINUM", "GOLD", "SILVER", "BRONZE", "FREE"):
            if t in tier:
                return t
        return "BRONZE" if "STARTER" in tier else "FREE"
    except SystemExit:
        return "FREE"


def pricing(actor: str) -> dict:
    d = call("GET", f"/acts/{actor_id(actor)}", auth=False)["data"]
    infos = d.get("pricingInfos") or []
    return infos[-1] if infos else {"pricingModel": "FREE"}


def cmd_estimate(a):
    p = pricing(a.actor)
    tier = a.tier or (plan_tier() if (os.environ.get("APIFY_TOKEN") or (ROOT / ".env").exists()) else "FREE")
    model = p.get("pricingModel")
    lines, total = [], 0.0
    if model == "PAY_PER_EVENT":
        events = p.get("pricingPerEvent", {}).get("actorChargeEvents", {})
        start = events.get("apify-actor-start", {}).get("eventPriceUsd") or 0
        total += start or 0
        for spec in (a.events or "").split(","):
            if not spec.strip():
                continue
            name, n = spec.split("=")
            ev = events.get(name.strip())
            if not ev:
                sys.exit(f"unknown event {name}; actor has: {', '.join(events)}")
            price = ev.get("eventPriceUsd")
            if price is None:
                tiers = ev.get("eventTieredPricingUsd") or {}
                price = (tiers.get(tier) or tiers.get("FREE") or {}).get("tieredEventPriceUsd", 0)
            cost = price * int(n)
            total += cost
            lines.append({"event": name.strip(), "count": int(n), "unit_usd": price, "usd": round(cost, 4)})
    elif model == "PRICE_PER_DATASET_ITEM":
        unit = p.get("pricePerUnitUsd") or 0
        n = int(a.items or 0)
        total = unit * n
        lines.append({"event": "dataset-item", "count": n, "unit_usd": unit, "usd": round(total, 4)})
    else:
        lines.append({"note": f"pricing model {model}: platform compute only; budget ~$0.01-0.05 per run"})
    out = {"actor": a.actor, "tier": tier, "model": model, "lines": lines,
           "estimated_usd": round(total, 4), "suggested_cap_usd": round(max(total * 1.25, 0.10), 2),
           "note": "Rough estimate from live Apify pricing; actual charge is logged after the run."}
    print(json.dumps(out, indent=2))


def cmd_me(a):
    me = call("GET", "/users/me")["data"]
    lim = call("GET", "/users/me/limits").get("data", {})
    cur = lim.get("current", {})
    mx = lim.get("limits", {})
    print(json.dumps({"username": me.get("username"), "tier": plan_tier(),
                      "monthly_usage_usd": cur.get("monthlyUsageUsd"),
                      "max_monthly_usage_usd": mx.get("maxMonthlyUsageUsd")}, indent=2))


def cmd_run(a):
    if a.max_charge is None or a.max_charge <= 0:
        sys.exit("refusing to run without --max-charge (USD). Show the user the estimate first.")
    body = json.loads(Path(a.input).read_text())
    params = {"maxTotalChargeUsd": a.max_charge}
    if a.max_items:
        params["maxItems"] = a.max_items
    run = call("POST", f"/acts/{actor_id(a.actor)}/runs", body=body, params=params)["data"]
    rid = run["id"]
    print(f"started run {rid}  https://console.apify.com/actors/runs/{rid}", file=sys.stderr)
    t0 = time.time()
    while run["status"] in ("READY", "RUNNING"):
        if time.time() - t0 > a.timeout:
            print("timeout waiting; run continues on Apify. Re-fetch later with the run id.", file=sys.stderr)
            break
        time.sleep(10)
        run = call("GET", f"/actor-runs/{rid}")["data"]
        print(f"  {run['status']} items~{(run.get('stats') or {}).get('resultCount', '?')}", file=sys.stderr)
    items = call("GET", f"/datasets/{run['defaultDatasetId']}/items", params={"clean": "true", "format": "json"})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(items, ensure_ascii=False, indent=1))
    usage = run.get("usageTotalUsd")
    rec = {"ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "actor": a.actor, "run_id": rid,
           "status": run["status"], "items": len(items), "charged_usd": usage, "cap_usd": a.max_charge, "out": a.out}
    if a.campaign:
        p = ROOT / a.campaign / "runs.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("estimate"); s.add_argument("--actor", required=True); s.add_argument("--events"); s.add_argument("--items")
    s.add_argument("--tier", choices=["FREE", "BRONZE", "SILVER", "GOLD", "PLATINUM", "DIAMOND"]); s.set_defaults(f=cmd_estimate)
    s = sp.add_parser("run"); s.add_argument("--actor", required=True); s.add_argument("--input", required=True)
    s.add_argument("--max-charge", type=float); s.add_argument("--max-items", type=int); s.add_argument("--out", required=True)
    s.add_argument("--campaign"); s.add_argument("--timeout", type=int, default=1500); s.set_defaults(f=cmd_run)
    s = sp.add_parser("me"); s.set_defaults(f=cmd_me)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
