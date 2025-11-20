import pandas as pd
import json, re, argparse
from pathlib import Path
from datetime import datetime

# -----------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------
BASE_DIR = Path(r"C:\Users\RC19361\OneDrive - Ryan LLC\TP_Dashboard")
EXCEL_PATH = BASE_DIR / "Compliance Requirementsv2.xlsx"
MAPPING_PATH = BASE_DIR / "tp_requirements_mapping.json"
MARKDOWN_PATH = BASE_DIR / "tp_requirements_review.md"
CSS_PATH = BASE_DIR / "Ryan_format.css"
OUTPUT_HTML = BASE_DIR / "tp_dashboard.html"

# -----------------------------------------------------------
# HELPER FUNCTIONS
# -----------------------------------------------------------

def norm(s):
    return re.sub(r'\s+', ' ', str(s).strip().lower())

def to_text(x):
    if pd.isna(x):
        return ""
    return str(x).strip()

def bulletize_deadlines(text):
    """Convert '|' or ';' separated deadlines into bullet list."""
    if not text:
        return ""
    parts = [p.strip(" -–—\t") for p in re.split(r"[|;]+", text) if p.strip()]
    return "\n".join(f"- {p}" for p in parts)

def linkify_forms(text):
    """Add placeholder links for known TP forms."""
    if not text:
        return ""
    known = [
        (r"\b3ceb\b", "Form 3CEB"),
        (r"\b17-?4\b", "Schedule 17-4"),
        (r"\bt106\b", "Form T106"),
        (r"\b232\b", "Form 232"),
        (r"\b275\.?mf\b|\b275\s*\.?\s*mf\b", "Form 275.MF"),
        (r"\btransaction matrix\b", "Transaction Matrix"),
        (r"\bcit return\b|\bincome tax return\b", "CIT Return"),
    ]
    out = text
    for pat, label in known:
        out = re.sub(pat, f"[{label}](#)", out, flags=re.IGNORECASE)
    return out

def guess_quarter(text):
    """Roughly assign a deadline to a quarter."""
    t = text.lower()
    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    for m, n in months.items():
        if m in t:
            if n <= 3: return "Q1"
            elif n <= 6: return "Q2"
            elif n <= 9: return "Q3"
            else: return "Q4"
    return "Unscheduled"

# -----------------------------------------------------------
# MAIN LOGIC
# -----------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate TP dashboard from Excel.")
    parser.add_argument("--countries", type=str, required=True,
                        help="Comma-separated list of countries (e.g., 'Germany,France,Italy')")
    args = parser.parse_args()
    selected_countries = [c.strip() for c in args.countries.split(",") if c.strip()]

    print(f"Selected countries: {', '.join(selected_countries)}")

    # Load mapping
    with open(MAPPING_PATH, "r", encoding="utf-8") as f:
        mapping = json.load(f)

    # Load Excel
    df = pd.read_excel(EXCEL_PATH)
    print(f"Loaded {len(df)} rows from Excel")

    # Resolve columns
    def get_col(name):
        if name not in mapping or not mapping[name]:
            return None
        return mapping[name]

    country_col = get_col("Country")
    region_col = get_col("Region")
    mf_col = get_col("MF Requirements/Thresholds")
    lf_col = get_col("LF Requirements/Thresholds")
    forms_col = get_col("Forms/Disclosures")
    cbcr_col = get_col("CBCR Notifications")
    deadlines_col = get_col("Deadlines")
    notes_col = get_col("Notes/Rule Notes")

    # Filter by countries
    df_filtered = df[df[country_col].isin(selected_countries)]
    if df_filtered.empty:
        print("No matching countries found in Excel.")
        return

    # -------------------------------------------------------
    # STEP 1: Generate Markdown
    # -------------------------------------------------------
    lines = []
    lines.append("# TP Compliance Requirements – Review Source (Editable)")
    lines.append("")
    lines.append("> Automatically generated from Compliance Requirementsv2.xlsx")
    lines.append("")

    current_region = None
    for _, r in df_filtered.iterrows():
        country = to_text(r.get(country_col, ""))
        region = to_text(r.get(region_col, "")) or "Unassigned"
        if current_region != region:
            lines.append(f"\n## {region}")
            current_region = region

        mf = to_text(r.get(mf_col, ""))
        lf = to_text(r.get(lf_col, ""))
        forms = linkify_forms(to_text(r.get(forms_col, "")))
        cbcr = linkify_forms(to_text(r.get(cbcr_col, "")))
        deadlines = bulletize_deadlines(to_text(r.get(deadlines_col, "")))
        notes = to_text(r.get(notes_col, ""))

        anchor = re.sub(r"[^a-z0-9]+", "-", country.lower()).strip("-")
        lines.append(f"\n### {country} {{#{anchor}}}")
        lines.append("**Thresholds & Requirements**")
        lines.append(f"- **MF**: {mf or '—'}")
        lines.append(f"- **LF**: {lf or '—'}")
        lines.append("")
        lines.append("**Forms & Disclosures**")
        lines.append(f"- {forms or '—'}")
        lines.append("")
        if cbcr_col:
            lines.append("**CbCR Notifications**")
            lines.append(f"- {cbcr or '—'}")
            lines.append("")
        lines.append("**Deadlines**")
        lines.append(deadlines or "- —")
        lines.append("")
        if notes:
            lines.append("**Notes**")
            lines.append(f"- {notes}")
            lines.append("")

    MARKDOWN_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Markdown written to {MARKDOWN_PATH}")

    # -------------------------------------------------------
    # STEP 2: Generate HTML
    # -------------------------------------------------------
    html_header = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>TP Dashboard – {', '.join(selected_countries)}</title>
<link rel="stylesheet" href="{CSS_PATH.name}">
</head>
<body>
<div class="header">
  <h1>TP Dashboard – {', '.join(selected_countries)}</h1>
  <div class="header-info">
    <div class="header-stat">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
    <div class="header-stat">Countries: {len(selected_countries)}</div>
  </div>
</div>
<div class="nav-tabs">
  <div class="nav-tab active" onclick="showView('summary')">Regional Summary</div>
  <div class="nav-tab" onclick="showView('details')">Country Details</div>
  <div class="nav-tab" onclick="showView('timeline')">Timeline</div>
</div>
<div class="content">
"""

    html_footer = """
</div>
<script>
function showView(id){
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
}
</script>
</body>
</html>"""

    # Build Summary View
    summary_html = '<div id="summary" class="view active">\n<div class="region-grid">'
    for region, sub in df_filtered.groupby(region_col):
        region = region or "Unassigned"
        summary_html += f'<div class="region-card"><div class="region-header">{region}<span class="region-stats">{len(sub)} countries</span></div><div class="entity-list">'
        for _, r in sub.iterrows():
            country = to_text(r.get(country_col, ""))
            badges = []
            if to_text(r.get(mf_col)): badges.append('<span class="status-badge status-mf">MF</span>')
            if to_text(r.get(lf_col)): badges.append('<span class="status-badge status-lf">LF</span>')
            if to_text(r.get(forms_col)): badges.append('<span class="status-badge status-form">Fm</span>')
            if to_text(r.get(cbcr_col)): badges.append('<span class="status-badge status-new">Nt</span>')
            summary_html += f'<div class="entity-item" onclick="showView(\'details\');document.getElementById(\'{country}\').scrollIntoView();"><div class="entity-name">{country}</div><div class="entity-status">{"".join(badges)}</div></div>'
        summary_html += '</div></div>'
    summary_html += '</div></div>'

    # Build Detail View
    detail_html = '<div id="details" class="view">\n'
    for _, r in df_filtered.iterrows():
        country = to_text(r.get(country_col, ""))
        region = to_text(r.get(region_col, "")) or "Unassigned"
        mf = to_text(r.get(mf_col, ""))
        lf = to_text(r.get(lf_col, ""))
        forms = linkify_forms(to_text(r.get(forms_col, "")))
        cbcr = linkify_forms(to_text(r.get(cbcr_col, "")))
        deadlines = bulletize_deadlines(to_text(r.get(deadlines_col, "")))
        notes = to_text(r.get(notes_col, ""))
        detail_html += f"""
<div id="{country}" class="country-detail">
  <div class="country-header">
    <div class="country-title"><h2>{country}</h2><div class="country-entity">{region}</div></div>
    <button class="back-button" onclick="showView('summary')">← Back</button>
  </div>
  <div class="requirement-grid">
    <div class="requirement-card"><h3>Master File</h3><div>{mf or '—'}</div></div>
    <div class="requirement-card"><h3>Local File</h3><div>{lf or '—'}</div></div>
    <div class="requirement-card"><h3>Forms / Disclosures</h3><div>{forms or '—'}</div></div>
    <div class="requirement-card"><h3>CbCR Notifications</h3><div>{cbcr or '—'}</div></div>
    <div class="requirement-card"><h3>Deadlines</h3><div>{deadlines or '—'}</div></div>
  </div>
  {'<div class="note-column"><h3>Notes</h3><p>'+notes+'</p></div>' if notes else ''}
</div>"""
    detail_html += '</div>'

    # Build Timeline View
    timeline_html = '<div id="timeline" class="view timeline-view">'
    timeline_html += '<h2>Timeline Overview</h2>'
    quarters = {"Q1": [], "Q2": [], "Q3": [], "Q4": [], "Unscheduled": []}
    for _, r in df_filtered.iterrows():
        deadlines = to_text(r.get(deadlines_col, ""))
        if not deadlines:
            continue
        q = guess_quarter(deadlines)
        quarters[q].append((to_text(r.get(country_col, "")), deadlines))
    for q, items in quarters.items():
        if not items: continue
        timeline_html += f'<div class="month-section"><div class="month-header">{q} Deadlines</div>'
        for c, d in items:
            timeline_html += f'<div class="deadline-item"><div class="deadline-country">{c}</div><div class="deadline-date">{d}</div></div>'
        timeline_html += '</div>'
    timeline_html += '</div>'

    html_full = html_header + summary_html + detail_html + timeline_html + html_footer
    OUTPUT_HTML.write_text(html_full, encoding="utf-8")
    print(f"HTML dashboard written to {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
