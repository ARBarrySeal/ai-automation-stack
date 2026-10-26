"""
enrich_all.py — Batch enrichment for all HubSpot NEW companies.

Pulls company + decision-maker data from Apollo, updates HubSpot company
records, creates missing contacts, and writes a CSV report to OUTPUT_DIR.
Re-runnable: companies that already have a domain set in HubSpot are skipped.

Runtime: ~2.5s per company (1.2s sleep for the Apollo free-plan rate limit).
"""
import requests
import time
import csv
import os
from _env import require, VERIFY_SSL, OUTPUT_DIR

VERIFY = VERIFY_SSL

APOLLO_KEY = require("APOLLO_KEY")
HS_TOKEN   = require("HUBSPOT_TOKEN")

APOLLO_HEADERS = {"Content-Type": "application/json", "X-Api-Key": APOLLO_KEY}
HS_HEADERS     = {"Authorization": f"Bearer {HS_TOKEN}", "Content-Type": "application/json"}

CSV_PATH = OUTPUT_DIR / "enrichment_report.csv"
CSV_COLS = [
    "company", "hubspot_company_id", "domain", "employees", "linkedin_company",
    "contact_name", "contact_title", "contact_email", "contact_linkedin",
    "hubspot_contact_id", "status",
]


# ── HubSpot ──────────────────────────────────────────────────────────────────

def get_hubspot_companies():
    """Return all HubSpot companies with hs_lead_status=NEW."""
    companies = []
    after = None
    while True:
        body = {
            "filterGroups": [{"filters": [{"propertyName": "hs_lead_status", "operator": "EQ", "value": "NEW"}]}],
            "properties": ["name", "domain"],
            "limit": 100,
        }
        if after:
            body["after"] = after
        r = requests.post(
            "https://api.hubapi.com/crm/v3/objects/companies/search",
            headers=HS_HEADERS, json=body, timeout=15, verify=VERIFY,
        )
        if not r.ok:
            print(f"[hs] search error {r.status_code}: {r.text[:160]}")
            break
        data = r.json()
        for co in data.get("results", []):
            companies.append({
                "id":     co["id"],
                "name":   co["properties"].get("name", ""),
                "domain": co["properties"].get("domain") or "",
            })
        nxt = data.get("paging", {}).get("next")
        after = nxt.get("after") if nxt else None
        if not after:
            break
    return companies


def update_hubspot_company(company_id, props):
    props = {k: v for k, v in props.items() if v}
    if not props:
        return False
    try:
        r = requests.patch(
            f"https://api.hubapi.com/crm/v3/objects/companies/{company_id}",
            headers=HS_HEADERS, json={"properties": props}, timeout=12, verify=VERIFY,
        )
        return r.ok
    except Exception as e:
        print(f"  [hs-company] {e}")
        return False


def create_hubspot_contact(company_id, person):
    """Create contact + associate to company. Handles 409 (already exists)."""
    props = {k: v for k, v in {
        "firstname":    person.get("first_name"),
        "lastname":     person.get("last_name"),
        "email":        person.get("email"),
        "jobtitle":     person.get("title"),
        "linkedin_bio": person.get("linkedin_url"),
        "hs_lead_status": "NEW",
    }.items() if v}

    body = {
        "properties": props,
        "associations": [{
            "to": {"id": company_id},
            "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 280}],
        }],
    }
    try:
        r = requests.post(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers=HS_HEADERS, json=body, timeout=12, verify=VERIFY,
        )
        if r.status_code in (200, 201):
            return r.json()["id"]
        if r.status_code == 409:
            email = props.get("email")
            if email:
                return _associate_existing_contact(company_id, email)
        print(f"  [hs-contact] HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"  [hs-contact] {e}")
    return None


def _associate_existing_contact(company_id, email):
    """Find contact by email and associate to company. Returns contact_id."""
    try:
        r = requests.post(
            "https://api.hubapi.com/crm/v3/objects/contacts/search",
            headers=HS_HEADERS,
            json={
                "filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}],
                "properties": ["email"], "limit": 1,
            },
            timeout=12, verify=VERIFY,
        )
        if r.ok and r.json().get("results"):
            contact_id = r.json()["results"][0]["id"]
            requests.put(
                f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"
                f"/associations/companies/{company_id}/contact_to_company",
                headers=HS_HEADERS, timeout=10, verify=VERIFY,
            )
            return contact_id
    except Exception as e:
        print(f"  [hs-assoc] {e}")
    return None


def add_hubspot_note(company_id, text):
    try:
        r = requests.post(
            "https://api.hubapi.com/crm/v3/objects/notes",
            headers=HS_HEADERS,
            json={
                "properties": {
                    "hs_note_body": text,
                    "hs_timestamp": str(int(time.time() * 1000)),
                },
                "associations": [{
                    "to": {"id": company_id},
                    "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 190}],
                }],
            },
            timeout=12, verify=VERIFY,
        )
        return r.ok
    except Exception as e:
        print(f"  [hs-note] {e}")
        return False


# ── Apollo ───────────────────────────────────────────────────────────────────

def apollo_org_enrich(name):
    """Return org data dict or None."""
    try:
        r = requests.post(
            "https://api.apollo.io/v1/organizations/enrich",
            headers=APOLLO_HEADERS,
            json={"name": name, "organization_name": name},
            timeout=12, verify=VERIFY,
        )
        if not r.ok:
            return None
        org = (r.json().get("organization") or {})
        if not org:
            return None
        return {
            "domain":      org.get("primary_domain") or "",
            "employees":   str(org.get("estimated_num_employees") or ""),
            "linkedin":    org.get("linkedin_url") or "",
            "industry":    org.get("industry") or "",
            "description": (org.get("short_description") or "")[:300],
        }
    except Exception as e:
        print(f"  [apollo-org] {e}")
        return None


def apollo_people_match(domain, company_name):
    """Return person data dict or None."""
    try:
        r = requests.post(
            "https://api.apollo.io/api/v1/people/match"
            "?run_waterfall_email=false&run_waterfall_phone=false"
            "&reveal_personal_emails=false&reveal_phone_number=false",
            headers=APOLLO_HEADERS,
            json={"domain": domain, "organization_name": company_name},
            timeout=12, verify=VERIFY,
        )
        if not r.ok:
            return None
        person = r.json().get("person") or {}
        if not person or not person.get("name"):
            return None
        return {
            "first_name":   person.get("first_name") or "",
            "last_name":    person.get("last_name") or "",
            "name":         person.get("name") or "",
            "title":        person.get("title") or "",
            "email":        person.get("email") or "",
            "linkedin_url": person.get("linkedin_url") or "",
        }
    except Exception as e:
        print(f"  [apollo-people] {e}")
        return None


# ── CSV ───────────────────────────────────────────────────────────────────────

def append_csv_row(row):
    write_header = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        if write_header:
            w.writeheader()
        w.writerow({col: row.get(col, "") for col in CSV_COLS})


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching HubSpot NEW companies...")
    companies = get_hubspot_companies()
    to_enrich = [c for c in companies if not c["domain"]]
    skipped   = len(companies) - len(to_enrich)
    print(f"  Total NEW: {len(companies)} | Already enriched (skipped): {skipped} | To process: {len(to_enrich)}")

    if not to_enrich:
        print("Nothing to do — all companies already have a domain set.")
        return

    ok_count = no_org = no_contact = err = 0

    for i, co in enumerate(to_enrich, 1):
        name  = co["name"]
        hs_id = co["id"]
        print(f"\n[{i:03d}/{len(to_enrich)}] {name}")

        row = {"company": name, "hubspot_company_id": hs_id, "status": "error"}

        # Step 1 — Apollo org enrich
        org = apollo_org_enrich(name)
        if not org or not org["domain"]:
            print("  no org match")
            row["status"] = "no_org_match"
            append_csv_row(row)
            no_org += 1
            time.sleep(1.2)
            continue

        print(f"  domain: {org['domain']} | employees: {org['employees']} | industry: {org['industry']}")
        row.update({
            "domain":           org["domain"],
            "employees":        org["employees"],
            "linkedin_company": org["linkedin"],
        })

        # Step 2 — Update HubSpot company
        update_hubspot_company(hs_id, {
            "domain":              org["domain"],
            "website":             f"https://{org['domain']}",
            "numberofemployees":   org["employees"],
            "linkedin_company_page": org["linkedin"],
            "industry":            "DEFENSE_AND_SPACE",
            "description":         org["description"],
        })

        # Step 3 — Apollo people/match
        person = apollo_people_match(org["domain"], name)
        contact_id = None

        if person:
            print(f"  contact: {person['name']} | {person['title']} | {person['email'] or '(no email)'}")
            row.update({
                "contact_name":     person["name"],
                "contact_title":    person["title"],
                "contact_email":    person["email"],
                "contact_linkedin": person["linkedin_url"],
            })

            # Step 4 — Create HubSpot contact
            contact_id = create_hubspot_contact(hs_id, person)
            row["hubspot_contact_id"] = contact_id or ""

            note_lines = [
                f"ENRICHMENT — {time.strftime('%Y-%m-%d')} [Apollo]",
                f"Domain: {org['domain']}",
                f"Employees: ~{org['employees']}" if org["employees"] else None,
                f"LinkedIn page: {org['linkedin']}" if org["linkedin"] else None,
                f"Decision-maker: {person['name']} | {person['title']}",
                f"Email: {person['email']}" if person["email"] else None,
                f"Contact LinkedIn: {person['linkedin_url']}" if person["linkedin_url"] else None,
            ]
            add_hubspot_note(hs_id, "\n".join(x for x in note_lines if x))
            row["status"] = "ok"
            ok_count += 1
        else:
            print("  no contact found")
            note_lines = [
                f"ENRICHMENT — {time.strftime('%Y-%m-%d')} [Apollo]",
                f"Domain: {org['domain']}",
                f"Employees: ~{org['employees']}" if org["employees"] else None,
                f"LinkedIn page: {org['linkedin']}" if org["linkedin"] else None,
                "No decision-maker contact found via Apollo people/match.",
            ]
            add_hubspot_note(hs_id, "\n".join(x for x in note_lines if x))
            row["status"] = "no_contact_found"
            no_contact += 1

        append_csv_row(row)
        time.sleep(1.2)

    print(f"\n{'='*60}")
    print(f"Processed: {len(to_enrich)} companies")
    print(f"  ok (company + contact): {ok_count}")
    print(f"  no_contact_found:       {no_contact}")
    print(f"  no_org_match:           {no_org}")
    print(f"  errors:                 {err}")
    print(f"Report -> {CSV_PATH}")


if __name__ == "__main__":
    main()
