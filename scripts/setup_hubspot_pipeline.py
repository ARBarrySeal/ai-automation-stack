"""
Sets up a CMMC consulting deal pipeline in HubSpot with proper stages.
Also tags existing contacts as CMMC prospects.
"""
import requests, json
from _env import require

HS_TOKEN = require("HUBSPOT_TOKEN")
HEADERS = {
    "Authorization": f"Bearer {HS_TOKEN}",
    "Content-Type": "application/json"
}

PIPELINE_NAME = "CMMC Consulting Pipeline"
STAGES = [
    {"label": "New Lead",           "displayOrder": 0, "metadata": {"probability": "0.05"}},
    {"label": "Outreach Sent",      "displayOrder": 1, "metadata": {"probability": "0.10"}},
    {"label": "Meeting Scheduled",  "displayOrder": 2, "metadata": {"probability": "0.25"}},
    {"label": "Gap Assessment",     "displayOrder": 3, "metadata": {"probability": "0.40"}},
    {"label": "Proposal Sent",      "displayOrder": 4, "metadata": {"probability": "0.60"}},
    {"label": "Contract Signed",    "displayOrder": 5, "metadata": {"probability": "1.0", "isClosed": "true"}},
    {"label": "Lost / No Response", "displayOrder": 6, "metadata": {"probability": "0.0", "isClosed": "true"}},
]


def get_pipelines():
    r = requests.get("https://api.hubapi.com/crm/v3/pipelines/deals", headers=HEADERS, timeout=10)
    return r.json().get("results", []) if r.ok else []


def create_pipeline():
    existing = get_pipelines()
    for p in existing:
        if p.get("label") == PIPELINE_NAME:
            print(f"Pipeline already exists: {p['label']} (id={p['id']})")
            return p["id"]

    payload = {"label": PIPELINE_NAME, "displayOrder": 1, "stages": STAGES}
    r = requests.post("https://api.hubapi.com/crm/v3/pipelines/deals", headers=HEADERS, json=payload, timeout=10)
    if r.ok:
        pid = r.json()["id"]
        print(f"Created pipeline: {PIPELINE_NAME} (id={pid})")
        for s in r.json().get("stages", []):
            print(f"  Stage: {s['label']} (id={s['id']})")
        return pid
    else:
        print(f"Pipeline create error: {r.status_code} {r.text[:200]}")
        # List what exists
        print("Existing pipelines:")
        for p in existing:
            print(f"  {p.get('label')} (id={p['id']})")
            for s in p.get("stages", []):
                print(f"    Stage: {s.get('label')} (id={s.get('id')})")
        return None


def tag_contacts_as_cmmc():
    """Add CMMC prospect tag to first 50 contacts without a lead status."""
    r = requests.post(
        "https://api.hubapi.com/crm/v3/objects/contacts/search",
        headers=HEADERS,
        json={
            "filterGroups": [{"filters": [
                {"propertyName": "hs_lead_status", "operator": "NOT_HAS_PROPERTY"}
            ]}],
            "properties": ["firstname", "lastname", "email", "hs_lead_status"],
            "limit": 50
        },
        timeout=10
    )
    if not r.ok:
        print(f"Contact search error: {r.status_code} {r.text[:100]}")
        return

    contacts = r.json().get("results", [])
    print(f"\nTagging {len(contacts)} untagged contacts as NEW leads...")
    updated = 0
    for c in contacts:
        patch = requests.patch(
            f"https://api.hubapi.com/crm/v3/objects/contacts/{c['id']}",
            headers=HEADERS,
            json={"properties": {"hs_lead_status": "NEW"}},
            timeout=5
        )
        if patch.ok:
            updated += 1
    print(f"  Tagged {updated}/{len(contacts)} contacts with hs_lead_status=NEW")


def show_summary():
    print("\n--- HubSpot Summary ---")
    # Contacts
    r = requests.post(
        "https://api.hubapi.com/crm/v3/objects/contacts/search",
        headers=HEADERS,
        json={"filterGroups": [], "limit": 1},
        timeout=10
    )
    if r.ok:
        print(f"Total contacts: {r.json().get('total', '?')}")

    # Companies
    r = requests.post(
        "https://api.hubapi.com/crm/v3/objects/companies/search",
        headers=HEADERS,
        json={"filterGroups": [], "limit": 1},
        timeout=10
    )
    if r.ok:
        print(f"Total companies: {r.json().get('total', '?')}")

    # Deals
    r = requests.post(
        "https://api.hubapi.com/crm/v3/objects/deals/search",
        headers=HEADERS,
        json={"filterGroups": [], "limit": 1},
        timeout=10
    )
    if r.ok:
        print(f"Total deals: {r.json().get('total', '?')}")

    # Pipelines
    print("\nDeal pipelines:")
    for p in get_pipelines():
        print(f"  {p.get('label')} (id={p['id']}, stages={len(p.get('stages', []))})")


if __name__ == "__main__":
    print("=== HubSpot Pipeline Setup ===\n")
    create_pipeline()
    tag_contacts_as_cmmc()
    show_summary()
