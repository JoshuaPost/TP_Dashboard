import pandas as pd
import json

# Test CIT data loading
excel_path = "Rule Tables.xlsx"
xls = pd.ExcelFile(excel_path)

# Load CIT sheet
df_cit = pd.read_excel(xls, "7. CIT Deadlines")
print(f"CIT Sheet has {len(df_cit)} rows")
print(f"Columns: {list(df_cit.columns)[:5]}")

# Show first 3 jurisdictions
for i in range(min(3, len(df_cit))):
    jurisdiction = df_cit.iloc[i]["Jurisdiction (3-letter code)"]
    taxpayer_type = df_cit.iloc[i]["TaxpayerType"]
    text = df_cit.iloc[i]["DisplayText"]
    print(f"  {jurisdiction}: {taxpayer_type} - {text[:50]}...")

# Check if these jurisdictions exist in rules.json
with open("rules.json", "r") as f:
    rules = json.load(f)
    
print(f"\nRules.json has {len(rules['countries'])} countries")

# Check a specific country
for country in rules["countries"]:
    if country["name"] == "Albania":
        print(f"\nAlbania data:")
        print(f"  CIT deadlines: {len(country.get('cit_deadlines', []))}")
        if country.get('cit_deadlines'):
            print(f"  First CIT: {country['cit_deadlines'][0]}")
        break