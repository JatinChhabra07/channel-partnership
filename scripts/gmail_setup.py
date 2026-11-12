#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Guided Gmail connection for people who have never touched Google Cloud.

Claude drives this one step at a time, and between steps tells the user in plain words what to click.
Every step opens the exact page in the user's browser, so nobody has to find anything.

  status                       which steps are already done (start here; re-run any time)
  open project                 page: create a Google Cloud project
  open gmail-api [--project ID]   page: enable the Gmail API
  open consent   [--project ID]   page: OAuth consent / branding (choose Internal for Workspace accounts)
  open client    [--project ID]   page: create OAuth client (Desktop app) -> Download JSON
  catch-secret [--wait 600]    watches ~/Downloads for the downloaded client_secret*.json and installs it
  login                        runs `gws auth login -s gmail` (opens the Google sign-in page)
  finish --campaign C [--name N] [--signature S]   verifies the mailbox and saves it as the campaign sender
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

GWS_DIR = Path.home() / ".config" / "gws"
SECRET = GWS_DIR / "client_secret.json"
ROOT = Path(os.environ.get("CHANNEL_PARTNERSHIP_HOME", Path.home() / ".channel-partnership"))
URLS = {
    "project": "https://console.cloud.google.com/projectcreate",
    "gmail-api": "https://console.cloud.google.com/apis/library/gmail.googleapis.com",
    "consent": "https://console.cloud.google.com/auth/branding",
    "client": "https://console.cloud.google.com/auth/clients/create",
}
SAY = {
    "project": "Type a project name like 'channel-partnership' and click CREATE. Wait ~20 seconds until it finishes.",
    "gmail-api": "Check the project name at the top of the page is the one you just created, then click the blue ENABLE button.",
    "consent": "Click GET STARTED. App name: anything (e.g. 'Partner outreach'). Support email: your email. "
               "Audience: choose INTERNAL (if you only see External, choose External and add your own email as a test user). "
               "Contact email: your email. Agree and click CREATE.",
    "client": "Application type: DESKTOP APP. Name: anything. Click CREATE, then click DOWNLOAD JSON in the popup.",
}


def downloads_dir() -> Path:
    try:
        p = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True).stdout.strip()
        if p and Path(p).is_dir():
            return Path(p)
    except FileNotFoundError:
        pass
    return Path.home() / "Downloads"


def gws(*args):
    return subprocess.run(["gws", *args], capture_output=True, text=True)


def profile() -> str | None:
    r = gws("gmail", "users", "getProfile", "--params", '{"userId":"me"}')
    if r.returncode == 0:
        try:
            return json.loads(r.stdout).get("emailAddress")
        except json.JSONDecodeError:
            return None
    return None


def cmd_status(a):
    st = {
        "gws_installed": bool(shutil.which("gws")),
        "client_secret_installed": SECRET.exists(),
        "signed_in_as": profile() if SECRET.exists() else None,
    }
    st["next_step"] = ("install gws (run doctor.sh)" if not st["gws_installed"] else
                       "open project -> gmail-api -> consent -> client -> catch-secret" if not st["client_secret_installed"] else
                       "login" if not st["signed_in_as"] else "finish")
    print(json.dumps(st, indent=2))


def cmd_open(a):
    url = URLS[a.step] + (f"?project={a.project}" if a.project else "")
    opened = False
    for opener in ("xdg-open", "open", "wslview"):
        if shutil.which(opener):
            opened = subprocess.run([opener, url], capture_output=True).returncode == 0
            break
    print(json.dumps({"opened_in_browser": opened, "url": url, "tell_user": SAY[a.step]}, indent=2))


def valid_secret(p: Path) -> bool:
    try:
        d = json.loads(p.read_text())
        return "installed" in d and d["installed"].get("client_id")
    except Exception:  # noqa: BLE001
        return False


def cmd_catch(a):
    dl = downloads_dir()
    since = time.time() - a.lookback
    deadline = time.time() + a.wait
    while True:
        cands = sorted((p for p in dl.glob("client_secret*.json") if p.stat().st_mtime >= since), key=lambda p: p.stat().st_mtime)
        good = [p for p in cands if valid_secret(p)]
        if good:
            GWS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(good[-1], SECRET)
            SECRET.chmod(0o600)
            good[-1].unlink()  # don't leave an OAuth secret lying in Downloads
            print(json.dumps({"installed": str(SECRET), "from": good[-1].name}))
            return
        if [p for p in cands if not valid_secret(p)]:
            sys.exit("WRONG_FILE: the downloaded JSON is not a Desktop-app OAuth client. Recreate it as 'Desktop app'.")
        if time.time() > deadline:
            sys.exit(f"NOT_FOUND: no client_secret*.json appeared in {dl} yet. Ask the user to click DOWNLOAD JSON.")
        time.sleep(3)


def cmd_login(a):
    if not SECRET.exists():
        sys.exit("NO_CLIENT: run catch-secret first")
    # gws only PRINTS the sign-in URL (it does not open a browser) and then waits for Google's redirect on
    # localhost. Watch its output, open the URL ourselves, then wait for it to finish.
    import re

    # A token cached before this sign-in (e.g. from an earlier attempt) carries no Gmail scopes and gws keeps
    # reusing it, giving 403 "insufficient authentication scopes" after a successful login. Set it aside.
    cache = GWS_DIR / "token_cache.json"
    if cache.exists():
        cache.rename(GWS_DIR / f"token_cache.json.old-{int(time.time())}")
    p = subprocess.Popen(["gws", "auth", "login", "-s", "gmail"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    opened = False
    deadline = time.time() + a.timeout
    for line in p.stdout:
        print(line, end="", file=sys.stderr)
        m = re.search(r"https://accounts\.google\.com/\S+", line)
        if m and not opened:
            for opener in ("xdg-open", "open", "wslview"):
                if shutil.which(opener):
                    subprocess.run([opener, m.group(0)], capture_output=True)
                    opened = True
                    break
        if time.time() > deadline:
            p.kill()
            break
    rc = p.wait()
    who = profile()
    print(json.dumps({"exit": rc, "browser_opened": opened, "signed_in_as": who}))
    if not who:
        sys.exit("LOGIN_INCOMPLETE: if Google showed 'access blocked', the Workspace admin restricts unverified apps; "
                 "otherwise run again and finish the browser sign-in.")


def cmd_finish(a):
    who = profile()
    if not who:
        sys.exit("NOT_CONNECTED: run login first")
    p = ROOT / a.campaign / "config.json"
    cfg = json.loads(p.read_text()) if p.exists() else {}
    cfg["sender_email"] = who
    if a.name:
        cfg["sender_name"] = a.name
    if a.signature:
        cfg["signature"] = a.signature
    cfg["sender_mode"] = "gmail_drafts"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2))
    print(json.dumps({"connected": who, "campaign": a.campaign, "drafts_go_to": "Gmail > Drafts"}, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("status").set_defaults(f=cmd_status)
    s = sp.add_parser("open"); s.add_argument("step", choices=list(URLS)); s.add_argument("--project"); s.set_defaults(f=cmd_open)
    s = sp.add_parser("catch-secret"); s.add_argument("--wait", type=int, default=600); s.add_argument("--lookback", type=int, default=3600)
    s.set_defaults(f=cmd_catch)
    s = sp.add_parser("login"); s.add_argument("--timeout", type=int, default=300); s.set_defaults(f=cmd_login)
    s = sp.add_parser("finish"); s.add_argument("--campaign", required=True); s.add_argument("--name"); s.add_argument("--signature")
    s.set_defaults(f=cmd_finish)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
