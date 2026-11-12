# The brain and the learning loop

## Why two layers

mem0 with inference on rewrites and merges what you give it. That suits chat preferences, but it's dangerous for
a sales system: a suppression entry or a "never promise X" rule must not be paraphrased away. So:

- **Ledger** (local JSONL/Markdown): exact, auditable, diffable, the source of truth. Scripts read it deterministically.
- **mem0** (`infer=False`, exact text, metadata `type`/`kind`/`area`): semantic recall across campaigns. For example,
  `brain.py recall <c> "how does the user like to open emails"` finds operator rules learned on a different product.

## What goes where

| Thing | Store | Scope |
|---|---|---|
| Product facts, proof, pricing shape, brand collisions | `fact add --kind …` | campaign |
| Program terms (what may be promised) | `fact add --kind program` | campaign |
| ICP decisions, excluded segments | `fact add --kind icp` + `icp.md` | campaign |
| How the user writes (tone, length, openers, sign-off) | `lesson add --scope operator` | operator |
| What works for this product's partners (angles, segments, proof) | `lesson add` | campaign |
| Opt-outs, bounces, "never contact" | `suppress add` | global |

## Lesson lifecycle

`candidate` (seen once) → `rule` (seen in ≥2 separate emails, OR confirmed by the user) → optional `rejected`.
Rules render into `brain/rules.md`, which `context` prints first. Merging is fuzzy (same area, similar text), so
phrase lessons consistently: `<where>: <what to do> (<why, if known>)`.

Areas: subject, opening, value_prop, cta, tone, length, claims, targeting, personalisation, signoff, other.

## Reading a diff report

- `recurring.*_in_multiple_emails`: the strongest signal. Almost always a lesson.
- `opening_changed` on most emails: your opener pattern is wrong. Look at what the user wrote instead.
- `words.sent` consistently < `words.draft`: length lesson, with the target number.
- A sentence removed everywhere: often a claim the user isn't comfortable making. Make it a `claims` lesson and
  check whether the fact behind it is wrong (retire it if so).
- `edit_ratio` > 0.6 on an email: the user rewrote it. Learn from the result's structure rather than line diffs,
  and ask the user one question about what was wrong.
- Deleted drafts: decide whether the cause is targeting (the company was wrong) or the template. If unclear, ask.
- Untouched sends: positive evidence. Note which template and segment, but don't create a lesson from "no change".

## Edge cases

- **Sent from another client / forwarded**: `sync` can't find it, so the draft shows `deleted`. Ask before
  recording a rejection.
- **User edits the template before drafting**: diff the template versions yourself and record the lessons the same way.
- **Contradicting lessons** (week 1 "shorter", week 3 "more detail"): keep the newer one, reject the older one, and tell the user.
- **Outcome lessons need volume**: under ~10 sends per arm, report numbers without conclusions.

## Autonomy levels

| Level | Agent may | Gate to offer it |
|---|---|---|
| `draft_only` (default) | create drafts | — |
| `assisted_send` | send drafts the user ticked in chat, this session only | `diff_learn.py autonomy` all green |
| `auto_send` | send approved templates to approved prospects within `daily_send_cap`, then report | assisted_send for ≥2 runs with no rollback triggers |

Rollback to `draft_only` on: bounce rate > 3%, any spam complaint or angry reply, or a new campaign (trust is per product).
