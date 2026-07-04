# /grow-reference — grow reference models to cut unpaired listings

Repeatable loop. Default fuel EV (biggest gap). Steps:

## 1. Find the gaps (deterministic)
Run: `./bin/grow-reference.sh gaps --fuel ev --rebuild --top 30`
This rebuilds `cars.json`, then writes ranked missing-reference clusters to
`tmp/ref-gap/ev-clusters.json` and prints projected newly-paired counts. Note the
current unpaired total. Skim the "Normalizační mezery" list — those are BRAND_MAP /
MODEL_CLEANUP fixes, NOT research targets; report them separately, do not research them.

## 2. Research each missing model (agentic — one subagent per cluster)
Read `tmp/ref-gap/ev-clusters.json` → `missing_ref`. For each cluster, dispatch a
subagent (model `haiku`; use `sonnet` for obscure/ambiguous models) with this contract:

> Research the electric car **"{prefix}"** (sample listing titles: {sample_names}).
> Return ONLY strict JSON with these exact keys:
> `Model auta` (= "{prefix}"), `Objem kufru (l)`, `Hlučnost (dB)`,
> `Kapacita baterie (kWh)`, `Dojezd komb. letní WLTP (km)`,
> `Dojezd komb. letní EV-database (km)`, `Cd`, `Cd zdroj`,
> `Tepelné čerpadlo možné (ano/ne)`, plus `_sources` (object mapping each numeric
> field to a source URL) and `_confidence` ("high"/"medium"/"low").
> Rules: use official manufacturer / ev-database / Wikipedia figures. NEVER invent a
> number — if you cannot find it, use "" (empty). `Cd`: real published value with
> `Cd zdroj`="reálné"; only if none exists, estimate from body shape and set
> `Cd zdroj`="odhad". `Tepelné čerpadlo možné`: "ano"/"ne"/"". If the car has several
> battery variants, give the most common one and note it in `_confidence`.

Collect the returned JSON rows into `tmp/ref-gap/candidates.json` (a JSON array).

## 3. (Optional) adversarial check
For any row with `_confidence` != "high", dispatch a second `haiku` subagent to refute
the specs (independent lookup). If it contradicts battery/range, blank those cells.

## 4. Validate
Run: `./bin/grow-reference.sh validate --fuel ev --in tmp/ref-gap/candidates.json`
Fix or drop any row the validator rejects. Result: `candidates.json.ok.json`.

## 5. Review gate (human)
Present a table: model | projected newly-paired | battery | WLTP | Cd | Cd zdroj |
source URLs. Ask the user which rows to apply. Write the approved subset to
`tmp/ref-gap/approved.json`.

## 6. Apply + measure
Run: `./bin/grow-reference.sh apply --fuel ev --in tmp/ref-gap/approved.json`
Report the printed `Nespárováno: BEFORE → AFTER (−DELTA)`. Run `./bin/test.sh` to
confirm the suite stays green.
