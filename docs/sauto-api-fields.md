# Sauto API — Available Fields

Fields from the sauto.cz detail API (`/api/v1/items/{id}`). Grouped by relevance for CSV output.

## Already Used

| API Field               | CSV Column     | Notes                                                   |
| ----------------------- | -------------- | ------------------------------------------------------- |
| `manufacturer_cb.name`  | Model auta     | Brand name                                              |
| `model_cb.name`         | Model auta     | Model name                                              |
| `additional_model_name` | Extra (suffix) | Free-text suffix, e.g. "1.5 TSi 110kW DSG - ČR, záruka" |
| `price`                 | Cena (Kč)      | Integer                                                 |
| `tachometer`            | Nájezd (km)    | Integer                                                 |
| `engine_power`          | Výkon (kW)     | Integer                                                 |
| `in_operation_date`     | Rok výroby     | Date string, first 4 chars = year                       |
| `fuel_cb.name`          | Palivo         | "Benzín", "Nafta", etc.                                 |
| `gearbox_cb.name`       | Převodovka     | "Automatická", "Manuální"                               |
| `drive_cb.name`         | Náhon 4x4      | "Pohon předních kol", "Pohon všech kol", etc.           |
| `engine_volume`         | Objem motoru   | In cc (e.g. 1498 → 1.5)                                 |
| `vehicle_body_cb.name`  | Karoserie      | "CUV", "Kombi", "SUV", "Hatchback"                      |
| `condition_cb.name`     | Stav           | "Ojeté", "Nové", "Předváděcí"                           |

## Available — Not Yet Used

### Vehicle specs

| API Field                | Type   | Example        | Notes               |
| ------------------------ | ------ | -------------- | ------------------- |
| `capacity`               | int    | `5`            | Seat count          |
| `doors`                  | int    | `5`            | Door count          |
| `airbags`                | int    | `10`           | Airbag count        |
| `average_gas_mileage`    | float  | `6.3`          | l/100km             |
| `gearbox_levels_cb.name` | string | `"7 stupňová"` | Gearbox speed count |
| `euro_level_cb.name`     | string | `"EURO 6"`     | Emission standard   |
| `vin`                    | string | `"VSSZZ..."`   | VIN number          |

### Appearance

| API Field            | Type   | Example   | Notes                            |
| -------------------- | ------ | --------- | -------------------------------- |
| `color_cb.name`      | string | `"Šedá"`  | Base color                       |
| `color_tone_cb.name` | string | `"Tmavá"` | Color tone (light/dark/metallic) |

### History & condition

| API Field                   | Type   | Example             | Notes                  |
| --------------------------- | ------ | ------------------- | ---------------------- |
| `first_owner`               | bool   | `true`              | First owner            |
| `crashed_in_past`           | bool   | `false`             | Crash history          |
| `service_book`              | bool   | `true`              | Service book available |
| `country_of_origin_cb.name` | string | `"Česká republika"` | Country of origin      |
| `stk_date`                  | date   | `"2029-01-01"`      | Next MOT/STK date      |
| `guarantee_date`            | date   | `"2028-12-01"`      | Warranty expiry        |

### Pricing

| API Field                 | Type   | Example  | Notes                 |
| ------------------------- | ------ | -------- | --------------------- |
| `price_is_vat_deductible` | bool   | `true`   | VAT deductible        |
| `price_without_vat`       | int    | `491736` | Price excl. VAT       |
| `price_note`              | string |          | Free-text price notes |

### Location

| API Field               | Type   | Example            | Notes    |
| ----------------------- | ------ | ------------------ | -------- |
| `locality.municipality` | string | `"Přerov"`         | City     |
| `locality.district`     | string | `"Přerov"`         | District |
| `locality.region`       | string | `"Olomoucký kraj"` | Region   |

### Equipment (structured)

`equipment_cb` is an array of objects, each with `name`, `value`, and `equipment_category`.

Categories: `safety`, `assist`, `interior`, `exterior`, `systems`, `seats`, `lights`, `drive`, `security`, `other`

Example items: ABS, ESP, Adaptivní tempomat, Android Auto, Apple Car Play, LED světlomety, Parkovací kamera, Vyhřívaná sedadla, Vyhřívaný volant, Start/Stop systém, Volba jízdního režimu, Isofix, Záruka, etc.

### Other (less useful)

| API Field                     | Notes                             |
| ----------------------------- | --------------------------------- |
| `aircondition_cb.name`        | AC type ("Třízónová automatická") |
| `adjustments_for_handicapped` | bool                              |
| `description`                 | Free-text listing description     |
| `images`                      | Photo URLs                        |
| `valid_to`                    | Listing expiry date               |
| `cebia_smart_code_url`        | Cebia verification link           |
| `seo_name`                    | URL slug                          |
