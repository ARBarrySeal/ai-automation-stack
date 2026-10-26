"""
leads_pipeline.py — Find real defense contractors via USASpending.gov and generate outreach emails.

Usage:
  python leads_pipeline.py                                    # DEFAULT_CITY/STATE from .env, NAICS 541512, 5 emails
  python leads_pipeline.py --naics 336411 --count 3           # aircraft manufacturers
  python leads_pipeline.py --city "Huntsville" --state AL --naics 541330
  python leads_pipeline.py --nationwide --naics 541512        # all US, not just CA
  python leads_pipeline.py --state TX --naics 336411          # specific state
  python leads_pipeline.py --output leads_apr27.md            # save to file
  python leads_pipeline.py --push-crm                         # create contacts in HubSpot
  python leads_pipeline.py --draft-gmail                      # save emails to Gmail Drafts
  python leads_pipeline.py --push-crm --draft-gmail           # full automation
  python leads_pipeline.py --list-naics                       # show NAICS codes
"""
import argparse
import csv
import io
import os
import sys
import time

import requests

from _env import require as _require, env as _env, VERIFY_SSL, DEFAULT_CITY, DEFAULT_STATE, OUTPUT_DIR

if not VERIFY_SSL:
    _orig_request = requests.Session.request
    def _no_ssl_verify(self, method, url, **kwargs):
        kwargs.setdefault("verify", False)
        return _orig_request(self, method, url, **kwargs)
    requests.Session.request = _no_ssl_verify

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
N8N_LEADS_URL = "http://localhost:5678/webhook/leads"
HUBSPOT_BASE = "https://api.hubapi.com"
HUBSPOT_TOKEN = _require("HUBSPOT_TOKEN")
WEBHOOK_SECRET = _env("N8N_WEBHOOK_SECRET", "")

NAICS_PROFILES = {
    "541512": ("IT / cybersecurity services", "Systems handling CUI across networks, endpoints, and cloud"),
    "541330": ("engineering services", "Technical drawings, specs, and R&D data loaded with CUI"),
    "336411": ("aircraft manufacturing", "Directly in the defense supply chain with export-controlled data"),
    "336413": ("aircraft parts & aux equipment", "Handle CUI in design and manufacturing data"),
    "332994": ("small arms & ordnance", "Work in classified and CUI environments daily"),
    "541715": ("R&D / defense research", "Regularly handle CUI and controlled research data"),
    "541380": ("testing laboratories", "CUI in test data, reports, and equipment specs"),
    "541519": ("IT support services", "Manage networks and endpoints that store CUI"),
    "336992": ("military vehicles", "Defense supply chain with strict ITAR and CUI requirements"),
    "541611": ("management consulting", "Support DoD programs that require CMMC compliance"),
}


# ── HubSpot ───────────────────────────────────────────────────────────────────

def _hs_headers() -> dict:
    return {"Authorization": f"Bearer {HUBSPOT_TOKEN}", "Content-Type": "application/json"}


def hubspot_company_exists(name: str) -> bool:
    try:
        r = requests.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/companies/search",
            headers=_hs_headers(),
            json={
                "filterGroups": [{"filters": [{"propertyName": "name", "operator": "EQ", "value": name}]}],
                "properties": ["name"],
                "limit": 1,
            },
            timeout=10,
        )
        if r.ok:
            return r.json().get("total", 0) > 0
    except Exception as e:
        print(f"  [HubSpot search error] {e}", file=sys.stderr)
    return False


def hubspot_create_company(company: dict, naics: str, city: str, state: str, email_text: str) -> str | None:
    naics_label, _ = NAICS_PROFILES.get(naics, ("defense", ""))
    award = company.get("award_amount", 0)
    try:
        r = requests.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/companies",
            headers=_hs_headers(),
            json={"properties": {
                "name": company["name"],
                "city": city,
                "state": state,
                "country": "United States",
                "description": f"DoD contractor | NAICS {naics} ({naics_label}) | ${award/1_000_000:.1f}M in awards",
                "hs_lead_status": "NEW",
                "annualrevenue": str(int(award)) if award else "",
            }},
            timeout=10,
        )
        if not r.ok:
            print(f"  [HubSpot create error] {r.status_code}: {r.text[:150]}", file=sys.stderr)
            return None
        company_id = r.json()["id"]

        note_body = f"CMMC Outreach Email — Generated {time.strftime('%Y-%m-%d')}\n\n{email_text}"
        requests.post(
            f"{HUBSPOT_BASE}/crm/v3/objects/notes",
            headers=_hs_headers(),
            json={
                "properties": {
                    "hs_note_body": note_body,
                    "hs_timestamp": str(int(time.time() * 1000)),
                },
                "associations": [{"to": {"id": company_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 190}]}],
            },
            timeout=10,
        )
        return company_id
    except Exception as e:
        print(f"  [HubSpot error] {e}", file=sys.stderr)
        return None


# ── Gmail ─────────────────────────────────────────────────────────────────────

def gmail_create_draft(company_name: str, email_text: str) -> str | None:
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from gmail_draft import create_draft

        # Parse subject from email text (first line starting with Subject:)
        subject = f"CMMC Outreach — {company_name}"
        for line in email_text.split("\n"):
            stripped = line.strip()
            if stripped.lower().startswith("subject:"):
                subject = stripped[8:].strip()
                break
            if stripped.startswith("**Subject:**"):
                subject = stripped[12:].strip()
                break

        draft_id = create_draft(subject=subject, body=email_text)
        return draft_id
    except Exception as e:
        print(f"  [Gmail draft error] {e}", file=sys.stderr)
        return None


# ── USASpending ───────────────────────────────────────────────────────────────

def fetch_contractors(naics: str, count: int, city: str = "", state: str = "CA", nationwide: bool = False) -> list[dict]:
    location_filter = []
    if nationwide:
        location_filter = [{"country": "USA"}]
    elif city:
        location_filter = [{"country": "USA", "state": state, "city": city}]
    else:
        location_filter = [{"country": "USA", "state": state}]

    payload = {
        "filters": {
            "award_type_codes": ["A", "B", "C", "D"],
            "agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of Defense"}],
            "time_period": [{"start_date": "2022-01-01", "end_date": "2025-12-31"}],
            "naics_codes": {"require": [naics]},
        },
        "fields": ["Recipient Name", "Award Amount", "Place of Performance City Name", "Place of Performance State Code"],
        "page": 1,
        "limit": count * 4,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }
    if location_filter:
        payload["filters"]["recipient_locations"] = location_filter

    try:
        r = requests.post(USASPENDING_URL, json=payload, timeout=20,
                          headers={"Content-Type": "application/json"})
        r.raise_for_status()
        seen, deduped = set(), []
        for item in r.json().get("results", []):
            name = item.get("Recipient Name", "").strip().title()
            if name and name not in seen:
                seen.add(name)
                deduped.append({
                    "name": name,
                    "award_amount": item.get("Award Amount", 0),
                    "city": (item.get("Place of Performance City Name") or city or "").title(),
                    "state": (item.get("Place of Performance State Code") or state or ""),
                })
        return deduped
    except Exception as e:
        print(f"  [USASpending error] {e}", file=sys.stderr)
        return []


# ── Email generation ──────────────────────────────────────────────────────────

def generate_email(company: dict, naics: str) -> str:
    naics_label, naics_pain = NAICS_PROFILES.get(naics, ("defense", "work with DoD contracts"))
    award = company.get("award_amount", 0)
    award_str = f"~${award/1_000_000:.1f}M in recent DoD contract awards" if award > 0 else "active DoD contracts"
    city = company.get("city", "")
    state = company.get("state", "")
    location = f"{city}, {state}" if city else state

    notes = (
        f"NAICS {naics} ({naics_label}). Company has {award_str}. "
        f"Based in {location}. Pain point: {naics_pain}. "
        f"CMMC Level 2 required for continued contract eligibility."
    )
    try:
        headers = {"X-Webhook-Token": WEBHOOK_SECRET} if WEBHOOK_SECRET else {}
        r = requests.post(N8N_LEADS_URL,
                          json={"company": company["name"], "naics": naics, "notes": notes},
                          headers=headers,
                          timeout=180)
        r.raise_for_status()
        return r.text.strip()
    except Exception as e:
        return f"[Email generation failed: {e}]"


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run_pipeline(city: str, state: str, naics: str, count: int,
                 output_file: str | None, push_crm: bool, draft_gmail: bool, nationwide: bool):
    naics_label, _ = NAICS_PROFILES.get(naics, ("defense", ""))
    location_desc = "Nationwide" if nationwide else (f"{city}, {state}" if city else state)

    print(f"\n{'='*60}")
    print(f"CMMC LEAD GENERATION PIPELINE")
    print(f"  Location: {location_desc}")
    print(f"  Industry: NAICS {naics} — {naics_label}")
    print(f"  Target:   {count} outreach emails")
    print(f"  HubSpot:  {'push new leads' if push_crm else 'dedup only'}")
    print(f"  Gmail:    {'save to Drafts' if draft_gmail else 'off'}")
    print(f"{'='*60}\n")

    print("Querying USASpending.gov...")
    all_companies = fetch_contractors(naics, count, city=city, state=state, nationwide=nationwide)
    if not all_companies:
        print("No companies found. Try different --city, --state, --naics, or --nationwide.")
        return

    # Dedup against HubSpot
    print(f"Checking {min(len(all_companies), count*2)} candidates against HubSpot CRM...")
    new_companies, skipped = [], []
    for co in all_companies:
        if len(new_companies) >= count:
            break
        if hubspot_company_exists(co["name"]):
            skipped.append(co["name"])
        else:
            new_companies.append(co)

    if skipped:
        print(f"  Skipped {len(skipped)} already in CRM: {', '.join(skipped[:3])}{'...' if len(skipped)>3 else ''}")
    if not new_companies:
        print("All candidates already in HubSpot. Try --naics or a different location.")
        return

    companies = new_companies[:count]
    print(f"\nNew prospects ({len(companies)}):\n")
    for co in companies:
        print(f"  {co['name']:<45} ${co.get('award_amount',0)/1_000_000:.1f}M  {co.get('city','')}, {co.get('state','')}")
    print()

    output_lines = [
        f"# CMMC Outreach Batch — {location_desc} | NAICS {naics}",
        f"**{naics_label}** | Generated {time.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    crm_results, draft_results = [], []

    for i, co in enumerate(companies):
        print(f"[{i+1}/{len(companies)}] {co['name']}...", end="", flush=True)
        email = generate_email(co, naics)
        print(" email✓", end="", flush=True)

        if push_crm:
            hs_id = hubspot_create_company(co, naics, co.get("city", city), co.get("state", state), email)
            crm_results.append((co["name"], hs_id))
            print(f" crm✓({hs_id})" if hs_id else " crm✗", end="", flush=True)

        if draft_gmail:
            draft_id = gmail_create_draft(co["name"], email)
            draft_results.append((co["name"], draft_id))
            print(f" draft✓" if draft_id else " draft✗", end="", flush=True)

        print()

        amt = co.get("award_amount", 0)
        output_lines += [
            "---",
            f"## {i+1}. {co['name']}",
            f"**DoD awards:** ${amt/1_000_000:.1f}M | **NAICS:** {naics} | **Location:** {co.get('city','')}, {co.get('state','')}",
            "",
            email,
            "",
        ]
        if i < len(companies) - 1:
            time.sleep(1)

    output_lines.append(f"\n*{len(companies)} emails generated*")
    output_text = "\n".join(output_lines)

    print(f"\n{'='*60}")
    print(output_text)
    print(f"{'='*60}")

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"\nSaved: {output_file}")

    csv_base = output_file.rsplit(".", 1)[0] if output_file else str(OUTPUT_DIR / f"leads_{time.strftime('%Y%m%d_%H%M')}")
    csv_path = csv_base + ".csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as csvf:
        writer = csv.writer(csvf)
        writer.writerow(["Company", "DoD_Awards_M", "NAICS", "Industry", "City", "State", "Source", "HubSpot_ID", "Gmail_Draft_ID"])
        for co in companies:
            hs_id = next((hid for name, hid in crm_results if name == co["name"]), "") if push_crm else ""
            gid = next((gid for name, gid in draft_results if name == co["name"]), "") if draft_gmail else ""
            writer.writerow([
                co["name"], f"{co.get('award_amount',0)/1_000_000:.1f}",
                naics, naics_label, co.get("city", city), co.get("state", state),
                "USASpending.gov", hs_id or "", gid or "",
            ])
    print(f"CSV:   {csv_path}")

    if draft_gmail:
        drafted = sum(1 for _, gid in draft_results if gid)
        print(f"Gmail: {drafted}/{len(draft_results)} drafts saved → check Gmail Drafts folder")


def main():
    parser = argparse.ArgumentParser(
        description="Find real DoD contractors, generate CMMC outreach emails",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--city", default=DEFAULT_CITY, help="City to search (default: DEFAULT_CITY in .env; blank = whole state)")
    parser.add_argument("--state", default=DEFAULT_STATE, help="State abbreviation (default: DEFAULT_STATE in .env)")
    parser.add_argument("--nationwide", action="store_true", help="Search all US, not just one state")
    parser.add_argument("--naics", default="541512", choices=list(NAICS_PROFILES.keys()),
                        help="NAICS code (default: 541512 IT/cyber)")
    parser.add_argument("--count", type=int, default=5, help="Number of emails (default: 5)")
    parser.add_argument("--output", default="", help="Save output to .md file")
    parser.add_argument("--push-crm", action="store_true", help="Create companies in HubSpot")
    parser.add_argument("--draft-gmail", action="store_true", help="Save emails to Gmail Drafts")
    parser.add_argument("--list-naics", action="store_true", help="List NAICS codes and exit")
    args = parser.parse_args()

    if args.list_naics:
        print("\nAvailable NAICS codes:\n")
        for code, (label, pain) in NAICS_PROFILES.items():
            print(f"  {code}  {label}\n         {pain}\n")
        return

    run_pipeline(
        city=args.city if not args.nationwide else "",
        state=args.state,
        naics=args.naics,
        count=args.count,
        output_file=args.output or None,
        push_crm=args.push_crm,
        draft_gmail=args.draft_gmail,
        nationwide=args.nationwide,
    )


if __name__ == "__main__":
    main()
