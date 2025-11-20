# compile_rules2.py
# Compile "Rule Tables.xlsx" (tabs 0..6) into a normalized rules.json
# Uses country names as primary identifiers.

import argparse, json, sys, calendar, re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import pandas as pd
try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    relativedelta = None  # Handle missing dateutil gracefully

# ---------------------------- Constants ----------------------------

class SheetNames:
    COUNTRY_REGIONS = "0. Iso Codes"  # Maps countries to regions
    LF_THRESHOLD = "1.LFR Threshold"
    LF_DEADLINES = "2. LFR Deadlines"
    MF_THRESHOLD = "3. MF_Thresholds"
    MF_DEADLINES = "4. MF_Deadlines"
    TP_FORMS = "5. TPForms_deadlines"
    CBCR = "6. CBCR Notifications"
    CIT_DEADLINES = "7. CIT Deadlines"  # NEW

class DocType:
    LF = "LF"
    MF = "MF"
    FM = "Fm"

class RequirementStatus:
    YES_VALUES = ("yes", "y", "true", "1")
    NO_VALUES = ("no", "n", "false", "0")

# ----------------------------- helpers -----------------------------

def clean(x) -> str:
    """Clean and normalize input value to string."""
    if pd.isna(x): return ""
    return str(x).strip()

def as_int(x) -> Optional[int]:
    """Convert value to integer, return None if invalid."""
    try:
        if x == "" or pd.isna(x): return None
        return int(float(x))
    except Exception:
        return None

def as_float(x) -> Optional[float]:
    """Convert value to float, return None if invalid."""
    try:
        if x == "" or pd.isna(x): return None
        return float(x)
    except Exception:
        return None

def norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names by stripping whitespace."""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def find_col(cols: List[str], *candidates: str) -> Optional[str]:
    """Return first case-insensitive exact match; fallback to substring contains."""
    lc = {c.lower(): c for c in cols}
    # First pass: exact match
    for cand in candidates:
        key = cand.lower()
        if key in lc: 
            return lc[key]
    # Second pass: substring match
    for c in cols:
        cl = c.lower()
        for cand in candidates:
            if cand.lower() in cl: 
                return c
    return None

def month_name(m: Optional[int]) -> str:
    """Get abbreviated month name for month number."""
    return calendar.month_abbr[m] if m and 1 <= m <= 12 else ""

# --------------------------- Country/Region loading ---------------------------

def load_country_map(df_country: pd.DataFrame, debug: bool = False) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Load country name AND code to region mapping, plus code to name mapping."""
    df_country = norm_cols(df_country)
    
    # Find columns
    country_col = find_col(df_country.columns, "Country", "Jurisdiction")
    code3_col = find_col(df_country.columns, "Code_3", "Code 3", "Code3", "ISO3", "ISO_3", "ISO-3")
    region_col = find_col(df_country.columns, "Region")
    
    if debug:
        print(f"[country_map] columns: country={country_col}, code3={code3_col}, region={region_col}")
    
    if not country_col:
        raise ValueError("Country/Region sheet must contain a 'Country' column.")

    name_to_region = {}
    code_to_name = {}
    
    for _, r in df_country.iterrows():
        nm = clean(r.get(country_col))
        code3 = clean(r.get(code3_col)) if code3_col else ""
        reg = clean(r.get(region_col))
        
        if reg:  # Only process if region exists
            if nm:
                name_to_region[nm.lower()] = reg
            if code3:
                name_to_region[code3.lower()] = reg
                code_to_name[code3.upper()] = nm  # Map code to full name
    
    if debug:
        print(f"[country_map] Loaded {len(name_to_region)} region mappings, {len(code_to_name)} code->name mappings")
    
    return name_to_region, code_to_name

def ensure_country(registry: Dict[str, Dict], j_value: str, 
                  name_to_region: Dict[str, str], code_to_name: Dict[str, str],
                  debug: bool = False) -> Optional[Dict[str, Any]]:
    """Ensure country exists in registry, create if needed. Uses country name as identifier."""
    if not j_value:
        return None
    
    nm = clean(j_value)
    
    # Get the full country name if j_value is a code
    full_name = code_to_name.get(nm.upper(), nm)  # Use the mapping or fallback to original
    key = full_name.lower()  # Use full name as key
    
    if key not in registry:
        region = name_to_region.get(nm.lower(), "")  # Get region using original value
        if not region and debug:
            print(f"[warn] No region found for country: {nm}")
        
        registry[key] = {
            "name": full_name,  # Store the full country name
            "region": region,
            "lf_tpd_thresholds": [],
            "lf_tpd_deadlines": [],
            "mf_thresholds": [],
            "mf_deadlines": [],
            "tp_forms": [],
            "cbcr": None,
            "cit_deadlines": []  # NEW - CIT deadlines
        }
    
    return registry[key]

# --------------------------- loaders -------------------------------

def load_sheet(xls: pd.ExcelFile, name: str, required: bool = True, debug: bool = False) -> pd.DataFrame:
    """Load and normalize a sheet from Excel file."""
    if name not in xls.sheet_names:
        if required:
            raise ValueError(f"Missing required sheet: {name}")
        if debug:
            print(f"[warn] sheet not found (optional): {name}")
        return pd.DataFrame()
    
    df = pd.read_excel(xls, sheet_name=name)
    return norm_cols(df)

def pack_threshold_row(r: Any) -> Dict[str, Any]:
    """Pack threshold data from row into dictionary."""
    requirement_applies = clean(r.get("RequirementApplies"))
    
    return {
        "group_id": clean(r.get("GroupID")),
        "seq": as_int(r.get("Seq")) or 0,
        "requirement_applies": requirement_applies,  # Yes/No
        "op": clean(r.get("ThresholdOperator")),                    # >=, >, none, ...
        "amount": as_float(r.get("ThresholdAmount")),
        "currency": clean(r.get("ThresholdCurrency")),
        "metric": clean(r.get("ThresholdMetric")),
        "metric_basis": clean(r.get("MetricBasisText")),
        "note": clean(r.get("DisplayNote")),
        "is_applicable": requirement_applies.lower() not in ["no", "n", "n/a", "false", "0"] if requirement_applies else True
    }

def pack_deadline_row(r: Any) -> Dict[str, Any]:
    """Pack deadline data from row into dictionary."""
    m = as_int(r.get("Month"))
    d = as_int(r.get("Day"))
    offset_days = as_int(r.get("OffsetDays"))
    offset_months = as_int(r.get("OffsetMonths"))
    
    return {
        "group_id": clean(r.get("GroupID")),
        "seq": as_int(r.get("Seq")) or 0,
        "requirement_type": clean(r.get("RequirementType")),   # HARD/SOFT/N/A
        "deadline_kind": clean(r.get("DeadlineKind")),         # FIXED_DATE, RETURN_DUE_DATE, etc.
        "month": m,
        "day": d,
        "month_name": month_name(m) if m else "",
        "event_anchor": clean(r.get("EventAnchor")),           # FYE, AuditNotice, RequestDate, ...
        "offset_days": offset_days,
        "offset_months": offset_months,
        "text": clean(r.get("DisplayText")),
    }

def pack_form_row(r: Any) -> Dict[str, Any]:
    """Pack TP form data from row into dictionary."""
    base = pack_deadline_row(r)
    base.update({
        "name": clean(r.get("FormName")),
        "included_in_return": clean(r.get("IncludedInReturn")),
    })
    return base

def pack_cbcr_row(r: Any) -> Dict[str, Any]:
    """Pack CbCR notification data from row into dictionary."""
    m = as_int(r.get("Month"))
    return {
        "required": clean(r.get("Required")),                       # Yes/No
        "requirement_type": clean(r.get("RequirementType")),        # HARD/SOFT/N/A
        "included_in_cit": clean(r.get("IncludedInCITReturn")),    # Yes/No
        "annual": clean(r.get("AnnualNotification")),              # Yes/No
        "single_filer_ok": clean(r.get("SingleFilerAllowed")),     # Yes/No
        "deadline_kind": clean(r.get("DeadlineKind")),
        "month": m,
        "day": as_int(r.get("Day")),
        "month_name": month_name(m) if m else "",
        "event_anchor": clean(r.get("EventAnchor")),
        "offset_days": as_int(r.get("OffsetDays")),
        "offset_months": as_int(r.get("OffsetMonths")),
        "text": clean(r.get("DisplayText")),
    }

def pack_cit_row(r: Any) -> Dict[str, Any]:
    """Pack CIT deadline data from row into dictionary."""
    m = as_int(r.get("Month"))
    # Handle N/A values properly - check multiple possible column name variations
    offset_months_val = r.get("OffsetMonths") or r.get("Offset Months") or r.get("offset_months")
    offset_days_val = r.get("OffsetDays") or r.get("Offset Days") or r.get("offset_days")
    
    offset_months = as_int(offset_months_val) if clean(str(offset_months_val)).upper() != "N/A" else None
    offset_days = as_int(offset_days_val) if clean(str(offset_days_val)).upper() != "N/A" else None
    
    return {
        "group_id": clean(r.get("GroupID") or r.get("Group ID") or r.get("group_id")),
        "seq": as_int(r.get("Seq")) or 0,
        "taxpayer_type": clean(r.get("TaxpayerType") or r.get("Taxpayer Type") or r.get("taxpayer_type")),
        "condition_metric": clean(r.get("ConditionMetric") or r.get("Condition Metric")) if clean(str(r.get("ConditionMetric"))).upper() != "N/A" else "",
        "condition_op": clean(r.get("ConditionOperator") or r.get("Condition Operator")) if clean(str(r.get("ConditionOperator"))).upper() != "N/A" else "",
        "condition_value": as_float(r.get("ConditionValue") or r.get("Condition Value")) if clean(str(r.get("ConditionValue"))).upper() != "N/A" else None,
        "deadline_kind": clean(r.get("DeadlineKind") or r.get("Deadline Kind") or r.get("deadline_kind")),
        "month": m,
        "day": as_int(r.get("Day")),
        "month_name": month_name(m) if m else "",
        "offset_months": offset_months,
        "offset_days": offset_days,
        "text": clean(r.get("DisplayText") or r.get("Display Text") or r.get("display_text")),
    }

def validate_threshold_data(row: Dict[str, Any], debug: bool = False) -> bool:
    """Validate threshold row has required fields when applicable."""
    if row.get("requirement_applies", "").lower() in RequirementStatus.YES_VALUES:
        if row.get("op") and not row.get("amount"):
            if debug:
                print(f"Warning: Threshold operator without amount in group {row.get('group_id')}")
            return False
    return True

def calculate_deadline_from_cit(deadline_info: Dict, cit_deadlines: List[Dict], fye: str = "") -> Dict[str, Any]:
    """
    Calculate actual TP deadline date when it references CIT/tax return deadline.
    """
    if not deadline_info or not cit_deadlines or not relativedelta:
        return deadline_info
    
    deadline_kind = (deadline_info.get("deadline_kind") or "").upper()
    event_anchor = (deadline_info.get("event_anchor") or "").upper()
    
    # Check if this deadline references tax return
    tax_return_indicators = [
        "RETURN_DUE_DATE", "TAX_RETURN", "CIT_RETURN", 
        "CORPORATE_TAX", "WITH_RETURN", "FILING_DATE", "TAX_FILING"
    ]
    
    is_tax_return_based = (
        deadline_kind in tax_return_indicators or
        any(indicator in event_anchor for indicator in tax_return_indicators) or
        "tax return" in (deadline_info.get("text") or "").lower()
    )
    
    if not is_tax_return_based:
        return deadline_info
    
    # Get the appropriate CIT deadline
    cit_deadline = cit_deadlines[0] if cit_deadlines else None
    if not cit_deadline:
        return deadline_info
    
    # Calculate the CIT deadline date
    cit_date = None
    cit_kind = (cit_deadline.get("deadline_kind") or "").upper()
    
    if cit_kind == "FIXED_DATE":
        month = cit_deadline.get("month")
        day = cit_deadline.get("day")
        if month and day:
            try:
                if fye:
                    fye_date = datetime.strptime(fye, "%Y-%m-%d")
                    year = fye_date.year + 1
                else:
                    year = datetime.now().year + 1
                cit_date = datetime(year, month, day)
            except ValueError:
                pass
    
    elif cit_kind == "FYE_RELATIVE" and fye:
        try:
            fye_date = datetime.strptime(fye, "%Y-%m-%d")
            offset_months = cit_deadline.get("offset_months", 0) or 0
            offset_days = cit_deadline.get("offset_days", 0) or 0
            cit_date = fye_date + relativedelta(months=offset_months, days=offset_days)
        except ValueError:
            pass
    
    if not cit_date:
        return deadline_info
    
    # Calculate the TP deadline based on the CIT date
    tp_offset_months = deadline_info.get("offset_months", 0) or 0
    tp_offset_days = deadline_info.get("offset_days", 0) or 0
    
    updated = deadline_info.copy()
    
    if tp_offset_months == 0 and tp_offset_days == 0:
        # TP deadline is same as CIT deadline
        calculated_date = cit_date
        updated["calculated_date"] = calculated_date.strftime("%Y-%m-%d")
        updated["month"] = calculated_date.month
        updated["day"] = calculated_date.day
        updated["month_name"] = calendar.month_abbr[calculated_date.month]
        if not updated.get("text"):
            updated["text"] = f"Due with tax return ({calculated_date.strftime('%B %d, %Y')})"
    else:
        # TP deadline is offset from CIT deadline
        calculated_date = cit_date + relativedelta(months=tp_offset_months, days=tp_offset_days)
        updated["calculated_date"] = calculated_date.strftime("%Y-%m-%d")
        updated["month"] = calculated_date.month
        updated["day"] = calculated_date.day
        updated["month_name"] = calendar.month_abbr[calculated_date.month]
        if not updated.get("text"):
            updated["text"] = f"{tp_offset_months}m {tp_offset_days}d after tax return ({calculated_date.strftime('%B %d, %Y')})"
    
    return updated

# ------------------------ compiler core ----------------------------

def compile_rules(excel_path: Path, fye: str = "", debug: bool = False) -> Dict[str, Any]:
    """
    Compile transfer pricing rules from Excel sheets into JSON format.
    
    Args:
        excel_path: Path to Rule Tables.xlsx
        fye: Fiscal year-end (YYYY-MM-DD) for relative deadlines
        debug: Enable verbose output
        
    Returns:
        Dictionary with compiled rules for all countries
    """
    xls = pd.ExcelFile(excel_path)

    # Load all sheets (0..6)
    df_countries = load_sheet(xls, SheetNames.COUNTRY_REGIONS, required=True, debug=debug)
    df_lf_th = load_sheet(xls, SheetNames.LF_THRESHOLD, required=True, debug=debug)
    df_lf_dl = load_sheet(xls, SheetNames.LF_DEADLINES, required=True, debug=debug)
    df_mf_th = load_sheet(xls, SheetNames.MF_THRESHOLD, required=True, debug=debug)
    df_mf_dl = load_sheet(xls, SheetNames.MF_DEADLINES, required=True, debug=debug)
    df_forms = load_sheet(xls, SheetNames.TP_FORMS, required=True, debug=debug)
    df_cbcr = load_sheet(xls, SheetNames.CBCR, required=True, debug=debug)
    df_cit = load_sheet(xls, SheetNames.CIT_DEADLINES, required=False, debug=debug)  # NEW - optional

    if debug:
        print("[sizes]",
              f"countries={len(df_countries)} lf_th={len(df_lf_th)} lf_dl={len(df_lf_dl)}",
              f"mf_th={len(df_mf_th)} mf_dl={len(df_mf_dl)} forms={len(df_forms)} cbcr={len(df_cbcr)}",
              f"cit={len(df_cit) if not df_cit.empty else 0}")

    # Load country to region mapping (maps both names AND codes to regions)
    name_to_region, code_to_name = load_country_map(df_countries, debug=debug)
    countries = {}
    unmatched = set()

    # --- LF / TPD Thresholds (DocTypeNormalized should be LF) ---
    if not df_lf_th.empty:
        for _, r in df_lf_th.iterrows():
            j = clean(r.get("Jurisdiction"))
            c = ensure_country(countries, j, name_to_region, code_to_name, debug)
            if not c:
                unmatched.add(j)
                continue
            # Visibility: hide groups when RequirementApplies = "No"
            row = pack_threshold_row(r)
            row["doc_type"] = clean(r.get("DocTypeNormalized") or DocType.LF)
            if validate_threshold_data(row, debug):
                c["lf_tpd_thresholds"].append(row)

    # --- LF / TPD Deadlines ---
    if not df_lf_dl.empty:
        for _, r in df_lf_dl.iterrows():
            j = clean(r.get("Jurisdiction"))
            c = ensure_country(countries, j, name_to_region, code_to_name, debug)
            if not c:
                unmatched.add(j)
                continue
            row = pack_deadline_row(r)
            row["doc_type"] = clean(r.get("DocTypeNormalized") or DocType.LF)
            c["lf_tpd_deadlines"].append(row)

    # --- MF Thresholds ---
    if not df_mf_th.empty:
        for _, r in df_mf_th.iterrows():
            j = clean(r.get("Jurisdiction"))
            c = ensure_country(countries, j, name_to_region, code_to_name, debug)
            if not c:
                unmatched.add(j)
                continue
            row = pack_threshold_row(r)
            row["doc_type"] = clean(r.get("DocTypeNormalized") or DocType.MF)
            if validate_threshold_data(row, debug):
                c["mf_thresholds"].append(row)

    # --- MF Deadlines ---
    if not df_mf_dl.empty:
        for _, r in df_mf_dl.iterrows():
            j = clean(r.get("Jurisdiction"))
            c = ensure_country(countries, j, name_to_region, code_to_name, debug)
            if not c:
                unmatched.add(j)
                continue
            row = pack_deadline_row(r)
            row["doc_type"] = clean(r.get("DocTypeNormalized") or DocType.MF)
            c["mf_deadlines"].append(row)

    # --- TP Forms / Disclosures ---
    if not df_forms.empty:
        for _, r in df_forms.iterrows():
            j = clean(r.get("Jurisdiction"))
            c = ensure_country(countries, j, name_to_region, code_to_name, debug)
            if not c:
                unmatched.add(j)
                continue
            row = pack_form_row(r)
            row["doc_type"] = clean(r.get("DocTypeNormalized") or DocType.FM)
            c["tp_forms"].append(row)

    # --- CbCR Notifications ---
    if not df_cbcr.empty:
        for _, r in df_cbcr.iterrows():
            j = clean(r.get("Jurisdiction"))
            c = ensure_country(countries, j, name_to_region, code_to_name, debug)
            if not c:
                unmatched.add(j)
                continue
            row = pack_cbcr_row(r)
            
            # Hide entirely if neither required nor included in CIT
            req = row.get("required", "").lower()
            in_cit = row.get("included_in_cit", "").lower()
            
            is_required = req in RequirementStatus.YES_VALUES
            is_in_cit = in_cit in RequirementStatus.YES_VALUES
            
            if not (is_required or is_in_cit):
                continue  # Hide if neither required nor included in CIT
                
            c["cbcr"] = row  # single object per country; last one wins if duplicates

    # REPLACE your existing "# --- CIT Deadlines ---" section with this:

    # --- CIT Deadlines ---
    if not df_cit.empty:
        if debug:
            print(f"[cit] Processing {len(df_cit)} CIT deadline rows")
            
        cit_added = 0
        for idx, r in df_cit.iterrows():
            # Get jurisdiction code from the specific column name
            j = clean(r.get("Jurisdiction (3-letter code)"))
            
            if not j:
                continue
            
            # Convert code to full name using code_to_name mapping
            full_country_name = code_to_name.get(j.upper(), j)
            
            # Find the country by its full name
            country_found = None
            for key, country_data in countries.items():
                if country_data["name"] == full_country_name:
                    country_found = country_data
                    break
            
            if not country_found:
                # Try to find by the code directly (fallback)
                for key, country_data in countries.items():
                    if key == j.lower():
                        country_found = country_data
                        break
            
            if not country_found:
                if debug:
                    print(f"[cit] Could not find country for code {j} (mapped to {full_country_name})")
                continue
            
            # Pack the CIT row data
            row = pack_cit_row(r)
            country_found["cit_deadlines"].append(row)
            cit_added += 1
            
            if debug and idx < 3:
                print(f"[cit] Added CIT for {country_found.get('name')}: {row.get('text', '')[:50]}...")
        
        if debug:
            print(f"[cit] Successfully added {cit_added} CIT deadline entries")














    # Sort groups by group_id + seq for stable display
    def sort_group(items: List[Dict]) -> List[Dict]:
        """Sort items by group_id and sequence number."""
        return sorted(items, key=lambda x: (x.get("group_id", ""), x.get("seq", 0)))

    for k, c in countries.items():
        c["lf_tpd_thresholds"] = sort_group(c["lf_tpd_thresholds"])
        c["lf_tpd_deadlines"] = sort_group(c["lf_tpd_deadlines"])
        c["mf_thresholds"] = sort_group(c["mf_thresholds"])
        c["mf_deadlines"] = sort_group(c["mf_deadlines"])
        c["tp_forms"] = sort_group(c["tp_forms"])
        c["cit_deadlines"] = sort_group(c["cit_deadlines"])  # NEW - sort CIT deadlines
        # cbcr is a single dict (or None)
    
    # Enhance TP deadlines with CIT-based calculations
    if relativedelta and fye:  # Only if we have dateutil and FYE
        for country_key, country_data in countries.items():
            cit_deadlines = country_data.get("cit_deadlines", [])
            if cit_deadlines:
                # Process each type of deadline
                for i, deadline in enumerate(country_data.get("lf_tpd_deadlines", [])):
                    country_data["lf_tpd_deadlines"][i] = calculate_deadline_from_cit(deadline, cit_deadlines, fye)
                
                for i, deadline in enumerate(country_data.get("mf_deadlines", [])):
                    country_data["mf_deadlines"][i] = calculate_deadline_from_cit(deadline, cit_deadlines, fye)
                
                for i, form in enumerate(country_data.get("tp_forms", [])):
                    country_data["tp_forms"][i] = calculate_deadline_from_cit(form, cit_deadlines, fye)
                
                if country_data.get("cbcr"):
                    country_data["cbcr"] = calculate_deadline_from_cit(country_data["cbcr"], cit_deadlines, fye)
                
                if debug:
                    print(f"[cit_enhance] Applied CIT calculations for {country_data.get('name')}")

    compiled = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "excel_source": str(excel_path),
        "fye": fye or "",
        "countries": sorted(countries.values(), key=lambda x: (x["region"], x["name"].lower()))
    }

    if debug:
        print(f"[result] countries compiled: {len(compiled['countries'])}")
        if unmatched:
            bad = sorted({u for u in unmatched if u})
            print(f"[warn] jurisdictions not matched to Country/Region mapping (sample): {bad[:20]}")

    return compiled

# ------------------------------ CLI -------------------------------

@dataclass
class CompilerConfig:
    """Configuration for the rules compiler."""
    excel_path: Path
    output_path: Path
    fye: str = ""
    debug: bool = False
    
    def validate(self):
        """Validate configuration settings."""
        if not self.excel_path.exists():
            raise FileNotFoundError(f"Excel not found: {self.excel_path}")

def main():
    """Main CLI entry point for the rules compiler."""
    ap = argparse.ArgumentParser(
        description="Compile Rule Tables.xlsx (tabs 0..6) into rules.json using country names."
    )
    ap.add_argument("--excel", required=True, help="Path to Rule Tables.xlsx")
    ap.add_argument("--out", required=True, help="Path to write rules.json")
    ap.add_argument("--fye", default="", help="Fiscal year-end (YYYY-MM-DD) for relative deadlines")
    ap.add_argument("--debug", action="store_true", help="Verbose diagnostics")
    args = ap.parse_args()

    # Create and validate configuration
    config = CompilerConfig(
        excel_path=Path(args.excel),
        output_path=Path(args.out),
        fye=args.fye,
        debug=args.debug
    )
    
    try:
        config.validate()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Compile the rules
    try:
        data = compile_rules(config.excel_path, fye=config.fye, debug=config.debug)
    except Exception as e:
        print("❌ Compile failed:", e)
        if config.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    # Validate output structure
    if not isinstance(data, dict) or "countries" not in data:
        print("❌ Unexpected output (no 'countries').")
        sys.exit(1)

    # Write output file
    try:
        config.output_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), 
            encoding="utf-8"
        )
        print(f"✅ Wrote {config.output_path} ({len(data['countries'])} countries)")
    except Exception as e:
        print(f"❌ Failed to write output: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()