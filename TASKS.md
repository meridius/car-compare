# Task list

Work on the following tasks. Check off each item as you complete it. Commit and push your changes after each task.

## Website

- [x] add light/dark mode toggle
    - make sure that popup filters are not transparent and match the selected theme
- [x] make table headers text wrap if the text in cells is short
    - or even make the cols width adjustable with some sensible default
- [x] move vehicle link to header cols and display it some small icon instead of text to save space
- [x] some headers have separated text like "Výkon (k W)" which should be fixed to "Výkon (kW)", the same goes for "Hlučnost (d B)" which should be "Hlučnost (dB)"
- [x] cell data alignment:
    - align rigth Cena, Nájezd
    - align left Model auta
    - align center everything else
- [x] remove duplicate of the "Typ" col since it is already in the header col and again in the data section
- cols such as "Typ", "Palivo", "Převodovka" and others should have filter options in the UI, not just text search
    - for example, "Palivo" should have options like "Benzin", "Nafta", "LPG", etc. instead of free text search

## Data

- [x] some cars have invalid price like <https://www.energycars.cz/vuz/mercedes-benz-eqe/> which shows 149 900 Kč but is actually for 1 149 900 Kč
- you may have to unify combustion/data/makes-and-models.csv and electric/data/new_cars_specs.csv into a single source of truth
- [x] when scraping, don't remove the data from scraped cols, add to them instad
    - mark the existing rows, that are not currently scraped, as "Odstaněno" in the "Stav" col
- [x] add Karoserie col
