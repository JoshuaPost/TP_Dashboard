import argparse, json, re, sys, calendar
from datetime import datetime
from pathlib import Path
import pandas as pd

# ------------------------------ utils ------------------------------

HARD_PAT = re.compile(
    r"(submit|file|due|deadline|lodge|lodgment|upload|deliver|sign|attest|statutory|"
    r"by\s+\d|by\s+end\s+of|last\s+day\s+of|within\s+\d+\s+(day|days|month|months)\s+(after|of)\s+(fye|year|year-end))",
    re.IGNORECASE
)
SOFT_PAT = re.compile(
    r"(prepare|maintain|upon\s+request|within\s+\d+\s+(day|days)\s+of\s+(audit|request|notice)|"
    r"on\s+demand|keep\s+on\s+file|produce\s+upon\s+request)",
    re.IGNORECASE
)
SEP = re.compile(r"\s*[|;]\s*")

MONTH_MAP = {
    'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
    'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12
}
MONTH_RE = re.compile(
    r'\b('
    r'jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
    r'jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|'
    r'nov(?:ember)?|dec(?:ember)?'
    r')\b', re.IGNORECASE
)

def clean(x):
    if pd.isna(x): return ""
    return str(x).strip()

def split_multi(text):
    if not text: return []
    return [p.strip(" -–—\t") for p in SEP.split(text) if p.strip()]

def classify_deadline(text):
    if not text: return ""
    is_hard = bool(HARD_PAT.search(text))
    is_soft = bool(SOFT_PAT.search(text))
    if is_hard and not is_soft: return "HARD"
    if is_soft and not is_hard: return "SOFT"
    if is_hard and is_soft: return "HARD"  # bias to HARD when both appear
    return ""

def _month_name(m: int) -> str:
    return calendar.month_abbr[m] if m and 1 <= m <= 12 else ""

def _month_from_text(text: str, fye_str: str) -> int | None:
    """
    Returns month number (1..12) or None.
    Treat 'upon request' / 'not applicable' as undated (None).
    Handles: month names, DD/MM(/YYYY), 'N months after year-end', bare 'year-end'.
    """
    if not text:
        return None
    t = text.lower()

    # Undated phrases -> None (keeps them out of January)
    if 'upon request' in t or 'not applicable' in t:
        return None

    # Month names
    m = MONTH_RE.search(t)
    if m:
        return MONTH_MAP[m.group(1)[:3].lower()]

    # Numeric dates (DD/MM, DD-MM, DD.MM)
    m = re.search(r'\b([0-3]?\d)\s*[/\-.]\s*(0?[1-9]|1[0-2])\b', t)
    if m:
        return int(m.group(2))

    # Relative months after year-end / FYE
    rel = re.search(r'(\d+)\s*(?:month|months)\s+after\s+(?:fye|fy-?end|year[-\s]?end)', t)
    try:
        fye = datetime.fromisoformat(fye_str) if fye_str else None
    except Exception:
        fye = None

    if rel and fye:
        offset = int(rel.group(1))
        base = fye.month
        return ((base - 1 + offset) % 12) + 1

    # Bare year-end
    if fye and ('year-end' in t or 'year end' in t or 'fy-end' in t or 'fy end' in t):
        return fye.month

    # Common literal Dec 31
    if re.search(r'\b31\s*[/\-.]\s*12\b', t):
        return 12

    return None

def _decorate_deadline(d: dict, fye: str) -> dict:
    txt = d.get('text', '') or d.get('deadline', '')
    m = _month_from_text(txt, fye)
    if m:
        d['month'] = m
        d['month_name'] = _month_name(m)
    else:
        d['month'] = None
        d['month_name'] = ""
    return d

def norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def find_col(cols, *candidates):
    """Return the first matching column (case-insensitive) with contains() fallback."""
    lc = {c.lower(): c for c in cols}
    for cand in candidates:
        key = cand.lower()
        if key in lc: return lc[key]
    for c in cols:
        cl = c.lower()
        for cand in candidates:
            if cand.lower() in cl:
                return c
    return None

# ------------------------------ ISO map ------------------------------

def load_iso_codes(df_iso: pd.DataFrame, debug=False):
    df_iso = norm_cols(df_iso)
    country_col = find_col(df_iso.columns, "Country", "Jurisdiction")
    iso_col     = find_col(df_iso.columns, "Code (ISO2)", "ISO2", "ISO-2", "ISO 2", "Code")
    region_col  = find_col(df_iso.columns, "Region")
    if debug:
        print(f"[iso] columns found: country={country_col}, iso2={iso_col}, region={region_col}")
    if not country_col or not iso_col:
        return {}, {}, {}
    name_to_iso, iso_to_name, name_to_region = {}, {}, {}
    for _, r in df_iso.iterrows():
        nm  = clean(r.get(country_col))
        iso = clean(r.get(iso_col)).upper()
        reg = clean(r.get(region_col)) if region_col else ""
        if nm and iso:
            name_to_iso[nm.lower()] = iso
            iso_to_name[iso] = nm
            name_to_region[nm.lower()] = reg
    return (name_to_iso, iso_to_name, name_to_region)

def ensure_country(registry: dict, name_to_iso: dict, name_to_region: dict, j_name: str):
    key = clean(j_name).lower()
    if not key: return None
    if key not in name_to_iso:
        return None
    if key not in registry:
        nm  = j_name.strip()
        iso = name_to_iso[key]
        reg = name_to_region.get(key, "")
        registry[key] = {
            "name": nm,
            "iso2": iso,
            "region": reg,
            "lf_tpd_thresholds": [],
            "lf_tpd_deadlines": [],
            "mf_thresholds": [],
            "mf_deadlines": [],
            "tp_forms": [],
            "cbcr": None
        }
    return registry[key]

# ------------------------------ compiler ------------------------------

def compile_rules(excel_path: Path, fye: str = "", debug: bool = False):
    xls = pd.ExcelFile(excel_path)

    need = {
        "iso": "Iso Codes",
        "tpdlf_thr": "TPDLF Thresholds",
        "tpd_dead": "TPD Deadlines",
        "mf_thr": "MF Thresholds",
        "mf": "MF",
        "forms": "Submission Deadlines",
        "cbcr": "CBCR Notificaitons",
    }

    def load(name):
        sheet = need[name]
        if sheet not in xls.sheet_names:
            if debug: print(f"[warn] Missing sheet: {sheet}")
            return pd.DataFrame()
        df = pd.read_excel(excel_path, sheet_name=sheet)
        return norm_cols(df)

    df_iso       = load("iso")
    df_tpdlf_thr = load("tpdlf_thr")
    df_tpd_dead  = load("tpd_dead")
    df_mf_thr    = load("mf_thr")
    df_mf        = load("mf")
    df_forms     = load("forms")
    df_cbcr      = load("cbcr")

    if debug:
        print(f"[sheets] sizes: iso={len(df_iso)}, tpdlf_thr={len(df_tpdlf_thr)}, tpd_dead={len(df_tpd_dead)}, "
              f"mf_thr={len(df_mf_thr)}, mf={len(df_mf)}, forms={len(df_forms)}, cbcr={len(df_cbcr)}")

    name_to_iso, iso_to_name, name_to_region = load_iso_codes(df_iso, debug=debug)
    countries = {}  # key = country_name.lower()
    unmatched = set()

    def jcol(df):
        return find_col(df.columns, "Jurisdiction", "Country")

    # ---- TPD/LF thresholds ----
    if not df_tpdlf_thr.empty:
        jc = jcol(df_tpdlf_thr)
        at = find_col(df_tpdlf_thr.columns, "Applicable Documentation Type")
        th = find_col(df_tpdlf_thr.columns, "Financial Threshold(s)")
        mt = find_col(df_tpdlf_thr.columns, "Metric/Basis Used")
        nd = find_col(df_tpdlf_thr.columns, "Additional Threshold Details")
        for _, r in df_tpdlf_thr.iterrows():
            j = clean(r.get(jc))
            c = ensure_country(countries, name_to_iso, name_to_region, j)
            if not c:
                unmatched.add(j); continue
            c["lf_tpd_thresholds"].append({
                "type": clean(r.get(at)),
                "thresholds": clean(r.get(th)),
                "metric": clean(r.get(mt)),
                "notes": clean(r.get(nd)),
            })

    # ---- TPD deadlines ----
    if not df_tpd_dead.empty:
        jc = jcol(df_tpd_dead)
        prep = find_col(df_tpd_dead.columns, "Preparation Deadline (Contemporaneous Requirement)")
        subm = find_col(df_tpd_dead.columns, "Submission Requirement (Statutory or Upon Request)")
        urd = find_col(df_tpd_dead.columns, "Deadline for Submission Upon Request (in Days)")
        for _, r in df_tpd_dead.iterrows():
            j = clean(r.get(jc))
            c = ensure_country(countries, name_to_iso, name_to_region, j)
            if not c:
                unmatched.add(j); continue

            prep_items = split_multi(clean(r.get(prep)))
            subm_items = split_multi(clean(r.get(subm)))

            for p in prep_items:
                c["lf_tpd_deadlines"].append(_decorate_deadline(
                    {"kind":"prepare", "text": p, "class": classify_deadline(p) or "SOFT"}, fye))

            for s in subm_items:
                c["lf_tpd_deadlines"].append(_decorate_deadline(
                    {"kind":"submit", "text": s, "class": classify_deadline(s) or "HARD"}, fye))

            ur = clean(r.get(urd))
            if ur:
                txt = f"Provide upon request within {ur} days"
                c["lf_tpd_deadlines"].append(_decorate_deadline(
                    {"kind":"upon_request", "text": txt, "class": classify_deadline(txt) or "SOFT"}, fye))

    # ---- MF thresholds ----
    if not df_mf_thr.empty:
        jc = jcol(df_mf_thr)
        th = find_col(df_mf_thr.columns, "Financial Threshold(s) for Applicability")
        mt = find_col(df_mf_thr.columns, "Metric / Basis Used to Determine Threshold")
        nd = find_col(df_mf_thr.columns, "Additional Details / Alternate Triggers")
        for _, r in df_mf_thr.iterrows():
            j = clean(r.get(jc))
            c = ensure_country(countries, name_to_iso, name_to_region, j)
            if not c:
                unmatched.add(j); continue
            c["mf_thresholds"].append({
                "thresholds": clean(r.get(th)),
                "metric": clean(r.get(mt)),
                "notes": clean(r.get(nd)),
            })

    # ---- MF deadlines ----
    if not df_mf.empty:
        jc = jcol(df_mf)
        sd = find_col(df_mf.columns, "Master File Submission Deadline")
        dt = find_col(df_mf.columns, "Details on Submission / Preparation Date")
        for _, r in df_mf.iterrows():
            j = clean(r.get(jc))
            c = ensure_country(countries, name_to_iso, name_to_region, j)
            if not c:
                unmatched.add(j); continue

            for item in split_multi(clean(r.get(sd))):
                if item:
                    c["mf_deadlines"].append(_decorate_deadline(
                        {"text": item, "class": classify_deadline(item) or "HARD"}, fye))
            for item in split_multi(clean(r.get(dt))):
                if item:
                    c["mf_deadlines"].append(_decorate_deadline(
                        {"text": item, "class": classify_deadline(item) or "SOFT"}, fye))

    # ---- TP forms / disclosures ----
    if not df_forms.empty:
        jc = jcol(df_forms)
        nm = find_col(df_forms.columns, "TP Form, Return, or Specific Disclosure")
        dl = find_col(df_forms.columns, "Submission Deadline (for FYE 31/12)")
        for _, r in df_forms.iterrows():
            j = clean(r.get(jc))
            c = ensure_country(countries, name_to_iso, name_to_region, j)
            if not c:
                unmatched.add(j); continue
            name = clean(r.get(nm))
            for item in split_multi(clean(r.get(dl))):
                c["tp_forms"].append(_decorate_deadline(
                    {"name": name, "deadline": item, "class": classify_deadline(item) or "HARD"}, fye))

   # ---- CbCR notifications ----
if not df_cbcr.empty:
    jc  = jcol(df_cbcr)
    dl  = find_col(
        df_cbcr.columns,
        "CbCR Notification Deadline (for Dec 31 FYE)",
        "CbCR Notification Deadline",
        "CBCR Notification Deadline",
        "Notification Deadline",
        "CbCR deadline"
    )
    cit = find_col(
        df_cbcr.columns,
        "Inclusion in CIT Return?",
        "Included in CIT return?",
        "Included in CIT?",
        "In CIT return?"
    )
    ann = find_col(
        df_cbcr.columns,
        "Annual Submission Required?",
        "Annual requirement?",
        "Annual?"
    )
    sfa = find_col(
        df_cbcr.columns,
        "Multiple Entities (Single Filing Allowed)?",
        "Multiple Entities (Single filer allowed)?",
        "Single filer allowed?"
    )

    if debug:
        print(f"[cbcr] cols: juris={jc}, deadline={dl}, in_cit={cit}, annual={ann}, single={sfa}")

    for _, r in df_cbcr.iterrows():
        j = clean(r.get(jc))
        c = ensure_country(countries, name_to_iso, name_to_region, j)
        if not c:
            unmatched.add(j)
            continue

        deadline_text = clean(r.get(dl))
        in_cit_val    = clean(r.get(cit))
        annual_val    = clean(r.get(ann))
        single_val    = clean(r.get(sfa))

        # If blank AND not included in CIT → skip Nt entirely
        if not deadline_text and not in_cit_val:
            continue  # leave c["cbcr"] as None

        # If blank BUT included in CIT return → set an explicit message
        if not deadline_text and in_cit_val:
            deadline_text = "Included in CIT return (no separate notification)"

        c["cbcr"] = _decorate_deadline({
            "deadline": deadline_text,
            "in_cit": in_cit_val,
            "annual": annual_val,
            "single_filer_ok": single_val,
            # HARD if explicit filing/date words; else SOFT (you can flip if you want CIT-included to be HARD)
            "class": classify_deadline(deadline_text) or ("HARD" if "included in cit" in deadline_text.lower() else "SOFT")
        }, fye)


    compiled = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "excel_source": str(excel_path),
        "fye": fye or "",
        "countries": sorted(countries.values(), key=lambda x: x["name"].lower())
    }

    if debug:
        print(f"[result] countries compiled: {len(compiled['countries'])}")
        if unmatched:
            bad = sorted({u for u in unmatched if u})
            print(f"[warn] jurisdictions not matched to Iso Codes (up to 20): {bad[:20]}")

    return compiled

# ------------------------------ CLI ------------------------------

def main():
    p = argparse.ArgumentParser(description="Compile 'Rule Tables.xlsx' -> rules.json (normalized + classified).")
    p.add_argument("--excel", required=True, help="Path to Rule Tables.xlsx")
    p.add_argument("--out", required=True, help="Path to write rules.json")
    p.add_argument("--fye", default="", help="Fiscal year-end in ISO format, e.g., 2025-12-31")
    p.add_argument("--debug", action="store_true", help="Print diagnostics")
    args = p.parse_args()

    excel_path = Path(args.excel)
    out_path = Path(args.out)
    if not excel_path.exists():
        print(f"❌ Excel not found: {excel_path}")
        sys.exit(1)

    try:
        data = compile_rules(excel_path, fye=args.fye, debug=args.debug)
    except Exception as e:
        print("❌ Compile failed:", e)
        import traceback; traceback.print_exc()
        sys.exit(1)

    if not isinstance(data, dict) or "countries" not in data:
        print("❌ Unexpected compiler output (no 'countries'). Re-run with --debug.")
        sys.exit(1)

    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✅ Wrote {out_path} ({len(data['countries'])} countries)")

if __name__ == "__main__":
    main()
