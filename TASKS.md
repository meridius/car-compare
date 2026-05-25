# Task list

Work on the following tasks. Check off each item as you complete it. Commit and push your changes after each task.

## Website

## Data

- you may have to unify combustion/data/makes-and-models.csv and electric/data/new_cars_specs.csv into a single source of truth
    - This is part of larger refactor and should be worked on separately - when i specifically ask for it.
- [x] validate that old data are never removed from the CSVs (only marked as "Odstraněno" in the "Stav" column) when the scrapers don't find them anymore. This is crucial for tracking the history of listings and ensuring data integrity over time.
    - items returned by the scrapers should be merged with the previous CSV data
