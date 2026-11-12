# Partner scoring (100 points)

A score is a prioritisation aid, not proof. Every point needs a piece of evidence you can quote. No evidence means
0 for that line, not a guess.

| Criterion | Pts | Full points when… |
|---|---|---|
| Serves our buyer | 25 | Site/listing shows clients that are our buyer type (offices, factories, campuses, clinics, commercial buildings, …) |
| Complementary portfolio | 20 | Sells/installs something our buyer buys alongside us (for VMS: CCTV, access control, biometric, IT, FM, office systems) |
| Reaches decision-makers | 15 | Evidence of selling to the roles who buy us (admin, facilities, security, IT, HR, property) |
| Geographic fit | 10 | Operates where the company can sell and support |
| Credibility | 10 | Real website, years in business, rating/reviews, named clients, certifications |
| Partner capacity | 10 | Has a sales team, multiple branches, existing vendor partnerships (e.g. "authorised dealer of …") |
| Reachability | 10 | Verified business email (10), risky (6), phone only (3) |

Bands: **80+** priority · **65-79** good · **50-64** low priority · **<50** drop unless the user overrides.

Adapt the first two rows to the product in the brain. For a dev-tool, "serves our buyer" means serving engineering teams.
Write `score_breakdown` as `{"criterion": [points, "evidence quote or URL"]}` so the user can audit it in one glance.

Red flags that cap the score at 40: a competitor (sells a rival product in our category), a pure B2C shop,
a directory or aggregator page instead of a company, a dead site, or a different country than claimed.


## The scoring profile (`<ledger>/brain/score_profile.json`)

`evidence.py score` turns the rubric above into points using a per-product keyword profile, which you write from the brain.
Each group in `buyer_terms` and `portfolio_terms` counts once (1 group → partial points, 2 → more, 3+ → full), so pick
groups that mean different things. `phrases` controls how a matched group is worded in the email's evidence line: a phrase of
`""` means "never mention it" (e.g. the facility-services group inside an access-control email). Use the product's own
language from the brain, not generic words.

Worked example (Vizitor, run 1, which scored 117 companies; spot-checks matched the sites):

```json
{
 "buyer_terms": {
  "offices": [
   "corporate office",
   "corporates",
   "corporate clients",
   "offices",
   "office buildings",
   "IT park",
   "tech park",
   "commercial building",
   "commercial complex",
   "business park",
   "co-working",
   "coworking"
  ],
  "industrial": [
   "factory",
   "factories",
   "manufacturing",
   "plant",
   "warehouse",
   "industrial",
   "logistics park"
  ],
  "institutions": [
   "hospital",
   "healthcare",
   "clinic",
   "school",
   "college",
   "university",
   "campus",
   "educational institution"
  ],
  "hospitality_retail_banking": [
   "hotel",
   "mall",
   "bank",
   "retail chain",
   "government"
  ]
 },
 "portfolio_terms": {
  "access_control": [
   "access control",
   "biometric",
   "attendance system",
   "turnstile",
   "boom barrier",
   "flap barrier",
   "door lock",
   "RFID"
  ],
  "cctv": [
   "CCTV",
   "surveillance",
   "IP camera",
   "video management",
   "NVR"
  ],
  "facility_ops": [
   "facility management",
   "reception",
   "front desk",
   "front office",
   "housekeeping",
   "manned guarding",
   "security services",
   "soft services",
   "integrated facility"
  ],
  "it_si": [
   "system integrator",
   "system integration",
   "networking",
   "IT infrastructure",
   "structured cabling",
   "ELV"
  ]
 },
 "decision_terms": [
  "admin",
  "administration",
  "facility manager",
  "facilities team",
  "security head",
  "HR",
  "procurement",
  "IT team",
  "property manager",
  "estate manager"
 ],
 "capacity_terms": [
  "authorised dealer",
  "authorized dealer",
  "authorised partner",
  "authorized partner",
  "authorised distributor",
  "authorized distributor",
  "channel partner",
  "branches",
  "pan india",
  "pan-india",
  "nationwide",
  "offices in"
 ],
 "brands": [
  "HID",
  "ZKTeco",
  "eSSL",
  "Honeywell",
  "Hikvision",
  "CP Plus",
  "Matrix",
  "Suprema",
  "Bosch",
  "Dahua",
  "Axis",
  "Realtime",
  "Lenel",
  "Paxton",
  "Genetec"
 ],
 "competitor_terms": [
  "visitor management system",
  "visitor management software",
  "Envoy",
  "Veris",
  "Vizmo",
  "Greetly",
  "SwipedOn",
  "Proxyclick",
  "iLobby",
  "Sine"
 ],
 "residential_terms": [
  "home security",
  "for homes",
  "residential",
  "villa",
  "apartment"
 ],
 "geo_ok": [
  "IN",
  "AE",
  "SA",
  "NG",
  "KE",
  "GB",
  "SG"
 ],
 "phrases": {
  "portfolio": {
   "access_control": "access control",
   "cctv": "CCTV",
   "it_si": "networking",
   "facility_ops": ""
  },
  "buyers": {
   "offices": "offices",
   "industrial": "factories",
   "institutions": "campuses",
   "hospitality_retail_banking": "hotels"
  },
  "templates": {
   "Facility management": "You run facility services for {buyers}{where}.",
   "default": "You install {portfolio}{brands} for {buyers}{where}."
  }
 }
}
```

When the user overrides a high score in the review sheet, ask why. If it's a pattern ("they only do homes"), fix the profile
(e.g. add to `residential_terms`) and re-score before the next run.
