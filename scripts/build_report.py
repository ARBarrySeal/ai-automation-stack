"""
Build a Word report from lead pipeline output: an overview table of prospects,
then one section per company with contact notes and its cold-email draft.

Input is a JSON file (default examples/report_data.example.json):
  {"title": "...", "companies": [{name, naics, sector, awards, domain, ciso, contact_note}],
   "emails": {"<company name>": {"subject": "...", "body": "..."}},
   "action_items": ["..."], "notes": ["..."]}

  python build_report.py --input my_leads.json
Writes OUTPUT_DIR/Leads_Report.docx (or --output).
"""
import argparse
import json
from datetime import date

from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from _env import ROOT, OUTPUT_DIR, BUSINESS_NAME, CALENDLY_URL

COMPANIES = []
EMAILS = {}
DATA = {}


def set_cell_bg(cell, hex_color):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def add_header_row(table, texts, bg="1F3864"):
    row = table.rows[0]
    for i, text in enumerate(texts):
        cell = row.cells[i]
        cell.text = text
        set_cell_bg(cell, bg)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.runs[0]
        run.bold = True
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        run.font.size = Pt(9)


def style_body_cell(cell, text, bold=False, size=9, center=False):
    cell.text = text
    p = cell.paragraphs[0]
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if p.runs:
        r = p.runs[0]
        r.bold = bold
        r.font.size = Pt(size)


def main():
    doc = Document()

    # ── Page margins ──────────────────────────────────────────────────────────
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    # ── Title ─────────────────────────────────────────────────────────────────
    title = doc.add_heading(DATA.get("title", f"{BUSINESS_NAME} Lead Pipeline"), 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title.runs:
        run.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)

    sub = doc.add_paragraph(f"Outreach Campaign — Generated {date.today().isoformat()}")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.runs[0].font.size = Pt(11)
    sub.runs[0].italic = True

    doc.add_paragraph("")

    # ── Campaign Summary ──────────────────────────────────────────────────────
    doc.add_heading("Campaign Summary", 1)
    n = len(COMPANIES)
    summary_items = [
        ("Total companies identified", str(n)),
        ("NAICS sectors covered", ", ".join(sorted({f"{c['naics']} ({c['sector']})" for c in COMPANIES}))),
        ("Emails generated", f"{sum(1 for c in COMPANIES if c['name'] in EMAILS)} / {n}"),
        ("Domains confirmed", f"{sum(1 for c in COMPANIES if c.get('domain'))} / {n}"),
        ("Booking link in emails", CALENDLY_URL),
        ("Data source", DATA.get("source", "SAM.gov / USASpending.gov")),
    ]
    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    add_header_row(tbl, ["Field", "Value"])
    for label, value in summary_items:
        row = tbl.add_row()
        style_body_cell(row.cells[0], label, bold=True)
        style_body_cell(row.cells[1], value)
    tbl.columns[0].width = Inches(2.4)
    tbl.columns[1].width = Inches(4.6)

    doc.add_paragraph("")

    # ── Action Items ──────────────────────────────────────────────────────────
    doc.add_heading("Action Items Before Sending", 1)
    actions = DATA.get("action_items", [
        "Replace all [Recipient's Name] placeholders with real names before sending.",
        "Verify contact names on LinkedIn before using them in subject lines or openers.",
    ])
    for i, item in enumerate(actions, 1):
        p = doc.add_paragraph(style="List Number")
        p.add_run(item).font.size = Pt(10)

    doc.add_paragraph("")

    # ── Master Table ──────────────────────────────────────────────────────────
    doc.add_heading(f"All {len(COMPANIES)} Companies — Overview", 1)
    cols = ["#", "Company", "Sector", "DoD Awards", "Domain", "Contact / CISO", "Notes"]
    tbl2 = doc.add_table(rows=1, cols=len(cols))
    tbl2.style = "Table Grid"
    add_header_row(tbl2, cols)
    widths = [Inches(0.3), Inches(1.9), Inches(1.1), Inches(0.75), Inches(1.3), Inches(1.2), Inches(1.9)]
    for i, w in enumerate(widths):
        for cell in tbl2.columns[i].cells:
            cell.width = w

    for i, co in enumerate(COMPANIES, 1):
        row = tbl2.add_row()
        cells = row.cells
        style_body_cell(cells[0], str(i), center=True, size=8)
        style_body_cell(cells[1], co["name"], bold=True, size=8)
        style_body_cell(cells[2], co["sector"], size=8)
        style_body_cell(cells[3], co["awards"], center=True, size=8)
        style_body_cell(cells[4], co.get("domain") or "—", size=8)
        style_body_cell(cells[5], co.get("ciso", "—"), size=8)
        style_body_cell(cells[6], co["contact_note"], size=7)
        # Alternate row shading
        if i % 2 == 0:
            for c in cells:
                set_cell_bg(c, "E8EDF5")

    doc.add_page_break()

    # ── Individual Company Sections ───────────────────────────────────────────
    doc.add_heading("Company Profiles & Cold Emails", 1)

    for i, co in enumerate(COMPANIES, 1):
        # Section header
        h = doc.add_heading(f"{i}. {co['name']}", 2)
        for run in h.runs:
            run.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)

        # Quick-facts table
        facts = doc.add_table(rows=1, cols=4)
        facts.style = "Table Grid"
        add_header_row(facts, ["Sector", "NAICS", "DoD Awards", "Domain"], bg="2E75B6")
        r = facts.add_row()
        style_body_cell(r.cells[0], co["sector"], size=9)
        style_body_cell(r.cells[1], co["naics"], size=9, center=True)
        style_body_cell(r.cells[2], co["awards"], size=9, center=True)
        style_body_cell(r.cells[3], co.get("domain") or "Not confirmed", size=9)

        doc.add_paragraph("")

        # Contact intel
        p = doc.add_paragraph()
        p.add_run("Contact Intelligence: ").bold = True
        p.add_run(f"{co.get('ciso', '—')}  |  ").font.size = Pt(10)
        note_run = p.add_run(co["contact_note"])
        note_run.font.size = Pt(9)
        note_run.italic = True

        doc.add_paragraph("")

        # Cold email
        email_key = co["name"]
        email = EMAILS.get(email_key)
        if email:
            ep = doc.add_paragraph()
            ep.add_run("Cold Email Draft").bold = True
            ep.runs[0].font.size = Pt(10)

            subj_p = doc.add_paragraph()
            subj_p.add_run("Subject: ").bold = True
            subj_p.add_run(email["subject"]).font.size = Pt(10)

            body_p = doc.add_paragraph()
            body_p.add_run(email["body"]).font.size = Pt(9)
            # Light background for email block
            for para in [subj_p, body_p]:
                pPr = para._p.get_or_add_pPr()
                shd = OxmlElement('w:shd')
                shd.set(qn('w:val'), 'clear')
                shd.set(qn('w:color'), 'auto')
                shd.set(qn('w:fill'), 'F0F4FA')
                pPr.append(shd)
        else:
            doc.add_paragraph("Email: timed out during generation — draft manually using the template above.").italic = True

        doc.add_paragraph("─" * 80)

    # ── Footer note ───────────────────────────────────────────────────────────
    doc.add_page_break()
    doc.add_heading("Data Quality Notes", 1)
    notes = DATA.get("notes", [])
    for n in notes:
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(n).font.size = Pt(10)

    doc.save(OUTPUT)
    print(f"Saved: {OUTPUT}")


def load(path):
    data = json.loads(open(path, encoding="utf-8").read())
    DATA.update(data)
    COMPANIES[:] = data.get("companies", [])
    EMAILS.update(data.get("emails", {}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default=str(ROOT / "examples" / "report_data.example.json"))
    parser.add_argument("--output", default=str(OUTPUT_DIR / "Leads_Report.docx"))
    args = parser.parse_args()
    OUTPUT = args.output
    load(args.input)
    main()
