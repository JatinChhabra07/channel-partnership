# Compliance and deliverability

Operational guidance, not legal advice. When the user targets a new country, say which rule set applies and
recommend they confirm with whoever owns compliance.

## The email-collection line

| Allowed | Not allowed |
|---|---|
| Addresses the business publishes on its own website or Maps listing (info@, sales@, a named person on the contact page) | Guessing patterns (`firstname.lastname@`) |
| A small business's published freemail (`abcsecurity@gmail.com` on its own listing), flagged in review | Lead-enrichment databases of individuals (Apollo-style "find the CEO's email") |
| Business phone from the listing | Personal phone/email of employees from LinkedIn or data brokers |

Why: B2B outreach to a published *business* channel is accepted almost everywhere with an opt-out. Personal data of
individuals collected without their knowledge is regulated (GDPR in the EU/UK, DPDP in India) and is also what
spam filters and recipients punish. The scripts drop third-party addresses and never enable the personal-lead add-ons.

## Every email carries

- The real sender name, company, and the reason you're writing (the specific, true one).
- A plain opt-out line ("If this isn't relevant, reply 'no' and I won't email again."). Honour it: `gmail.py sync`
  suppresses opt-outs automatically, and you also add any the user mentions manually.
- The company postal address in the signature for US (CAN-SPAM) and EU/UK recipients. It's harmless everywhere, so include it by default.

## By region (short)

- **India**: B2B email to business addresses is common practice. DPDP Act obligations apply to personal data, so
  keep data minimal, record source, honour deletion requests. No consent needed for a published business channel,
  but do include the opt-out.
- **EU/UK (GDPR, PECR)**: corporate addresses may be emailed under legitimate interest with a clear opt-out.
  Sole traders and partnerships count as individuals under PECR and need prior consent, so skip them.
- **US (CAN-SPAM)**: opt-out, postal address, no deceptive subjects. Honour opt-outs within 10 days.
- **Canada (CASL)**: strict. Only email addresses that are conspicuously published **and** where the message
  relates to their business role. Keep the evidence URL.
- **Australia (Spam Act)**: similar "conspicuous publication" exception. Include an unsubscribe.

## Deliverability (protects the user's domain)

- Start ≤ 20-30 cold emails/day from a normal Workspace mailbox, sent as individual plain-text emails (which drafts are).
  Above ~50/day, recommend a secondary sending domain with SPF/DKIM/DMARC and warm-up (see the `cold-email` skill).
- No open/click tracking, no images, no attachments, max one link in the first email.
- Bounce rate > 2% means stop and re-verify. > 3% means drop autonomy to `draft_only`.
- Never send the same body to many recipients from Gmail in one burst. Personalisation also helps deliverability.
