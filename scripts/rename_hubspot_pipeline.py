"""
Renames the default HubSpot Sales Pipeline to CMMC Consulting Pipeline
and updates stage names to match the CMMC consulting sales process.
Also runs through all 312 contacts to tag untagged ones.
"""
import requests, json
from _env import require

T = require("HUBSPOT_TOKEN")
H = {"Authorization": f"Bearer {T}", "Content-Type": "application/json"}

PIPELINE_ID = "default"

# Map existing stage IDs → new CMMC names
STAGE_RENAMES = {
    "appointmentscheduled":   "Meeting Scheduled",
    "qualifiedtobuy":         "Gap Assessment",
    "presentationscheduled":  "Proposal Sent",
    "decisionmakerboughtin":  "Decision Pending",
    "contractsent":           "Contract Signed",
    "closedwon":              "Closed Won",
    "closedlost":             "Lost / No Response",
}

def rename_pipeline():
    r = requests.patch(
        f"https://api.hubapi.com/crm/v3/pipelines/deals/{PIPELINE_ID}",
        headers=H,
        json={"label": "CMMC Consulting Pipeline"},
        timeout=10
    )
    if r.ok:
        print(f"Pipeline renamed to: CMMC Consulting Pipeline")
    else:
        print(f"Pipeline rename error: {r.status_code} {r.text[:150]}")

def rename_stages():
    # Get current stages
    r = requests.get(f"https://api.hubapi.com/crm/v3/pipelines/deals/{PIPELINE_ID}/stages", headers=H, timeout=10)
    if not r.ok:
        print(f"Stage fetch error: {r.status_code}")
        return
    stages = r.json().get("results", [])
    print(f"\nRenaming {len(stages)} stages:")
    for stage in stages:
        sid = stage["id"]
        old = stage["label"]
        new = STAGE_RENAMES.get(sid, old)
        if new == old:
            print(f"  (unchanged) {old}")
            continue
        pr = requests.patch(
            f"https://api.hubapi.com/crm/v3/pipelines/deals/{PIPELINE_ID}/stages/{sid}",
            headers=H,
            json={"label": new},
            timeout=10
        )
        if pr.ok:
            print(f"  {old} -> {new}")
        else:
            print(f"  ERROR renaming {old}: {pr.status_code} {pr.text[:100]}")

def tag_all_contacts():
    """Tag all untagged contacts in batches of 50."""
    total_tagged = 0
    after = None
    while True:
        params = {
            "filterGroups": [{"filters": [
                {"propertyName": "hs_lead_status", "operator": "NOT_HAS_PROPERTY"}
            ]}],
            "properties": ["firstname", "lastname"],
            "limit": 100
        }
        if after:
            params["after"] = after
        r = requests.post(
            "https://api.hubapi.com/crm/v3/objects/contacts/search",
            headers=H, json=params, timeout=15
        )
        if not r.ok:
            print(f"Search error: {r.status_code}")
            break
        data = r.json()
        contacts = data.get("results", [])
        if not contacts:
            break
        for c in contacts:
            requests.patch(
                f"https://api.hubapi.com/crm/v3/objects/contacts/{c['id']}",
                headers=H,
                json={"properties": {"hs_lead_status": "NEW"}},
                timeout=5
            )
            total_tagged += 1
        paging = data.get("paging", {})
        after = paging.get("next", {}).get("after")
        if not after:
            break
    print(f"\nTagged {total_tagged} additional contacts as NEW")

def show_final_state():
    print("\n--- Final HubSpot State ---")
    for label, url in [
        ("Contacts", "https://api.hubapi.com/crm/v3/objects/contacts/search"),
        ("Companies", "https://api.hubapi.com/crm/v3/objects/companies/search"),
        ("Deals", "https://api.hubapi.com/crm/v3/objects/deals/search"),
    ]:
        r = requests.post(url, headers=H, json={"filterGroups": [], "limit": 1}, timeout=10)
        total = r.json().get("total", "?") if r.ok else f"err {r.status_code}"
        print(f"  {label}: {total}")

    r = requests.get(f"https://api.hubapi.com/crm/v3/pipelines/deals/{PIPELINE_ID}", headers=H, timeout=10)
    if r.ok:
        p = r.json()
        print(f"\n  Pipeline: {p['label']}")
        for s in sorted(p.get("stages", []), key=lambda x: x.get("displayOrder", 0)):
            print(f"    [{s['displayOrder']}] {s['label']}")

if __name__ == "__main__":
    print("=== CMMC Pipeline Rename ===\n")
    rename_pipeline()
    rename_stages()
    tag_all_contacts()
    show_final_state()
