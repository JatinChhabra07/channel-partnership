# Discovery

## Which source for which partner type

| Partner type | Best source | Why |
|---|---|---|
| Local service businesses (CCTV/security dealers, access-control/biometric installers, IT/AMC shops, facility management, office automation, interior/fit-out, real-estate brokers) | **Google Maps** `compass/crawler-google-places` with `scrapeContacts: true` | They all have Maps listings with website + phone; contacts come from their own site |
| Agencies / consultancies / SIs with a web presence but weak Maps presence | Google Search `apify/google-search-scraper` → their sites via `vdrmota/contact-info-scraper` | SERP finds them by service keyword |
| Vendors with official partner locators (e.g. "find a HID / ZKTeco / Hikvision partner") | wigolo `fetch` / `crawl` of the locator page, then contact-info-scraper | These are pre-qualified: they already resell a complementary product |
| Software / tech partners (integrations) | wigolo search + marketplace pages (app stores, Zapier/HubSpot listings) | No Maps presence |
| Current signals (who's talking about the category, new entrants, events) | `last30days` | Angles and names, not contacts |

Vendor partner locators are often the highest-quality source. A company that already resells access control
to offices is a near-perfect visitor-management partner. Check for them during Phase 3.

## Google Maps input template

```json
{
  "searchStringsArray": ["CCTV dealer", "security system installer", "CCTV installation company"],
  "locationQuery": "Pune, Maharashtra, India",
  "maxCrawledPlacesPerSearch": 40,
  "language": "en",
  "website": "withWebsite",
  "skipClosedPlaces": true,
  "scrapeContacts": true,
  "scrapePlaceDetailPage": false,
  "maximumLeadsEnrichmentRecords": 0,
  "scrapeSocialMediaProfiles": {"facebooks": false, "instagrams": false, "youtubes": false, "tiktoks": false, "twitters": false},
  "maxReviews": 0, "maxImages": 0
}
```

- One location per run (actor rule). Run segment × city as separate runs, so per-file ingest gets the right labels.
- `website: withWebsite` costs a filter event but saves paying contact enrichment on places that have no site.
  It also removes most one-person shops, which is usually right for partners.
- **Never** set `maximumLeadsEnrichmentRecords` > 0. That add-on returns named employees' personal data
  (and costs $0.10/lead on the free tier). It violates the business-contacts-only rule.
- 3 search strings × 40 places → up to 120 results, heavily overlapping. Expect ~50-70% unique after dedupe.
  Set the cap from the *unique* count you want, ×1.8.

### Cost formula (pull live prices with `apify_run.py estimate`; FREE-tier prices as of Nov 2026)

per place ≈ `place-scraped` $0.004 + `filter-applied` $0.001 + `contact-details-scraped` $0.002 ≈ **$0.007**
verification ≈ `email-verified` $0.0009 per email (bounceverify).
100 unique companies ≈ 180 places scraped ≈ $1.26 + ~$0.08 verification ≈ **$1.35**. Cap at 1.25× the estimate.

## Search-string patterns

Use the words the *partner* uses to describe itself, not our category:
- CCTV/security: "CCTV dealer", "CCTV installation", "security systems company", "surveillance system integrator"
- Access control/biometric: "biometric attendance machine dealer", "access control system", "boom barrier dealer", "ZKTeco dealer", "ESSL dealer"
- IT/SI: "IT solutions company", "IT AMC services", "system integrator", "networking solutions"
- Facility management: "facility management company", "housekeeping services company", "integrated facility management"
- Office automation: "office automation dealer", "photocopier dealer", "EPABX dealer", "office equipment supplier"
- Real estate: "commercial real estate consultant", "office space broker", "coworking space"

Write the chosen strings into `brain/icp.md`. When a string returns mostly junk (e.g. "security" pulls guard agencies), record a
`targeting` lesson so the next run drops it.

## Verification

1. `prospects.py mx` (free): kills dead domains.
2. Paid: `bounceverify/bounceverify-email-verifier` input `{"emails": [...]}`. Import with `prospects.py verify-import`.
   `valid` → draftable. `risky` (catch-all/unknown) → draftable but flagged in the review table; if the run's bounce
   rate later exceeds 2%, stop drafting `risky`. `invalid` → dropped.

## last30days

`python3 ~/.claude/skills/last30days/scripts/last30days.py "<topic>" --days 30` (see that skill for flags and keys;
it reuses `APIFY_TOKEN` when set). Use it in Phase 3 for angles, and when writing templates for a timely hook (a new
regulation, a widely discussed incident). Cite only what it actually returned.
