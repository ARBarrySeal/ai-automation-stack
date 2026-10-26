"""
Apollo + Tavily enrichment for a list of HubSpot companies.
Enriches company + finds decision-maker contacts, then updates HubSpot.

Input: a CSV with columns name,hubspot_id (default examples/companies.example.csv,
override with --input). Tip: enrich_all.py pulls the list from HubSpot instead.
"""
import requests, json, time, csv, os
from _env import env, require, VERIFY_SSL, ROOT, OUTPUT_DIR

APOLLO_KEY = env("APOLLO_KEY_FREE") or require("APOLLO_KEY")  # free plan - search blocked
TAVILY_KEY = require("TAVILY_API_KEY")
APOLLO_HEADERS = {
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
    "X-Api-Key": APOLLO_KEY,
}

HUBSPOT_KEY = require("HUBSPOT_TOKEN")
HUBSPOT_HEADERS = {
    "Authorization": f"Bearer {HUBSPOT_KEY}",
    "Content-Type": "application/json",
}

def load_companies(path):
    """Read name,hubspot_id rows from a CSV."""
    with open(path, newline="", encoding="utf-8") as f:
        return [
            {"name": row["name"].strip(), "hubspot_id": row.get("hubspot_id", "").strip()}
            for row in csv.DictReader(f)
            if row.get("name", "").strip()
        ]


COMPANIES = []

TITLE_KEYWORDS = [
    "Chief Information Security Officer", "CISO",
    "VP Information Technology", "VP IT",
    "Director of IT", "Director Information Technology",
    "IT Director", "Information Security Manager",
    "IT Manager", "Compliance Manager",
    "Chief Technology Officer", "CTO",
    "Chief Operating Officer", "COO",
    "President", "Owner",
]


def tavily_search(query, max_results=3):
    """Call Tavily search API. Returns list of result dicts."""
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_KEY,
                "query": query,
                "max_results": max_results,
                "include_answer": True,
                "search_depth": "basic",
            },
            timeout=20,
            verify=VERIFY_SSL,
        )
        if r.status_code == 200:
            return r.json()
        print(f"  [tavily] HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"  [tavily] error: {e}")
    return {}


def get_company_domain(company_name):
    """Use Tavily to find the company's official website domain."""
    data = tavily_search(f"{company_name} official website defense contractor")
    results = data.get("results", [])
    # Pick the first non-social, non-government result
    skip = ("linkedin.com", "facebook.com", "twitter.com", "sam.gov",
            "usaspending.gov", "beta.sam.gov", "govtribe.com", "fedmine.us",
            "bloomberg.com", "crunchbase.com", "zoominfo.com")
    for res in results:
        url = res.get("url", "")
        domain = url.replace("https://", "").replace("http://", "").split("/")[0].lstrip("www.")
        if not any(s in domain for s in skip) and domain:
            return domain
    return ""


def find_contact_tavily(company_name, domain=""):
    """Use Tavily to find a decision-maker contact at the company."""
    base = f'site:{domain}' if domain else company_name
    queries = [
        f"{company_name} CISO \"Chief Information Security Officer\" OR \"IT Director\" OR \"VP IT\" contact email",
        f"{company_name} cybersecurity compliance leadership team",
    ]
    for query in queries:
        data = tavily_search(query, max_results=5)
        answer = data.get("answer", "")
        results = data.get("results", [])
        # Try to extract a name from the answer
        if answer and len(answer) > 10:
            return {"source": "tavily_answer", "snippet": answer[:400]}
        for res in results:
            content = res.get("content", "")
            if any(t.lower() in content.lower() for t in ["CISO", "director", "VP", "president", "manager"]):
                return {"source": res.get("url", ""), "snippet": content[:400]}
    return None


def update_hubspot_company(hs_id, props):
    if not HUBSPOT_KEY or not props:
        return False
    try:
        r = requests.patch(
            f"https://api.hubapi.com/crm/v3/objects/companies/{hs_id}",
            headers=HUBSPOT_HEADERS,
            json={"properties": props},
            timeout=15,
            verify=VERIFY_SSL,
        )
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"  [hs] company update error: {e}")
        return False


def create_hubspot_contact(hs_company_id, contact):
    if not HUBSPOT_KEY:
        return None
    phones = contact.get("phone_numbers") or []
    props = {
        "firstname": contact.get("first_name", ""),
        "lastname": contact.get("last_name", ""),
        "email": contact.get("email", ""),
        "jobtitle": contact.get("title", ""),
        "phone": phones[0].get("raw_number", "") if phones else "",
        "linkedin_bio": contact.get("linkedin_url", ""),
        "hs_lead_status": "NEW",
    }
    props = {k: v for k, v in props.items() if v}
    try:
        r = requests.post(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers=HUBSPOT_HEADERS,
            json={"properties": props},
            timeout=15,
            verify=VERIFY_SSL,
        )
        if r.status_code in (200, 201):
            contact_id = r.json()["id"]
            requests.put(
                f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"
                f"/associations/companies/{hs_company_id}/contact_to_company",
                headers=HUBSPOT_HEADERS,
                timeout=10,
                verify=VERIFY_SSL,
            )
            return contact_id
        print(f"  [hs] contact create HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        print(f"  [hs] contact create error: {e}")
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default=str(ROOT / "examples" / "companies.example.csv"),
                        help="CSV with columns name,hubspot_id")
    args = parser.parse_args()
    COMPANIES[:] = load_companies(args.input)
    if not COMPANIES:
        raise SystemExit(f"No companies in {args.input}")
    results = []
    print(f"\nEnriching {len(COMPANIES)} companies via Apollo\n{'='*60}")

    for i, co in enumerate(COMPANIES, 1):
        name = co["name"]
        hs_id = co["hubspot_id"]
        print(f"\n[{i:02d}/{len(COMPANIES)}] {name}")

        domain = get_company_domain(name)
        time.sleep(1)

        linkedin_url = employee_count = ""
        print(f"  domain: {domain or '(not found)'}")

        if domain and hs_id:
            hs_props = {
                "domain": domain,
                "website": f"https://{domain}",
            }
            update_hubspot_company(hs_id, hs_props)

        contact_raw = find_contact_tavily(name, domain)
        time.sleep(1)

        contact_id = contact_email = contact_name = contact_title = contact_snippet = ""

        if contact_raw:
            contact_snippet = contact_raw.get("snippet", "")
            print(f"  contact snippet: {contact_snippet[:120]}")
        if contact_raw and hs_id:
            # Add note to HubSpot company record with the contact intelligence
            note_props = {
                "hs_note_body": f"Apollo/Tavily contact intel for {name}:\n\n{contact_snippet}\n\nSource: {contact_raw.get('source','')}",
                "hs_timestamp": str(int(time.time() * 1000)),
            }
            try:
                nr = requests.post(
                    "https://api.hubapi.com/crm/v3/objects/notes",
                    headers=HUBSPOT_HEADERS,
                    json={"properties": note_props},
                    verify=VERIFY_SSL, timeout=15,
                )
                if nr.status_code in (200, 201):
                    note_id = nr.json()["id"]
                    requests.put(
                        f"https://api.hubapi.com/crm/v3/objects/notes/{note_id}"
                        f"/associations/companies/{hs_id}/note_to_company",
                        headers=HUBSPOT_HEADERS, verify=VERIFY_SSL, timeout=10,
                    )
            except Exception as e:
                print(f"  [hs-note] error: {e}")
        elif not contact_raw:
            print("  contact: no intel found")

        results.append({
            "company": name,
            "hubspot_company_id": hs_id,
            "domain": domain,
            "contact_intel_snippet": contact_snippet[:200] if contact_snippet else "",
            "contact_source": contact_raw.get("source", "") if contact_raw else "",
        })

    out_path = OUTPUT_DIR / "apollo_enriched.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    print(f"\n{'='*60}")
    print(f"Results -> {out_path}")
    print(f"Domains found       : {sum(1 for r in results if r['domain'])}/{len(results)}")
    print(f"Contact intel found : {sum(1 for r in results if r['contact_intel_snippet'])}/{len(results)}")


if __name__ == "__main__":
    main()
