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
    - align right Cena, Nájezd
    - align left Model auta
    - align center everything else
- [x] remove duplicate of the "Typ" col since it is already in the header col and again in the data section
- [x] cols such as "Typ", "Palivo", "Převodovka" and others should have filter options in the UI, not just text search
    - for example, "Palivo" should have options like "Benzin", "Nafta", "LPG", etc. instead of free text search
- [x] reorder cols as listed in site/docs/cols.md
- [x] store custom col order the same way as filters (URL + localStorage) so it persists across sessions and can be shared via URL
- [x] some cols are still too wide by default, e.g. "Objem Kufru (l)" should be half of the current width since the values are short (4 chars max) and don't need that much space
    - check on the rest of the cols and adjust default widths accordingly
- [x] all col headers should be aligned to center
- [x] all col headers that contain units should have the units on a new line, e.g. "Výkon\n(kW)" instead of "Výkon (kW)" to save horizontal space
- [x] save dark mode selection in localStorage so it persists across sessions

## Data

- [x] some cars have invalid price like <https://www.energycars.cz/vuz/mercedes-benz-eqe/> which shows 149 900 Kč but is actually for 1 149 900 Kč
- you may have to unify combustion/data/makes-and-models.csv and electric/data/new_cars_specs.csv into a single source of truth
    - This is part of larger refactor and should be worked on separately - when i specifically ask for it.
- [x] when scraping, don't remove the data from scraped cols, add to them instad
    - mark the existing rows, that are not currently scraped, as "Odstaněno" in the "Stav" col
- [x] add Karoserie col
- [x] there are still some vehicles with incorrect price
    - <https://www.energycars.cz/vuz/byd-seal/>
    - <https://www.energycars.cz/vuz/mercedes-benz-eqe/>
    - <https://www.energycars.cz/vuz/bmw-ix/>
