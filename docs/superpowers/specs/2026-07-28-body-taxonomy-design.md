# Body-style taxonomy (Phase A)

Date: 2026-07-28
Status: design decisions agreed in chat; written spec pending review; not implemented
Branch: `feature/body-taxonomy`

## Context

This is Phase A of a larger effort to fill the reference/listing gaps that
`bin/ai-match-one.sh` can no longer close. The full effort decomposes into five
subsystems; only A is specified here.

| # | Subsystem | Depends on |
|---|-----------|-----------|
| **A** | **Body-style canonical vocabulary + fold rules + reference audit** | — |
| B | Body docs page (`site/karoserie.html`, like `transmissions.html`) | A |
| C | Reference **variant fingerprint** schema (the "indirect signals" store) | — |
| D | Listing detail-page mining (sauto free, mobile.de targeted + cached) | — |
| E | Gap-driven matching loop (rank Značka+Model groups by gap, agentic passes, then a script in the scrape) | C + D |

A is first because every later phase reads or writes `Karoserie`, and the
current value is simultaneously over-folded for display and under-folded for
scoring.

### Measured starting state (2026-07-28, full state, 152 777 live payload rows)

- Payload `Karoserie`: **6** distinct values, 50 blanks (0.03 %).
- `ice_specs.csv` (789 rows): **13** values — SUV 353, Kombi 108, Hatchback 96,
  Sedan 61, MPV 58, *blank 45*, Kupé 25, VAN 18, Sportback 12,
  Shooting Brake 4, Liftback 4, Fastback 4, Grand Sport 1.
- `ev_specs.csv` (197 rows): SUV 98, Hatchback 35, MPV 28, Sedan 20, *blank 9*,
  Kombi 4, Liftback 2, Kupé 1.
- Raw source values that must be absorbed: `CUV`, `Terénní`, `Sedan/limuzína`,
  `Pick-up`, `Kabriolet`, `SW`, `Variant`, `Combi`, `Sports Tourer`, `Touring`,
  `Allspace`, `Sportback`, `Fastback`.
- **2 651 rows / 351 reference entry groups** display a body contradicting their
  own listing (measured by the merged `fix/octavia-liftback-body` work).

### Source vocabularies

- **sauto.cz** — authoritative 13 values, codebook 4
  (`https://www.sauto.cz/api/v1/codebooks/values?codebook_id=4`): Kombi, SUV,
  Sedan/limuzína, Kabriolet, Hatchback, Kupé, MPV, Liftback, Pick-up, Terénní,
  VAN, Roadster, CUV.
- **mobile.de** — 8 values (`attr.c`): Cabrio, EstateCar, Limousine, OffRoad,
  SmallCar, SportsCar, Van, OtherCar. Only ~5 are usable: `SmallCar` is a *size*
  class, `Limousine` is a mis-set catch-all, `OffRoad` conflates SUV/off-roader/
  pickup, `SportsCar` conflates coupé/sports car.
- **autodraft.cz** — no taxonomy; regex-recovered from card text, 66 % blank.
- **energycars.cz** — none; body comes entirely from the EV reference join.

mobile.de is ~98 % of the payload (149 933 of 152 777 rows), so the dominant
source offers at most 5 body signals. This bounds what listing-side body data
can ever support.

## A1 · One module owns the taxonomy

The fold rules are currently duplicated across four files that **disagree**:

| File | Symbol |
|---|---|
| `build/build_data.py` | `_DISPLAY_BODY_CANON` |
| `scrapers/core/matching.py` | `_BODY_GROUPS` |
| `scrapers/core/fields.py` | `BODY_KEYWORDS` |
| `scrapers/sources/mobilede.py` | `_CATEGORY_MAP` |

The disagreement is a live bug: `_BODY_GROUPS` keeps `Sportback`, `Fastback` and
`Shooting Brake` as *separate scoring canons* while `_DISPLAY_BODY_CANON` folds
them into Hatchback/Kombi. A listing tagged `Sportback` therefore takes a
**−2 body mismatch** against a reference row labelled `Hatchback` even though
both render identically in the grid. Measured: 2 113 sub-body-tagged mobile.de
ICE rows, of which **80 are a guaranteed false −2** (no reference entry in their
(brand, model) cluster shares the scoring canon).

New module `scrapers/core/bodies.py` becomes the single source of truth, same
pattern as the existing `scrapers/core/filters.py`:

```python
CANONICAL      # ordered tuple of the 9 display values (filter order + docs page order)
DISPLAY_FOLD   # {raw source/reference label (lowercased) -> canonical}
SCORING_FOLD   # {canonical -> scoring canon}
```

All four call sites import from it; no body literals anywhere else.

## A2 · Two vocabularies, deliberately

**Display taxonomy — 9 values, precise.** Because the displayed body comes from
the *matched reference row* (`apply_reference_body_specs`), not the noisy
per-listing value, it can be exact without breaking the "same car → one body"
invariant.

| Czech (canonical) | English | Distinguishing fact | Absorbs |
|---|---|---|---|
| **SUV** | SUV / crossover | Raised ride height, two-box + tailgate | sauto SUV/CUV/Terénní, mobile.de OffRoad, ref SUV |
| **Kombi** | Estate / wagon | Roofline flat to the tail, cargo behind the D-pillar, car ride height | Kombi, Combi, Variant, Avant, SW, Touring, Sports Tourer, Grandtour, Shooting Brake, mobile.de EstateCar |
| **Hatchback** | Hatchback | Steep hatch **including the rear window**, boot ends just behind the C-pillar | sauto Hatchback, mobile.de SmallCar, ref Hatchback |
| **Liftback** | Liftback / Sportback | Sedan-like sloping roofline, but the hatch opens **with** the glass | sauto Liftback, ref Liftback/Sportback/Fastback/Grand Sport |
| **Sedan** | Saloon | Separate boot lid; rear glass fixed | sauto Sedan/limuzína, ref Sedan |
| **MPV** | MPV / minivan | Tall one-box passenger, ≥2 rows, reconfigurable | sauto MPV/VAN, mobile.de Van, ref MPV/VAN |
| **Kupé** | Coupé | **Fixed** low roof | sauto Kupé, mobile.de SportsCar, ref Kupé |
| **Kabriolet** | Convertible / roadster | **Retractable or removable** roof | sauto Kabriolet + Roadster, mobile.de Cabrio |
| **Pick-up** | Pickup | Open cargo bed behind the cab | sauto Pick-up |

Deltas vs the 6 shipped today: **+Liftback**, **+Kabriolet**, **+Pick-up**.

- `Kabriolet` currently folds to `Kupé`, which is simply false — an open car is
  not a fixed-roof car, and it is the most decision-relevant body fact there is
  (weather, security, resale). 24 live rows; the tag is dealer-*deliberate*
  (unlike `Limousine`), so it is trustworthy.
- `Pick-up` is 4 live rows and will stay near-empty (mobile.de buries pickups in
  `OffRoad` with no way to extract them), but folding a Ranger into SUV is a
  factual error.

**Scoring taxonomy — folded.** `SCORING_FOLD` collapses the liftback family into
Hatchback and Shooting Brake into Kombi, because listings cannot distinguish
them: a mobile.de Octavia liftback arrives tagged `SmallCar` → Hatchback, and a
−2 there would push a correct match to `Nejisté`. `Kabriolet` and `Pick-up` get
their **own** scoring groups (today `Kabriolet` has no group at all, so a
convertible scores −2 against a `Kupé` reference row).

This split is the load-bearing decision of Phase A: **display precision comes
from the reference, scoring tolerance comes from the listings' limits.**

### Why 9 and not ~14

Splitting further (CUV, Terénní, Shooting Brake, VAN, Roadster, Fastback as
distinct buckets) is not a precision-vs-sparsity trade — it is
precision-vs-*wrongness*. Those labels do not exist as clean data; they exist as
**contradictory** data. Body is also the heaviest matching field (+3 / −2), so
extra granularity is tie-fuel, and `Nejisté` is already ~98 % ties. Sub-body
detail stays available where it belongs: `body_raw` for tooltips/reference page,
and as a tie-resolver input (Lever A2's `_body_from_text` already does this).

## A3 · Reference audit — four passes

### Pass 1 — rules (no judgement)

Mechanical vocabulary remap over both CSVs: `Sportback`/`Fastback`/
`Grand Sport` → `Liftback`, `Shooting Brake` → `Kombi`, `VAN` → `MPV`,
`Terénní`/`CUV` → `SUV`, `Sedan/limuzína` → `Sedan`.

Measured: this pass alone resolves **0 of the 53** same-variant-key conflicts,
which is the point — see Pass 3.

### Pass 2 — body-agnostic PK split (the big lever)

**351 reference entry groups / 2 651 rows.** One reference row covering two
bodies forces a wrong body onto half of its listings. Generalizes the merged
`fix/octavia-liftback-body` fix: split the row per body and carry the body token
in the PK so the payload's `(Značka, Model, Verze, Objem motoru, Typ motoru)`
key stays unique per body.

```
Škoda Octavia 2.0 TDI  ->  Škoda Octavia Combi 2.0 TDI
                         + Škoda Octavia Liftback 2.0 TDI
```

`ReferencePayloadKeyTest` (already on `main`) guards the invariant.

**Known cost, accepted:** adding a same-engine body sibling converts some rows
`Ano → Nejisté`, because a body-silent listing genuinely ties between two
siblings differing only by body. An honest `Nejisté` beats a coin-flip body.
This must be reported per batch, not hidden.

Measured for the Octavia split, rebuilt on 2026-07-28 state:
`Ano 146 483 → 146 361`, `Nejisté 6 101 → 6 223` (**+122**); `Kombi −35`,
`Hatchback +35`. (The original commit measured +201 / 190 rows against its own
older state snapshot — the effect size depends on the state, so each batch must
re-measure rather than quote a previous number.)

### Pass 3 — plausible-pair detector

Nameplate-level body *conflict* is **not** an error signal, because body is
itself a variant dimension: `VW Golf 2.0 TDI [Hatchback, Kombi]` is correct
(Golf + Golf Variant), as is `Audi A4 2.0 TFSI [Kombi, Sedan]` (A4 + Avant).

The detector is instead a **plausible-pair whitelist** of body sets that one
nameplate can genuinely span:

```
{Hatchback, Kombi}  {Liftback, Kombi}  {Sedan, Kombi}  {Sedan, Liftback}
{Kupé, Kabriolet}   {MPV, Kombi}       {SUV, Kupé}     {Sedan, Kupé}
{MPV, Pick-up}      {SUV, Pick-up}
```

`{Hatchback, Liftback}` is deliberately **not** whitelisted: per A2 those are the
same physical body labelled two ways, so whitelisting the pair would suppress
exactly the error this pass exists to catch.

Any nameplate whose body set contains a pair outside the whitelist goes to the
review queue. Measured queue: **60 nameplates of 381** — e.g. `Fiat 500X
[Hatchback, SUV, Sedan]` (500X is only a crossover), `Volvo S60 [SUV, Sedan]`,
`Mini Cooper 3D [Hatchback, Kombi, Kupé, Sedan]` (3-door hatch only),
`Kia Sorento [Kupé, SUV]`, `Dacia Duster [Kombi, SUV]`.

Six of the 60 are caught *only* by the excluded pair, and they are precisely the
liftback-family contradictions the taxonomy change is meant to resolve:
`Audi A1`, `Audi A3`, `Mazda 3`, `Opel Insignia`, `Peugeot 408`, `Škoda Octavia`.

### Pass 4 — AI leftovers

Fan out Opus agents (High effort) over the residual, one nameplate per agent,
web-verified, each returning `{PK -> canonical body}` plus a short note:

- the 58 queued nameplates,
- the 45 blank-body ICE rows (includes commercial vans — Ford Transit Custom,
  Renault Trafic, Toyota Proace, Nissan Interstar, Iveco Daily — and pickups —
  Ford Ranger, Mitsubishi L200 — plus degenerate rows like `BMW 2.0`,
  `FAW Bestune 2.0`, `MG MG4`, `Toyota Yaris` that need a real variant or
  deletion),
- the 9 blank-body EV rows.

**Traps the agents must be told about:**

- **Mazda 3 "Fastback" is the 4-door saloon** in UK/EU naming → `Sedan`, *not*
  `Liftback`. A blanket `Fastback → Liftback` rule is wrong here.
- **BMW 2-series Gran Coupé is a sedan** (separate boot lid); the **4-series**
  Gran Coupé is a liftback. Our reference calls both `Kupé`.
- `Opel Insignia "Grand Sport"` is the liftback; its `Kombi` rows are Sports
  Tourer; its `Kupé` row is an error.
- `VW Arteon` = Liftback + Shooting Brake(→Kombi); the `Hatchback` row is really
  the liftback.

Batch results must be audited **per row before merging** — the existing
`ref_batch_audit` recipe applies: a new sibling can tie against an existing
entry and demote previously-confident rows, so isolated per-row effect ≠ joint
effect.

## A4 · Source-side fixes

- **`fields.BODY_KEYWORDS`**: drop `Allspace` — it is a VW *trim*, not a body,
  and currently emits `Karoserie = "Allspace"` on 3 rows. Add `Liftback` as a
  recognised listing token (sauto emits it natively on 739 rows — a free,
  high-quality signal currently folded away).
- **`mobilede._CATEGORY_MAP`**: keep `Limousine -> ""` (German dealers tag
  hatchbacks and even EVs with it; 38 020 of 183 506 rows). Unchanged.
- **`sauto.ICE_PARAMS`**: `typ_seo` is `cuv,kombi,suv,hatchback,mpv` — it
  **omits `liftback` and `sedanlimuzina`**, so we never request sedans or
  liftbacks from sauto at all. Add both. Making Liftback a first-class display
  value while not asking for the cars is incoherent. This widens the sauto
  scrape; it overlaps parked task #2 but is in scope here by explicit decision.

## A5 · Tests

1. `DISPLAY_FOLD` totality — every `Karoserie` value observed in both reference
   CSVs and all four state parquets maps to a `CANONICAL` value.
2. Every `CANONICAL` value has a `SCORING_FOLD` entry (catches the Kabriolet /
   Pick-up gap that exists today).
3. Display/scoring consistency — two labels that fold to the same *display*
   value must not fold to different *scoring* canons.
4. No reference nameplate outside the plausible-pair whitelist (Pass 3 as an
   invariant, so the queue can never silently regrow).
5. Blank-body count is monotonically non-increasing vs the current baseline
   (45 ICE + 9 EV).
6. Existing `ReferencePayloadKeyTest` continues to pass after every Pass 2 split.

Verification loop is the documented offline one: `python build/build_data.py`
then `./bin/test.sh`. The payload **must** be rebuilt before trusting the
integrity suite — a stale payload fails
`test_confident_ice_model_matches_reference_entry` whenever a reference PK
changes (observed during the `fix/octavia-liftback-body` merge: 2 938 offenders,
all stale Octavia rows).

## A6 · Silhouettes (asset produced in A, consumed in B)

Nine hand-drawn inline SVG side-profile silhouettes, iterated to v4 and reviewed.
Not Wikimedia images: no coherent Commons silhouette set exists (`File:SUV.svg`
is a Finnish powerboating federation logo; `Sedan.svg`, `Hatchback.svg`,
`Coupe.svg` etc. do not exist). Hand-drawn keeps the site self-contained,
theme-aware, and free of attribution debt.

Design decisions inside the drawings:

- A **dark seam line at the rear** marks the panel that opens — the whole
  taxonomy in one mark. Sedan's seam is *below* the glass; Liftback, Hatchback
  and Kombi's seam is *above* it.
- Greenhouse cutouts + pillar bars, real wheel-arch cutouts, a ground line, and
  differentiated ride height (low cars vs SUV/MPV/pickup share two geometry
  presets).
- An accent ring marks each value's distinguishing feature.

Draft is preserved in-repo at
`docs/superpowers/specs/assets/2026-07-28-body-silhouettes-v4.html`
(rendered: `…-v4.png`). Phase B ports it into `site/karoserie.html` with the
project's CSS custom props so it themes with the rest of the site.

Known nits carried into B: the kupé roof arc is thin (needs a fatter C-pillar);
Hatchback vs Kombi separate on length + window count only; SUV and MPV are the
same silhouette family, differing by forward-cab windshield.

## Out of scope for Phase A

- The docs page itself (B).
- Reference variant fingerprints — power, engine code, battery, door count,
  feature markers, name tokens per variant (C).
- Listing detail-page mining (D). Groundwork already probed:
  - sauto's detail call is **already made** and its `additional_model_name`,
    `equipment_cb`, `description`, `vin`, `doors`, `capacity`,
    `battery_capacity`, `gearbox_levels_cb` are all discarded — zero new
    requests to capture them.
  - mobile.de has a keyless detail endpoint `https://www.mobile.de/api/a/{id}`
    (same `X-Mobile-Client` header) returning un-truncated `title`, `subTitle`,
    `attributes` (incl. `doorCount`, `numSeats`, `countryVersion`), `features[]`
    and `htmlDescription`. No VIN. Must be targeted + cached, never a full
    150 k sweep (Akamai).
- The gap-driven matching loop (E).

## Non-goals

- Do **not** split CUV / Terénní from SUV. The distinction is dealer whim (the
  same Kodiaq appears under all three on sauto), invisible to a buyer, and
  absent from mobile.de entirely.
- Do **not** split VAN from MPV *from listings*. If it is ever wanted, derive
  `Dodávka` from the reference side only (hand-label the ~18 VAN reference
  rows), so it is consistent by construction.
- Do **not** trust mobile.de `Limousine`.
- Do **not** chase zero blanks or zero `Nejisté`. Honest uncertainty is the
  goal; the pre-existing 99.8 %-match-rate regime is the failure mode to avoid.
