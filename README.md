# channel-partnership

A Claude Code skill that finds **channel partners** (resellers, referral partners, integrators, facility and
security firms, agencies) for any product. It drafts personalised partner emails in your Gmail and learns from
how you edit them.

```
your product website ─► brain (local mem0) ─► questions (partner model, niches, cities)
      ─► Apify: find companies + business emails (cost shown first, hard cap)
      ─► verify emails ─► score each company from its own website (100 points)
      ─► REVIEW SHEET: you approve / hold / reject / add companies
      ─► 4-5 templates ─► personalised drafts in Gmail (nothing is ever sent for you)
      ─► you edit + send ─► it diffs your edits against its drafts ─► lessons into the brain ─► next run is better
```

## Install (once, about 5 minutes)

Works on **Linux and macOS**. On Windows, use WSL (Ubuntu).

You need [Claude Code](https://claude.com/claude-code), [uv](https://docs.astral.sh/uv/) and Node.js 18+.

```bash
git clone https://github.com/JatinChhabra07/channel-partnership.git ~/.claude/skills/channel-partnership
bash ~/.claude/skills/channel-partnership/scripts/doctor.sh
```

The setup script installs and checks everything else by itself:
- **wigolo** (website scraping), **last30days** (recent discussion research), the official **Apify**, **mem0**,
  **Gmail (gws)** and **cold-email** skills
- the **self-hosted mem0 brain** (no API key, no cloud, nothing leaves your laptop), plus the patched
  `claude-code-mem0` plugin that pulls the brain into every prompt
- a campaign workspace at `~/channel-partnership-workspace`

It is safe to run again any time; it only fixes what is missing.

## Use it

```bash
cd ~/channel-partnership-workspace && claude
```

Then say something like: **"find channel partners for https://yourproduct.com"**.

Claude will:
1. Read your website into the brain and ask a few questions (partner model, target partner types, cities, signature).
2. Ask for your **Apify token** (console.apify.com → Settings → Integrations; the free plan includes $5/month).
   Paste it into `~/.channel-partnership/.env` when asked. Never paste keys into a shared chat.
3. Optionally **connect your Gmail**: say "connect my Gmail" and it opens each Google page and tells you what to click.
   Without Gmail, drafts are saved as email files instead.
4. Show the cost, find companies, verify their emails, score them, and open a **review sheet** for you.
5. Write emails from the templates you pick and put them in **Gmail → Drafts**. You edit and send them yourself, then say **"sent"**.
6. Learn from your edits. The next run follows your style.

## Where things live

| What | Where |
|---|---|
| The skill (this repo) | `~/.claude/skills/channel-partnership/` |
| Your brain, prospects, drafts, keys | `~/.channel-partnership/` (private, never in this repo) |
| mem0 vector store + model | `~/.channel-partnership/mem0/` |
| Gmail sign-in | `~/.config/gws/` |

Back up `~/.channel-partnership/` to keep your brain. Every user builds their own brain from their own answers and edits.

## Rules it follows

- Drafts only. It never sends unless you explicitly raise its autonomy level after it has proven itself.
- Business contacts only: addresses the company publishes itself. No personal emails, no guessed addresses,
  no HR/careers inboxes.
- Every paid step shows the cost first and runs with a hard spending cap.
- It never invents facts or promises (commission, pricing, timelines) that the brain can't back up with a source.
- Opt-outs and bounces are never emailed again.

## Update

```bash
cd ~/.claude/skills/channel-partnership && git pull && bash scripts/doctor.sh
```
