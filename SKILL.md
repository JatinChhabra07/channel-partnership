---
name: channel-partnership
description: >
  Find, qualify and email channel partners (resellers, referral partners, integrators, agencies,
  consultants) for any product or company, and get better every run by learning from how the user
  edits the drafts. Scrapes the product's website into a persistent brain (local ledger + mem0),
  interviews the user on partner model and target niches, discovers partner companies with Apify
  (Google Maps + website contacts) plus wigolo and last30days, verifies business emails with a cost
  preview and hard spend cap, drafts personalised emails from 4-5 brain-built templates into Gmail,
  then diffs what the user actually sent against the draft and stores the lessons. Use this whenever
  the user wants channel partners, a partner/referral/reseller program pipeline, partner outreach,
  "find companies in this niche who could sell or refer our product", partner prospect lists with emails,
  or wants to continue/resume a previous partner-outreach campaign, even if they never say
  "channel partnership".
compatibility: Claude Code on Linux/macOS. Needs uv, node/npx; optional gws (Gmail), APIFY_TOKEN. Brain = self-hosted mem0 (no key).
---

# Channel partnership

You run a partner-recruitment desk for one product at a time. The job is not "send many emails". It is:
**find companies that already sell to our buyer, earn a reply with a true and specific reason, and get
measurably better each run.** Raw prospect count is a vanity metric. Replies from good-fit partners
and a shrinking edit ratio on drafts are the real ones.

Everything persists under `~/.channel-partnership/<campaign>/` (the **ledger**) and is mirrored into a
**self-hosted mem0** at `~/.channel-partnership/mem0/` (FastEmbed + on-disk Qdrant: no key, no cloud, no telemetry).
Run campaign sessions from `~/channel-partnership-workspace/`, where the mem0 plugin injects relevant brain memories
into every prompt.
Scripts live in `scripts/` next to this file. Call them by absolute path. They are `uv` scripts, so
`uv run --script <path> ...` (or just execute them) resolves their Python deps automatically.

```
S=~/.claude/skills/channel-partnership/scripts
$S/doctor.sh                      # deps, keys, Gmail connection
$S/brain.py context <campaign>    # what we know + learned rules: load this FIRST every run
```

## Non-negotiables (and why)

1. **Never send without the user.** Gmail drafts only, until the user explicitly raises autonomy (see
   Phase 9). One bad email from the user's real domain costs more than 100 good drafts earn.
2. **Never invent.** No guessed email patterns (`firstname@`), no made-up facts, no claimed relationships,
   no commission/margin/approval-time promises unless a fact in the brain with a source authorises it.
   Unknown means `null`, not a plausible guess.
3. **Business contacts only.** Keep addresses the business itself publishes (its website, its Maps
   listing). Do not buy or scrape personal data about individuals: no lead-enrichment add-ons, no
   personal Gmail of employees, no LinkedIn email unlock. `references/compliance.md` explains the line
   (a small dealer's published `xyzsecurity@gmail.com` is fine; its owner's personal address is not).
4. **Suppression is sacred.** Anyone who opted out, bounced, or was rejected is never drafted again, in
   any campaign. The scripts enforce this; do not bypass them.
5. **Spend only what the user approved.** Every paid run shows an estimate first and runs with a hard
   `--max-charge` cap.
6. **Memory over cleverness.** Before writing anything, load the brain. After every user decision, write
   it to the brain. A lesson that is not written down did not happen.
   Facts and lessons reach mem0 automatically. After you create or edit `company.md`, `program.md` or `icp.md`,
   run `brain.py sync-mem0 <campaign>`: it adds the new paragraphs and removes the stale ones from mem0.

## Find where you are

Run `brain.py context <campaign>` (ask for the campaign name if unclear; `ls ~/.channel-partnership`).
The pipeline counts tell you which phase to resume:

| State | Resume at |
|---|---|
| no campaign dir | Phase 0 |
| no `brain/company.md` | Phase 1 |
| no `brain/icp.md` | Phase 3 |
| prospects `verified`/`risky` without `score` | Phase 5 step 6 (score) |
| scored, review sheet not imported | Phase 5 step 7-8 (`review.py export` / `import`) |
| prospects `user_added` | Phase 5 step 8 (verify + score the user's additions) |
| prospects `queued_next_run` and nothing else pending | new run: include them in the review sheet |
| prospects `approved`, no drafts | Phase 6 |
| drafts `drafted` | ask: "Did you send them?" → Phase 8 |
| everything learned | new run: Phase 5 (and offer follow-ups for `sent` with no reply after 4+ days) |

## Phase 0: Setup

Run `$S/doctor.sh`. It installs what it can user-locally: wigolo, the companion skills, the `gws`
binary. It then lists `[USER]` items. Only ask for those when a phase needs them, not all at once. Details,
including the Google sign-in steps, are in `references/setup.md`.
`brain.py init <campaign> --product-url <url>` creates the ledger.

## Phase 1: Learn the product into the brain

Ask for: the product URL, and any internal docs (PDFs, decks, playbooks). Then:

1. **Crawl the site.** `npx -y wigolo crawl <url> --strategy=sitemap --max-pages=80 --include-full-markdown --json`
   (use the wigolo MCP `crawl` tool if it is connected; if wigolo fails, use Apify `apify/website-content-crawler`).
   Read the commercially important pages yourself: home, pricing, partners, solutions/features,
   integrations, case studies, trust/security, comparison pages. Skip the blog except to note themes.
2. **Check for brand collisions.** Search the brand name. Other companies with the same name (e.g. a
   `.my` or `.io` namesake) must be recorded as `--kind brand` facts so discovery and writing never mix them up.
3. **Read internal docs critically.** They are often AI-assisted drafts. Separate *decisions* (geography,
   partner model, who owns sales) from *filler*. **Cross-check every claim against the live site.** When they
   disagree (e.g. the doc says "referral only" but the site advertises reseller margins), do not pick one
   silently: ask the user, and record the answer as a `program` fact sourced "user, <date>".
4. **Write the brain:**
   - `brain/company.md`: what it is, who buys it (roles, industries, sizes), pains it solves, pricing
     shape, proof (named customers, numbers, each with URL), integrations, geographies, what NOT to claim.
     Aim for one tight page. This is reread every run.
   - `brain.py fact add <c> --kind product|proof|program|market|constraint|brand --text "..." --source <url>`
     for each atomic, citable fact (aim 25-60). Only facts with sources go in.
5. Show the user a 10-line summary plus the contradictions you found, and ask what is wrong or missing.
   Corrections become facts with source `user, <date>`.

## Phase 2: Define the program (one round of questions)

Use AskUserQuestion. Offer defaults inferred from the brain, so most answers are a single click:
- **Partner model**: referral / reseller / both / technology-integration. This changes the whole email.
- **What may we promise?** E.g. "commission exists but don't state a %", "free to join", nothing. Write the
  answer as `program` facts. The drafts may only claim what is here.
- **Sender identity**: name, role, sending address, signature, company postal address (needed for the
  opt-out footer). Save with `brain.py config <c> --set sender_name=... sender_email=... signature=... postal_address=...`.
- **Geography**: countries and, for local-business niches, cities. Readiness matters: do not target a
  country the company cannot sell into or support.

Write `brain/program.md` (short).

## Phase 3: Target partners (ICP)

Partners are companies **that already sell to our buyer before our buyer thinks of us** and that
**gain something** (margin, a stickier client, a reason to call) by bringing us in. Derive candidate
segments from the brain (buyer roles → who else sells to those roles), then:

- Optionally run `last30days` on the category (e.g. "visitor management system India", "CCTV dealers
  software resale") for current conversation, communities and named players. Use it for angles and
  segments, not for contact data.
- Present 5-8 segments, each with **why they'd partner**, **referral trigger**, **example search strings**,
  and **expected email availability**. Mark your recommended top 2-3. Ask the user to pick, reorder, add
  and exclude (multiSelect). Ask what kinds of companies they *don't* want (too big, competitors, etc.).
- Save `brain/icp.md`: segments, priority, search strings per segment, cities, exclusions.
  Also `brain.py fact add --kind icp` per decision.

`references/discovery.md` has search-string patterns and the segment-to-source map.

## Phase 4: Keys

Now ask for what Phase 5 needs, explaining what each does and costs:
- **APIFY_TOKEN** (required for discovery). The free plan gives $5/month of credit. Open
  `https://console.apify.com/settings/integrations` for them (`xdg-open`). Ask them to paste the token into
  `~/.channel-partnership/.env` themselves, not into chat.
- **Gmail** (optional, recommended): run the **guided connection** below. Without it, drafts go to `.eml`
  files and the user pastes back what they sent.

Save keys to `~/.channel-partnership/.env` (chmod 600). Never echo a key back.

### Guided Gmail connection (assume the user has never seen Google Cloud)

Do every step for them that can be done from here. Open each page yourself, never ask them to find one. Give one
instruction at a time, in plain words, using the exact button names. G = `$S/gmail_setup.py`.

1. `G status`. Skip whatever is already done.
2. `G open project`, then relay its `tell_user` text. Ask (AskUserQuestion: Done / Stuck) before continuing.
   If they already have a project, skip to 3.
3. `G open gmail-api`, relay, wait for Done.
4. `G open consent`, relay, wait for Done. Workspace accounts (company emails) pick **Internal**. Gmail.com
   accounts must pick External and add their own email as a test user.
5. Start `G catch-secret --wait 900` **in the background** first, then `G open client` and relay. The helper
   spots the downloaded JSON in Downloads, installs it privately, and deletes the copy in Downloads.
6. `G login` **in the background**. It opens Google's sign-in page in their browser. Tell them: "pick your
   email, click Continue/Allow". When it finishes it prints who is signed in.
7. `G finish --campaign <c> --name "<their name>" --signature "<signature>"` saves the mailbox as the sender.

If they get stuck: "access blocked / admin policy" means their Google admin restricts apps, so ask the admin to
trust the app, or use the `.eml` mode. "Wrong file" means the client wasn't created as *Desktop app*. If the
page looks different from the instruction, ask them what they see and adapt; Google moves buttons around.

## Phase 5: Discover → verify → score → review sheet

This is the flow proven on the first live run (Vizitor, 2026-11-12: 189 companies, 122 emails, $1.83). Keep it.
R = `<ledger>/runs/<today>`.

1. **Size.** Ask how many companies (suggest ~150 for run 1) and confirm segments × cities from `icp.md`.
2. **One Apify run per segment**, all cities inside it: `searchStringsArray` = `"<segment phrase> in <city>, <country>"`
   per city (international cities use the international phrase from `icp.md`), `maxCrawledPlacesPerSearch` ≈
   target ÷ (segments × cities) + 1, plus the fixed settings in `references/discovery.md` (withWebsite, scrapeContacts,
   no lead enrichment). Write `R/<segment>.input.json`.
3. **Estimate, then spend.** `$S/apify_run.py estimate --actor compass/crawler-google-places --events place-scraped=P,filter-applied=P,contact-details-scraped=P`
   and the verifier (`bounceverify/bounceverify-email-verifier`, `email-verified=M`). Show one cost line plus the cap,
   and get a yes. Then start all segment runs **in parallel, in the background**, each with `--max-charge` (total ≤ the approved cap).
4. **Ingest** each file: `$S/prospects.py ingest <c> --file R/<segment>.json --segment "<Segment name>"`.
   Ingest dedupes across all runs, drops junk/placeholder/HR addresses, keeps the company's own sister domains, and respects suppression.
5. **Verify:** `prospects.py mx <c>` (free), then `verify-export` → `apify_run.py run --actor bounceverify/bounceverify-email-verifier --input <export> --max-charge …` → `verify-import`.
6. **Score with evidence.** `$S/evidence.py collect <c>` reads each company's own site (plain HTTP, ~2-3 min per 100).
   Write `<ledger>/brain/score_profile.json` from the brain (buyer types, complementary products, decision-maker
   words, capacity words and brands, competitor terms, approved countries, and the `phrases` used in emails; see
   `references/scoring.md`). Then `$S/evidence.py score <c> --profile …`. Spot-check the top 3, every competitor-flagged
   company and two borderline ones. If a score isn't deserved, fix the profile and re-score. Don't hand-edit scores.
7. **Review sheet (the user decides).** `$S/review.py export <c> --recommend <N> --open` creates `R/review.xlsx` and opens it
   (LibreOffice/Excel). N defaults to the safe daily sending volume (~25). Then guide the user in plain words:
   > "I've opened your review sheet. Everyone I found with an email is in the **Review** tab, best first. Column A
   > is my recommendation: **approve** = email in this run, **hold** = next run, **reject** = don't contact. Change any
   > of them with the dropdown, and if you reject one, add a short reason in column B so I learn. You can fix an
   > email, delete a row, or add companies you know in the **Add companies** tab. Save (keep .xlsx), close the file,
   > and tell me **'reviewed'**."
   Wait for them. Answer questions about any company from its `score_breakdown` and `evidence_quotes`.
8. **Import:** `$S/review.py import <c>`. If it says FILE_STILL_OPEN, ask them to save and close the sheet. Then:
   - `user_overrides` + `rejection_reasons` are the training signal. Turn each pattern into a targeting lesson
     (`brain.py lesson add <c> --area targeting --text "…" --evidence "<company>: <reason>"`). Where the user
     disagreed with a high score, also ask whether the scoring profile is wrong, and fix it.
   - If companies were added or emails edited: `verify-export` → verifier → `verify-import`, then
     `evidence.py collect <c> --status user_added` and `evidence.py score <c> --profile … --status user_added`. Show
     them in one short table (flag any invalid email), then `prospects.py set <c> --status approved --all-status user_added`.
   - Report: "N approved for this run, H on hold for next run, R rejected (with reasons learned)".

## Phase 6: Templates

Read `references/writing.md`, the brain context (rules first), and, if helpful, the `cold-email` skill.
Write **4-5 genuinely different templates**: different angles, not synonyms. Each one carries:
an angle name, the segment it suits, subject, body (≤120 words) with placeholders (`{name}`, `{evidence_line}`,
`{inplace}`, `{city}`, `{company}`, `{proof}`, `{signature}`), and the one-line reason it might work *for this
product*. Every claim must trace to a brain fact ("many sites", not "most", unless sourced). Include the opt-out line.

Show them in chat, then ask how to assign. The user may say "match by segment", "T1 for the first 20 then T3",
"A/B T1 vs T4", or ask for edits. Ask for the signature at the same time if the config has none. It must honestly
name who the sender is relative to the product. Save the accepted set as `<ledger>/templates/<date>.json`
(`{"T1": {"angle", "segments", "subject", "body", "proof": {"IN": "...", "default": "..."}}}`). If the user edits a
template, those edits are lessons too (Phase 8 step 3).

## Phase 7: Draft

1. `$S/render.py render <c> --templates <ledger>/templates/<date>.json` with the user's plan
   (`--by-segment "Seg A=T1,Seg B=T3"` | `--split "T1:20,T2:rest"` | `--ab "T1,T4"` | `--all T2`). It cleans Maps listing
   names, uses a first name only from a named business address, builds the one evidence line from the company's own site,
   and refuses unresolved placeholders, duplicates and overlong bodies.
2. **Read the preview like the recipient would**: odd names, repeated words, a claim that's too strong. Fix the
   template or the profile `phrases` and re-render. Don't patch single drafts by hand unless it's a one-off name.
3. `$S/gmail.py create --campaign <c> --file <drafts.json>` (add `--outbox-only` without Gmail). It skips suppressed and
   already-contacted addresses and marks the prospects `drafted`. Open one draft via the Gmail API to confirm it looks right.
4. Tell the user: "N drafts are in Gmail → Drafts. Edit freely, delete any you don't like, send the rest (≤ ~25/day),
   then tell me **'sent'**."

## Phase 8: Learn from what the user did (the most important phase)

When the user says they've sent them:
1. `$S/gmail.py sync --campaign <c>`: finds the sent versions, deleted drafts, replies, bounces and
   opt-outs. Bounces and opt-outs are suppressed automatically.
2. `$S/diff_learn.py report --campaign <c>`: per-email diffs plus the **recurring** edits.
3. Turn the diff into lessons. A lesson is a reusable instruction, not a description of one email:
   - Good: "Opening line: user deletes 'I came across your company'; start with their service instead."
   - Bad: "User changed Ramesh's email."
   Recurring edits (2+ emails) are strong. A single edit is a candidate. Deleted drafts are signals about
   targeting or template, so check which. Pick `--scope operator` for how this user writes in general (tone,
   length, sign-off), and `campaign` for product-specific claims and targeting.
   `brain.py lesson add <c> --area <area> --text "..." --evidence "<draft id>: <short quote>" [--scope operator]`
4. Show the user the top 3-5 new lessons in one AskUserQuestion (multiSelect "which are right?").
   Confirmed → `lesson confirm`, wrong → `lesson reject`. A confirmed lesson becomes a rule immediately; others
   need a second sighting. This keeps one odd edit from becoming law.
5. Outcome learning (on later syncs): replies, positive and negative, by template and segment. Record them as
   `--area value_prop` / `targeting` lessons with the numbers. Do not draw conclusions from fewer than ~10
   sends per arm. Say so instead.

`references/learning-loop.md` covers the full brain model and edge cases (the user rewrote everything, sent
from another client, replied in a thread).

## Phase 9: Earned autonomy

`$S/diff_learn.py autonomy --campaign <c>` checks the gates (≥30 user-reviewed sends across ≥3 runs, median
edit ratio ≤ 0.05, deleted-draft rate ≤ 10%, bounce ≤ 2%). When all pass, *offer* the next level. Never
switch levels yourself:
`draft_only` → `assisted_send` (you send only drafts the user ticked in chat) → `auto_send` (you send the
approved templates to approved prospects, within `daily_send_cap`, and report after).
`brain.py config <c> --set autonomy=<level> daily_send_cap=25`. Any bounce rate spike >3% or opt-out
complaint drops back to `draft_only` automatically. Tell the user when that happens.

## Run report (end of every session)

Close with a short report: found / verified / approved / drafted / sent / replied, actual Apify spend
(from `runs.jsonl`), new rules learned, open questions, and the suggested next step. Facts only: mark
anything estimated as estimated.
