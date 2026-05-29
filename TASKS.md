# Task list

Work on the following tasks. Check off each item as you complete it. Commit and push your changes after each task.

## Website

- the X-axis of chart in "Historie scrapování" has only dates, which is not very informative as the scraping can happen multiple times a day (given manual triggering of the scrapers)
- the "Matice Typ × Palivo" should be redone to make more sense

## Data

- you may have to unify combustion/data/makes-and-models.csv and electric/data/new_cars_specs.csv into a single source of truth
    - This is part of larger refactor and should be worked on separately - when i specifically ask for it.
- [x] validate that old data are never removed from the CSVs (only marked as "Odstraněno" in the "Stav" column) when the scrapers don't find them anymore. This is crucial for tracking the history of listings and ensuring data integrity over time.
    - items returned by the scrapers should be merged with the previous CSV data
- [x] many of cars have empty "Stav" field
    - Root cause: sauto detail API fetch failures → `build_record()` created incomplete records with no Stav/Palivo/Výkon
    - Fix: `build_record()` now returns `None` when detail is empty (both electric + combustion)
    - Cleaned 5,392 broken records from combustion/data/scrapes/sauto.csv
- [x] there seem to be quite a lot of (potentially) duplicate entries in the CSVs, which should be investigated and resolved to maintain data quality
    - from history it seems that every four days the number of items in the CSVs increases by about 8k
    - Root cause: rows without "Odkaz na auto" (URL) couldn't be deduped by `merge_with_previous()` → accumulated as duplicates every scrape run
    - Fix: (1) `build_record()` rejects empty detail fetches, (2) `merge_with_previous()` skips empty-link rows, (3) cleaned 25,488 linkless/broken rows from all CSVs
    - Cross-source duplicates (same car on autodraft + sauto) are minimal (4 cars) — not actionable
    - also some items are still not paired with the "base" vehicles
    - whole process of data extraction, transformation, and pairing to the "base" vehicles should be thoroughly reviewed
