# Setup

`scripts/doctor.sh` does everything automatable. This file covers what needs a human.

## Data layout

```
~/.channel-partnership/
  .env                      APIFY_TOKEN=…   (chmod 600, never printed)
  mem0/                     SELF-HOSTED brain store: qdrant/ (vectors), history.db, models/ (FastEmbed), config.json
  _operator/                how THIS user writes, across all campaigns
    brain/lessons.jsonl  brain/rules.md  suppression.txt (global: bounces, opt-outs)
  <campaign>/
    config.json             sender identity, autonomy level, daily cap
    brain/company.md icp.md program.md   human-readable brain, reread every run
    brain/facts.jsonl       atomic sourced facts (mirrored to mem0)
    brain/lessons.jsonl     observations → rules (rules.md is generated)
    prospects.jsonl         every company ever found (dedupe source)
    drafts.jsonl            every draft, its sent version, outcome
    runs.jsonl              every Apify run with actual charge
    metrics.jsonl           per-learning-pass edit stats
    runs/<date>/            raw actor outputs   templates/<date>.md   outbox/<date>/*.eml
```

The ledger is the source of truth. mem0 is a mirror for semantic recall. If they ever disagree, the ledger wins.

## Keys

| Key | Where | Cost |
|---|---|---|
| `APIFY_TOKEN` | console.apify.com → Settings → Integrations | Free plan includes $5/month credit; a 100-company run is usually under $1.50 |

Write them with a heredoc append to `~/.channel-partnership/.env`. Do not put them in the command line of a
tool call that echoes them back.

## Gmail (optional, via the official `gws` CLI)

`gws` needs a Google OAuth client once per machine:

1. console.cloud.google.com → create/select a project → **APIs & Services → Library → enable "Gmail API"**.
2. **OAuth consent screen**: Internal (Workspace accounts) or External + add yourself as a test user.
3. **Credentials → Create credentials → OAuth client ID → Desktop app** → download the JSON.
4. Save it as `~/.config/gws/client_secret.json`.
5. In the Claude prompt: `! gws auth login -s gmail` (opens the browser; approve).
6. Verify: `scripts/gmail.py status`.

(If `gcloud` is installed, `gws auth setup --login` automates steps 1-5.)

Scopes used: compose drafts, read sent mail and threads (for learning and reply detection), and send only
when autonomy is raised. Without Gmail, use `gmail.py create --outbox-only`, which writes `.eml` files the user can
open and send from any client, then paste the sent text back so `diff_learn.py mark-sent` can learn from it.

## mem0 brain: self-hosted (no key, no cloud)

`scripts/localmem.py` configures mem0 OSS with **FastEmbed** `BAAI/bge-small-en-v1.5` (CPU, ~100 MB RAM, model cached
in `~/.channel-partnership/mem0/models`) and **embedded Qdrant on disk**. There is no LLM inside mem0: everything is stored
with `infer=False`, and Claude does the curation (sourced facts, lessons), so mem0 never rewrites the brain. Telemetry
(PostHog) is off. Measured: ~3 s per open, ~325 MB peak, 6/6 retrieval hits on the Vizitor facts.

The `claude-code-mem0` plugin (pinned 5e996ec, patched copy at `~/.claude/local-plugins/claude-code-mem0`) is installed
**project-scoped** in `~/channel-partnership-workspace/`. Start campaign sessions there. Each prompt pulls the top 8
brain memories into context; prompts and replies are saved verbatim (secrets redacted). The plugin vendors the identical
`localmem.py` (a test enforces it), so the hooks and `brain.py` share one store. Patches vs upstream: real Stop
`transcript_path`, incremental saves, redaction, self-hosted store, `uv` deps. Tests: `hooks/tests` (15 pass).

- Embedded Qdrant allows one process at a time. Callers retry for a few seconds, then fall back to the ledger.
  Two Claude sessions writing at the same moment can therefore skip a mirror; `brain.py sync-mem0 <campaign>` backfills.
- Backup: copy `~/.channel-partnership/` (ledger + mem0). Rebuild the store from the ledger any time by deleting
  `mem0/qdrant` and `mem0/history.db`, then `brain.py sync-mem0 <campaign>`.
- Off switch: `MEM0_DISABLED=1`.

## wigolo

Configured as an MCP server (`npx -y wigolo`). If the MCP fails to connect at session start (it sometimes
times out at 30s on cold start), the CLI works the same: `npx -y wigolo <search|fetch|crawl|extract> ... --json`.
`npx -y wigolo doctor --fix` repairs most installs.
