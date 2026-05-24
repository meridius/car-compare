import pandas as pd
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def parse_czech_decimal(val):
    """Parse Czech decimal format: '7,4' -> 7.4, '1,6 (13,8 kWh)' -> 1.6"""
    if pd.isna(val) or val == "":
        return None
    s = str(val).strip().strip('"')
    # Take only first number if there's extra text in parens
    if "(" in s:
        s = s[:s.index("(")].strip()
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None

def load_electric_csvs():
    dfs = []
    for name in ["autodraft", "energycars", "sauto"]:
        path = os.path.join(BASE_DIR, "electric", "data", "scrapes", f"{name}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path)
            df["Typ"] = "Elektrické"
            dfs.append(df)
            print(f"  Electric/{name}: {len(df)} rows")
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def load_combustion_csvs():
    dfs = []
    for name in ["autodraft", "sauto"]:
        path = os.path.join(BASE_DIR, "combustion", "data", "scrapes", f"{name}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path)
            df["Typ"] = "Spalovací"
            dfs.append(df)
            print(f"  Combustion/{name}: {len(df)} rows")
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()

def load_combustion_reference():
    path = os.path.join(BASE_DIR, "combustion", "data", "makes-and-models.csv")
    df = pd.read_csv(path)
    df["Spotřeba (l/100 km)"] = df["Spotřeba (l/100 km)"].apply(parse_czech_decimal)
    return df

def load_electric_reference():
    path = os.path.join(BASE_DIR, "electric", "data", "new_cars_specs.csv")
    df = pd.read_csv(path, sep=";")
    for col in ["Kapacita baterie (kWh)"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_czech_decimal)
    return df

def join_combustion_reference(df, ref):
    """Exact join: scraped 'Model auta' = ref 'Jednoznačná varianta vozu'"""
    ref_cols = {
        "Jednoznačná varianta vozu": "Model auta",
        "Spotřeba (l/100 km)": "Spotřeba (l/100 km)",
        "Objem kufru (l)": "Objem kufru (l)",
        "Hlučnost (dB)": "Hlučnost (dB)",
        "Aerodynamická modifikace (lepší/horší)": "Aerodynamická modifikace",
    }
    ref_renamed = ref.rename(columns=ref_cols)
    add_cols = ["Spotřeba (l/100 km)", "Objem kufru (l)", "Hlučnost (dB)", "Aerodynamická modifikace"]
    combustion_mask = df["Typ"] == "Spalovací"
    combustion = df[combustion_mask].copy()
    other = df[~combustion_mask].copy()

    merged = combustion.merge(
        ref_renamed[["Model auta"] + add_cols],
        on="Model auta",
        how="left",
        suffixes=("", "_ref")
    )
    for col in add_cols:
        ref_col = f"{col}_ref"
        if ref_col in merged.columns:
            merged[col] = merged[col].fillna(merged[ref_col])
            merged.drop(columns=[ref_col], inplace=True)

    return pd.concat([merged, other], ignore_index=True)

def join_electric_reference(df, ref):
    """Prefix match: find longest ref 'Model auta' that is prefix of scraped model."""
    electric_mask = df["Typ"] == "Elektrické"
    electric = df[electric_mask].copy()
    other = df[~electric_mask].copy()

    ref_models = ref["Model auta"].tolist()
    ref_models_sorted = sorted(ref_models, key=len, reverse=True)

    add_cols_map = {
        "Objem kufru (l)": "Objem kufru (l)",
        "Hlučnost (dB)": "Hlučnost (dB)",
        "Kapacita baterie (kWh)": "Kapacita baterie (kWh)",
        "Dojezd komb. letní WLTP (km)": "Dojezd WLTP (km)",
        "Dojezd komb. letní EV-database (km)": "Dojezd EV-database (km)",
        "Aerodynamická modifikace (lepší/horší)": "Aerodynamická modifikace",
        "Tepelné čerpadlo možné (ano/ne)": "Tepelné čerpadlo možné",
    }

    ref_lookup = {}
    for _, row in ref.iterrows():
        ref_lookup[row["Model auta"]] = row

    matched = 0
    for idx, row in electric.iterrows():
        model = str(row.get("Model auta", ""))
        for ref_model in ref_models_sorted:
            if model.startswith(ref_model):
                ref_row = ref_lookup[ref_model]
                for src_col, dst_col in add_cols_map.items():
                    if src_col in ref_row.index:
                        val = ref_row[src_col]
                        if pd.notna(val) and val != "":
                            if pd.isna(electric.at[idx, dst_col]) if dst_col in electric.columns else True:
                                electric.at[idx, dst_col] = val
                matched += 1
                break

    print(f"  Electric reference: {matched}/{len(electric)} matched")
    return pd.concat([other, electric], ignore_index=True)

def main():
    print("Loading scraper CSVs...")
    electric = load_electric_csvs()
    combustion = load_combustion_csvs()

    print("Merging suites...")
    df = pd.concat([electric, combustion], ignore_index=True)
    print(f"  Combined: {len(df)} rows, {len(df.columns)} columns")

    print("Loading reference data...")
    comb_ref = load_combustion_reference()
    elec_ref = load_electric_reference()

    print("Joining combustion reference...")
    df = join_combustion_reference(df, comb_ref)

    print("Joining electric reference...")
    df = join_electric_reference(df, elec_ref)

    numeric_cols = [
        "Cena (Kč)", "Nájezd (km)", "Výkon (kW)", "Rok výroby",
        "Objem kufru (l)", "Hlučnost (dB)", "Spotřeba (l/100 km)",
        "Kapacita baterie (kWh)", "Dojezd WLTP (km)", "Dojezd EV-database (km)",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.where(df.notna(), None)

    ordered_cols = [
        "Typ", "Model auta", "Cena (Kč)", "Nájezd (km)", "Rok výroby", "Výkon (kW)",
        "Palivo", "Objem motoru", "Typ motoru", "Hybrid typ",
        "Převodovka", "Dvouspojková převodovka", "Filtr pevných částic",
        "Kola", "Náhon 4x4", "Karoserie", "Výbava", "Záruka",
        "Tepelné čerpadlo",
        "Extra", "Stav", "Zdroj", "Odkaz na auto",
        "Spotřeba (l/100 km)", "Objem kufru (l)", "Hlučnost (dB)",
        "Kapacita baterie (kWh)", "Dojezd WLTP (km)", "Dojezd EV-database (km)",
        "Aerodynamická modifikace", "Tepelné čerpadlo možné",
    ]
    final_cols = [c for c in ordered_cols if c in df.columns]
    for c in df.columns:
        if c not in final_cols:
            final_cols.append(c)
    df = df[final_cols]

    out_path = os.path.join(BASE_DIR, "site", "data", "cars.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    records = df.to_dict(orient="records")
    for rec in records:
        for k, v in rec.items():
            if isinstance(v, float) and (v != v):
                rec[k] = None
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\nDone: {len(records)} cars → {out_path}")
    print(f"Final columns ({len(final_cols)}): {final_cols}")

if __name__ == "__main__":
    main()
