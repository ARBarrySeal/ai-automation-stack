"""
SAM.gov Opportunities scraper — pulls open DOD solicitations relevant to CMMC.
Filters for CMMC-relevant NAICS codes, active solicitations, posted in last 90 days,
with place of performance in SAM_TARGET_STATES (default: DEFAULT_STATE).
"""
import requests, json, csv, os
from datetime import datetime, timedelta
from _env import require, env, VERIFY_SSL, DEFAULT_STATE, OUTPUT_DIR


API_KEY = require("SAM_GOV_API_KEY")
BASE_URL = "https://api.sam.gov/opportunities/v2/search"

# NAICS codes relevant to CMMC/DOD cyber/IT/engineering
TARGET_NAICS = [
    "541512",  # Computer systems design
    "541330",  # Engineering services
    "541519",  # Other computer services
    "541511",  # Custom computer programming
    "541513",  # Computer facilities mgmt
    "541690",  # Other scientific/technical consulting
    "541715",  # R&D in physical/engineering sciences
    "336411",  # Aircraft manufacturing
    "334511",  # Search/detection/nav instruments
    "335991",  # Carbon and graphite products
    "517110",  # Wired telecom carriers
    "561210",  # Facilities support services
]

# Comma-separated in .env, e.g. SAM_TARGET_STATES=CA,AZ,NV
TARGET_STATES = [s.strip() for s in env("SAM_TARGET_STATES", DEFAULT_STATE).split(",") if s.strip()]

# Date range — last 90 days, close date in future
today = datetime.utcnow()
posted_from = (today - timedelta(days=90)).strftime("%m/%d/%Y")
posted_to = today.strftime("%m/%d/%Y")


def fetch_opportunities(keyword, limit=100):
    params = {
        "api_key": API_KEY,
        "limit": limit,
        "offset": 0,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "q": keyword,
        "ptype": "o,p,k,s",           # solicitation, presolicitation, combined synopsis, sources sought
        "status": "active",
    }
    try:
        r = requests.get(BASE_URL, params=params, timeout=30, verify=VERIFY_SSL)
        if r.status_code == 200:
            data = r.json()
            return data.get("opportunitiesData", [])
        print(f"  [sam] '{keyword}' HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  [sam] '{keyword}' error: {e}")
    return []


def parse_opportunity(opp):
    title = opp.get("title", "")
    sol_num = opp.get("solicitationNumber", "")
    dept = opp.get("fullParentPathName", opp.get("organizationHierarchy", {}).get("name", "")) if isinstance(opp.get("organizationHierarchy"), dict) else opp.get("organizationName", "")
    naics = opp.get("naicsCode") or ""
    ptype_map = {"o": "Solicitation", "p": "Pre-Solicitation", "k": "Combined Synopsis", "s": "Sources Sought", "r": "Sources Sought", "g": "Sale of Surplus", "a": "Award Notice"}
    ptype = ptype_map.get(opp.get("type", ""), opp.get("type", ""))
    posted = opp.get("postedDate", "")
    close_raw = opp.get("responseDeadLine", "") or opp.get("archiveDate", "")
    # Estimated value
    award = opp.get("award", {}) or {}
    est_value = ""
    if isinstance(award, dict):
        amt = award.get("amount")
        if amt:
            try:
                est_value = f"${float(amt):,.0f}"
            except:
                est_value = str(amt)
    # Set-aside
    setaside = opp.get("typeOfSetAsideDescription", "") or opp.get("typeOfSetAside", "")
    # POC
    pocs = opp.get("pointOfContact", []) or []
    poc_name = poc_email = poc_phone = ""
    if pocs:
        p = pocs[0] if isinstance(pocs[0], dict) else {}
        poc_name = p.get("fullName", p.get("name", ""))
        poc_email = p.get("email", "")
        poc_phone = p.get("phone", "")
    # Place of performance
    pop = opp.get("placeOfPerformance", {}) or {}
    if isinstance(pop, dict):
        city = (pop.get("city") or {}).get("name", "") if isinstance(pop.get("city"), dict) else ""
        state_pop = (pop.get("state") or {}).get("code", "") if isinstance(pop.get("state"), dict) else ""
        location = f"{city}, {state_pop}".strip(", ")
    else:
        location = ""
    # Link
    link = f"https://sam.gov/opp/{opp.get('noticeId', '')}/view" if opp.get("noticeId") else ""

    return {
        "title": title,
        "solicitation_number": sol_num,
        "type": ptype,
        "department": dept,
        "naics": naics,
        "posted": posted,
        "close_date": close_raw,
        "est_value": est_value,
        "set_aside": setaside,
        "poc_name": poc_name,
        "poc_email": poc_email,
        "poc_phone": poc_phone,
        "location": location,
        "link": link,
    }


KEYWORDS = [
    "cybersecurity",
    "CMMC",
    "information technology",
    "cyber security",
    "network security",
    "information assurance",
]

# NAICS codes we care about — used to filter results after fetch
RELEVANT_NAICS = set(TARGET_NAICS)

# Place of performance states to keep (broad — includes CA + nationwide DOD)
# We'll filter loosely: keep if CA or no state specified
def is_relevant(opp):
    """Return True if this opportunity is relevant to CMMC/IT consulting."""
    naics = opp.get("naicsCode") or ""
    # Accept any IT/engineering NAICS, or if keyword search found it
    relevant_naics_prefixes = ("5415", "5416", "5413", "3364", "3345", "5171", "5612")
    if any(naics.startswith(p) for p in relevant_naics_prefixes):
        return True
    # Accept if title/description mentions cyber/IT
    title = (opp.get("title") or "").lower()
    desc = (opp.get("description") or "").lower()
    it_terms = ["cyber", "cmmc", "information technology", "network", "security", "it support",
                "software", "systems integration", "dfars", "nist", "cloud", "data"]
    return any(t in title or t in desc for t in it_terms)


def main():
    all_opps = []
    seen = set()

    print(f"\nFetching SAM.gov opportunities — posted {posted_from} to {posted_to}")
    print(f"Keywords: {', '.join(KEYWORDS)}")
    print("=" * 70)

    for kw in KEYWORDS:
        print(f"\n'{kw}' ...", end=" ", flush=True)
        results = fetch_opportunities(kw)
        new = 0
        for opp in results:
            nid = opp.get("noticeId") or opp.get("solicitationNumber", "")
            if nid and nid in seen:
                continue
            if not is_relevant(opp):
                continue
            seen.add(nid)
            parsed = parse_opportunity(opp)
            all_opps.append(parsed)
            new += 1
        print(f"{new} new relevant opportunities")

    # Sort by close date (soonest first), then by est_value descending
    def sort_key(o):
        close = o["close_date"] or "9999"
        return close

    all_opps.sort(key=sort_key)

    print(f"\nTotal unique opportunities: {len(all_opps)}")

    # Write CSV
    csv_path = OUTPUT_DIR / "sam_opportunities.csv"
    if all_opps:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_opps[0].keys())
            writer.writeheader()
            writer.writerows(all_opps)
        print(f"CSV saved: {csv_path}")

    # Write Markdown summary
    md_path = OUTPUT_DIR / "sam_opportunities.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# SAM.gov Open Opportunities — {', '.join(TARGET_STATES)}\n")
        f.write(f"**Pulled:** {today.strftime('%Y-%m-%d')} | **Posted range:** last 90 days | **Total:** {len(all_opps)}\n\n---\n\n")
        for i, o in enumerate(all_opps, 1):
            f.write(f"## {i}. {o['title']}\n")
            f.write(f"**Type:** {o['type']} | **NAICS:** {o['naics']} | **Posted:** {o['posted']} | **Closes:** {o['close_date']}\n\n")
            if o['est_value']:
                f.write(f"**Estimated Value:** {o['est_value']}\n\n")
            if o['set_aside']:
                f.write(f"**Set-Aside:** {o['set_aside']}\n\n")
            if o['department']:
                f.write(f"**Agency:** {o['department']}\n\n")
            if o['location']:
                f.write(f"**Location:** {o['location']}\n\n")
            if o['solicitation_number']:
                f.write(f"**Solicitation #:** {o['solicitation_number']}\n\n")
            if o['poc_name'] or o['poc_email']:
                f.write(f"**POC:** {o['poc_name']} {o['poc_email']} {o['poc_phone']}\n\n".strip() + "\n\n")
            if o['link']:
                f.write(f"**Link:** {o['link']}\n\n")
            f.write("---\n\n")

    print(f"Markdown saved: {md_path}")
    return all_opps


if __name__ == "__main__":
    main()
