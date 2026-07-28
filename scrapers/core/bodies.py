"""Canonical car body-style taxonomy — the single source of truth.

Before this module the fold rules lived in four places that disagreed
(`build_data._DISPLAY_BODY_CANON`, `matching._BODY_GROUPS`, `fields.BODY_KEYWORDS`,
`mobilede._CATEGORY_MAP`). The disagreement was a live bug: `_BODY_GROUPS` kept
Sportback / Fastback / Shooting Brake as separate *scoring* canons while the display
table folded them into Hatchback / Kombi, so a listing tagged "Sportback" took a
−2 body mismatch against a reference row labelled "Hatchback" even though both
rendered identically in the grid (2 113 sub-body-tagged mobile.de ICE rows, 80 of
them a guaranteed false −2). Same pattern as `core/filters.py`: change it here, and
adapters, matching, build and tests move together.

**Two vocabularies, deliberately** — see
docs/superpowers/specs/2026-07-28-body-taxonomy-design.md:

- **Display** (`CANONICAL`, 9 values, via `to_display`). The displayed body comes
  from the *matched reference row* (`build_data.apply_reference_body_specs`), not the
  noisy per-listing value, so it can afford to be precise: Liftback stays distinct
  from Hatchback, Kabriolet from Kupé.
- **Scoring** (`SCORING_FOLD`, via `to_scoring`). Folds the liftback family into
  Hatchback and Shooting Brake into Kombi, because listings *cannot* distinguish
  them — a mobile.de Octavia liftback arrives tagged `SmallCar` → Hatchback, and body
  is the heaviest matching field (+3 / −2), so a false penalty there pushes a correct
  match into `Nejisté`.

Sub-body detail is not lost: `matching.load_authoritative_list` keeps `body_raw` for
display, and `_body_from_text` uses body tokens as a tie-resolver input (Lever A2).
"""

# Display vocabulary, in filter/docs order (broadest first). Adding a value here
# means adding it to SCORING_FOLD too — pinned by tests/test_bodies.py.
CANONICAL = ("SUV", "Kombi", "Hatchback", "Liftback", "Sedan", "MPV",
             "Kupé", "Kabriolet", "Pick-up")

# Every raw label any source or reference file emits → its display value.
# Keys are matched lowercased/stripped, so spell them naturally here.
_DISPLAY_SYNONYMS = {
    # sauto SUV/CUV/Terénní · mobile.de OffRoad · autodraft SUV. The unibody vs
    # ladder-frame split is dealer whim (the same Kodiaq appears under all three),
    # invisible to a buyer, and absent from mobile.de entirely — do not split it.
    "SUV": ("SUV", "CUV", "Terénní", "Terenni", "OffRoad", "Off-road", "Offroad",
            "Crossover", "Coupé-SUV", "Coupe-SUV", "SUV/Geländewagen/Pickup"),
    # Avant/Variant/Touring/SW/Sports Tourer/Grandtour are pure brand nomenclature
    # for one body. Shooting Brake joins them: in the 2021+ ≤750k Kč market it is
    # only the CLA, which the reference labels both ways anyway.
    "Kombi": ("Kombi", "Combi", "Variant", "SW", "Avant", "Touring",
              "Sports Tourer", "Sportstourer", "Sportswagon", "Grandtour",
              "Wagon", "Shooting Brake", "EstateCar", "Estate"),
    "Hatchback": ("Hatchback", "Hatch", "SmallCar"),
    # Liftback = sedan-like roofline whose hatch opens WITH the glass. Sportback
    # (Audi), Fastback and Opel's "Grand Sport" are marketing names for it.
    "Liftback": ("Liftback", "Sportback", "Fastback", "Grand Sport"),
    "Sedan": ("Sedan", "Sedan/limuzína", "Sedan/limuzina", "Limuzína", "Limuzina",
              "Saloon"),
    # VAN folds in: passenger-MPV vs commercial-derived van is a real distinction
    # but no source carries the discriminator (mobile.de's single "Van" covers
    # both). If it is ever wanted, derive it reference-side only.
    "MPV": ("MPV", "VAN", "Van", "Minivan", "Minibus"),
    "Kupé": ("Kupé", "Kupe", "Coupé", "Coupe", "SportsCar"),
    "Kabriolet": ("Kabriolet", "Kabrio", "Cabrio", "Cabriolet", "Roadster",
                  "Targa", "Convertible"),
    "Pick-up": ("Pick-up", "Pickup", "Pick up"),
}

# Labels that are NOT bodies and must blank rather than pass through, so the
# majority-vote / derive_body chain can fill the cell. "Allspace" is a VW trim that
# leaked into fields.BODY_KEYWORDS and produced Karoserie="Allspace" rows.
_NOT_A_BODY = ("Allspace", "Alltrack", "Scout", "OtherCar", "Limousine", "Andere")

DISPLAY_FOLD = {}
for _canon, _syns in _DISPLAY_SYNONYMS.items():
    for _s in _syns:
        DISPLAY_FOLD[_s.lower()] = _canon
for _s in _NOT_A_BODY:
    DISPLAY_FOLD[_s.lower()] = ""

# Display canon → scoring canon. Only the liftback family collapses; everything
# else scores as itself. Kabriolet and Pick-up MUST appear (they had no scoring
# group at all before, so a convertible scored −2 against every reference row).
SCORING_FOLD = {
    "SUV": "SUV",
    "Kombi": "Kombi",
    "Hatchback": "Hatchback",
    "Liftback": "Hatchback",
    "Sedan": "Sedan",
    "MPV": "MPV",
    "Kupé": "Kupé",
    "Kabriolet": "Kabriolet",
    "Pick-up": "Pick-up",
}

# Body sets one nameplate can legitimately span. Body is a variant dimension, so a
# nameplate carrying two bodies is normal (VW Golf = Hatchback + Variant); only an
# implausible combination signals a reference error.
#
# {Hatchback, Liftback} is deliberately absent: that is the same physical body
# labelled two ways (Audi A3 [Hatchback, Sportback]), which is exactly the error
# the detector exists to find.
_PLAUSIBLE_PAIRS = frozenset({
    frozenset({"Hatchback", "Kombi"}),    # Golf + Golf Variant
    frozenset({"Liftback", "Kombi"}),     # Octavia liftback + Combi
    frozenset({"Sedan", "Kombi"}),        # A4 + A4 Avant
    frozenset({"Sedan", "Liftback"}),     # A3 Limousine + A3 Sportback
    frozenset({"Sedan", "Kupé"}),         # 4-series saloon + coupé
    frozenset({"Kupé", "Kabriolet"}),     # coupé + its convertible
    frozenset({"SUV", "Kupé"}),           # coupé-SUV (Arkana)
    frozenset({"MPV", "Kombi"}),          # Jogger / Vito Tourer
    frozenset({"MPV", "Pick-up"}),        # van + pickup derivative
    frozenset({"SUV", "Pick-up"}),        # SUV + pickup on one platform
})


def to_display(body) -> str:
    """Fold a raw body label onto the canonical display vocabulary.

    Unknown values pass through unchanged (deliberate — an unrecognised label must
    stay visible so the totality test catches it, rather than silently becoming
    blank or SUV). Non-body labels blank; see `_NOT_A_BODY`.
    """
    if not body:
        return ""
    s = str(body).strip()
    if not s:
        return ""
    return DISPLAY_FOLD.get(s.lower(), s)


def to_scoring(body) -> str:
    """Fold a raw body label onto the scoring canon used by `matching._score_match`.

    Composition of `to_display` then `SCORING_FOLD`, so folding for display first
    can never yield a different scoring answer (build_data does fold first).
    """
    disp = to_display(body)
    if not disp:
        return ""
    return SCORING_FOLD.get(disp, disp)


def pairs_are_plausible(body_set) -> bool:
    """True when every pair in `body_set` is a combination one nameplate can really
    offer. A set of 0 or 1 bodies is always plausible.

    Used as the Pass-3 reference-audit detector and kept as a standing invariant in
    tests/test_bodies.py so the review queue cannot silently regrow.
    """
    vals = sorted({b for b in body_set if b})
    if len(vals) < 2:
        return True
    for i, a in enumerate(vals):
        for b in vals[i + 1:]:
            if frozenset({a, b}) not in _PLAUSIBLE_PAIRS:
                return False
    return True
