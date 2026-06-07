# Task list

Work on the following tasks. Check off each item as you complete it. Commit and push your changes after each task.

## Website

- the "Objem motoru" column should be sortable and filterable as numbers
- rows in "Referenční modely" page should be the height as on the main page
- add "Celkem" row to the bottom of the "Karoserie × Pohon" table on the "Přehled datasetu" pop-up
    - separate both "Celkem" cols/rows with bolder lines
- use decimals in the "%" col of the "Párování s referenčními modely" table on the "Přehled datasetu" pop-up

## Data

- fix `merge_with_previous` NaN-link bug: rows present in both the previous and new scrape lose `Odkaz na auto` because `df.set_index("Odkaz na auto").loc[link]` drops the index column — causes link churn on every incremental run (`scrapers/core/merge.py`)
- fix EV `Spárováno` = null vs ICE `Spárováno` = "Ne" asymmetry — dead guard in `build/build_data.py`, cosmetic/pre-existing
- you may have to unify combustion/data/makes-and-models.csv and electric/data/new_cars_specs.csv into a single source of truth
    - This is part of larger refactor and should be worked on separately - when i specifically ask for it.
- add mobile.de
- widen the scraping on sauto.cz and other sites to get more data
- values "Ne" and "Ano" in any field should be converted to their proper case
- in case the "Spárováno" column has empty values, it should be reported somewhere in the UI, so pairing can be improved, and not just ignored
- the col "Model auta" should be split into "Značka" and "Model" displayed in that order on the UI as header columns
- the col "Model auta" should not contain values from the "Objem motoru" and "Typ motoru" columns since those values are already in their respective columns
    - i know this is what the cars are called in the "Referenční modely" page, but those values should be there as a separate columns too
- some cols like "Karoserie" should be listed on the "Referenční modely" page as well as are on the main page, so they can be used for matching to scraped cars
