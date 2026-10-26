"""
SAM.gov Opportunities scraper — interpretation/translation/ASL contracts.
Targets NAICS 541930 (translation & interpretation), plus ADA-driven federal
solicitations for ASL, DeafBlind, tactile, ProTactile, and CART services.

Pulls active solicitations in the last 120 days, place of performance CA + nearby
states, writes CSV + Markdown summary to OUTPUT_DIR/interpretation_opportunities/.
Shows how to point the same SAM.gov scraper at a completely different industry.
"""
import os
import csv
from datetime import datetime, timedelta

import requests
from _env import require, VERIFY_SSL, OUTPUT_DIR


API_KEY = require("SAM_GOV_API_KEY")
BASE_URL = "https://api.sam.gov/opportunities/v2/search"

# Primary NAICS for translation / interpretation services
TARGET_NAICS = {
    "541930": "Translation and Interpretation Services",
    "611710": "Educational Support Services",   # school-district / DSPS ASL contracts
    "624190": "Other Individual and Family Services",  # VR / DOR / state deaf services
    "611691": "Exam Preparation and Tutoring",  # CART / academic interpreting in some agencies
    "621399": "Offices of All Other Misc Health Practitioners",  # VA / hospital ASL
}

# Edit to the states you serve
TARGET_STATES = ["CA", "AZ", "NV", "OR", "HI"]

# ASL/DeafBlind-specific keyword sweeps (used as fallback in case relevant
# opportunities are coded under a non-541930 NAICS — e.g. 561499 / 624190 /
# 611710 / 621399. We dedupe across both passes by noticeId.)
ASL_KEYWORDS = [
    "American Sign Language",
    "ASL interpreter",
    "deaf interpreter",
    "DeafBlind",
    "tactile interpret",
    "ProTactile",
    "CART captioning",
    "communication access realtime",
    "video remote interpreting",
]

# Look back 180 days — federal interpreter solicitations are infrequent and
# response windows are often short, so a wider window surfaces recompetes
# and recurring annual buys we can pre-stage cold outreach for.
today = datetime.utcnow()
posted_from = (today - timedelta(days=180)).strftime("%m/%d/%Y")
posted_to = today.strftime("%m/%d/%Y")


def fetch_by_naics(ncode: str, limit: int = 200):
    """Primary path: pull all opps in a given NAICS code."""
    params = {
        "api_key": API_KEY,
        "limit": limit,
        "offset": 0,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "ncode": ncode,
        "ptype": "o,p,k,s,r",
        "status": "active",
    }
    try:
        r = requests.get(BASE_URL, params=params, timeout=30, verify=VERIFY_SSL)
        if r.status_code == 200:
            return r.json().get("opportunitiesData", [])
        print(f"  [sam] NAICS {ncode} HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  [sam] NAICS {ncode} error: {e}")
    return []


def fetch_opportunities(keyword: str, limit: int = 100):
    """Fallback keyword path for ASL/DeafBlind buys filed under odd NAICS."""
    params = {
        "api_key": API_KEY,
        "limit": limit,
        "offset": 0,
        "postedFrom": posted_from,
        "postedTo": posted_to,
        "q": keyword,
        "ptype": "o,p,k,s,r",
        "status": "active",
    }
    try:
        r = requests.get(BASE_URL, params=params, timeout=30, verify=VERIFY_SSL)
        if r.status_code == 200:
            return r.json().get("opportunitiesData", [])
        print(f"  [sam] '{keyword}' HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  [sam] '{keyword}' error: {e}")
    return []


def parse_opportunity(opp: dict) -> dict:
    title = opp.get("title", "")
    sol_num = opp.get("solicitationNumber", "")
    org_hier = opp.get("organizationHierarchy")
    if isinstance(org_hier, dict):
        dept = opp.get("fullParentPathName", org_hier.get("name", ""))
    else:
        dept = opp.get("fullParentPathName", opp.get("organizationName", ""))
    naics = opp.get("naicsCode") or ""
    ptype_map = {
        "o": "Solicitation",
        "p": "Pre-Solicitation",
        "k": "Combined Synopsis",
        "s": "Sources Sought",
        "r": "Sources Sought",
        "g": "Sale of Surplus",
        "a": "Award Notice",
    }
    ptype = ptype_map.get(opp.get("type", ""), opp.get("type", ""))
    posted = opp.get("postedDate", "")
    close_raw = opp.get("responseDeadLine", "") or opp.get("archiveDate", "")

    award = opp.get("award", {}) or {}
    est_value = ""
    if isinstance(award, dict):
        amt = award.get("amount")
        if amt:
            try:
                est_value = f"${float(amt):,.0f}"
            except Exception:
                est_value = str(amt)

    setaside = opp.get("typeOfSetAsideDescription", "") or opp.get("typeOfSetAside", "")

    pocs = opp.get("pointOfContact", []) or []
    poc_name = poc_email = poc_phone = ""
    if pocs and isinstance(pocs[0], dict):
        p = pocs[0]
        poc_name = p.get("fullName", p.get("name", ""))
        poc_email = p.get("email", "")
        poc_phone = p.get("phone", "")

    pop = opp.get("placeOfPerformance", {}) or {}
    city_name = state_code = ""
    if isinstance(pop, dict):
        city = pop.get("city")
        if isinstance(city, dict):
            city_name = city.get("name", "")
        st = pop.get("state")
        if isinstance(st, dict):
            state_code = st.get("code", "")
    location = f"{city_name}, {state_code}".strip(", ")

    link = f"https://sam.gov/opp/{opp.get('noticeId', '')}/view" if opp.get("noticeId") else ""

    return {
        "title": title,
        "solicitation_number": sol_num,
        "type": ptype,
        "department": dept,
        "naics": naics,
        "state": state_code,
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


def is_relevant(opp: dict) -> bool:
    """Strict relevance: title or description must actually mention interpretation,
    translation, ASL, deaf services, CART, language access, etc. Filters out the
    fuzzy SAM.gov matches like 'Guidance Signs' that bypass keyword intent."""
    title = (opp.get("title") or "").lower()
    desc = (opp.get("description") or "").lower()
    blob = title + " " + desc
    triggers = [
        "interpret", "translat", "linguist", "asl", "american sign",
        "sign language", "deaf", "deafblind", "tactile", "protactile",
        "cart ", "captioning", "language access", "vri ", "video remote",
        "language services", "language assistance",
    ]
    return any(t in blob for t in triggers)


def in_target_state(opp: dict) -> bool:
    """Soft filter: keep if state is one of our targets OR unspecified (national)."""
    pop = opp.get("placeOfPerformance", {}) or {}
    if not isinstance(pop, dict):
        return True
    st = pop.get("state")
    if not isinstance(st, dict):
        return True
    code = st.get("code") or ""
    if not code:
        return True
    return code in TARGET_STATES


def main():
    out_dir = str(OUTPUT_DIR / "interpretation_opportunities")
    os.makedirs(out_dir, exist_ok=True)

    all_opps = []
    seen = set()

    print(f"\nSAM.gov Interpretation/ASL scraper")
    print(f"Posted range: {posted_from} -> {posted_to}")
    print(f"Target states: {', '.join(TARGET_STATES)} (+ national, + OCONUS deaf/ASL)")
    print("=" * 72)

    # Pass 1: NAICS-coded buys (primary path)
    print("\n[Pass 1] NAICS-coded buys")
    for code, label in TARGET_NAICS.items():
        print(f"  NAICS {code} ({label[:35]})...", end=" ", flush=True)
        results = fetch_by_naics(code)
        new = 0
        for opp in results:
            nid = opp.get("noticeId") or opp.get("solicitationNumber", "")
            if not nid or nid in seen:
                continue
            if not is_relevant(opp):
                continue
            # NAICS 541930 = always relevant regardless of state (ASL/DeafBlind
            # OCONUS work like DOD Guam is real). Other NAICS apply state filter.
            if code != "541930" and not in_target_state(opp):
                continue
            seen.add(nid)
            all_opps.append(parse_opportunity(opp))
            new += 1
        print(f"{new} new ({len(results)} total in NAICS)")

    # Pass 2: ASL/DeafBlind keyword fallback (catches buys filed under wrong NAICS)
    print("\n[Pass 2] ASL/DeafBlind keyword fallback")
    for kw in ASL_KEYWORDS:
        print(f"  '{kw}'...", end=" ", flush=True)
        results = fetch_opportunities(kw)
        new = 0
        for opp in results:
            nid = opp.get("noticeId") or opp.get("solicitationNumber", "")
            if not nid or nid in seen:
                continue
            if not is_relevant(opp):
                continue
            seen.add(nid)
            all_opps.append(parse_opportunity(opp))
            new += 1
        print(f"{new} new")

    # Sort by close date soonest first
    all_opps.sort(key=lambda o: o["close_date"] or "9999")
    print(f"\nTotal unique relevant opportunities: {len(all_opps)}")

    csv_path = os.path.join(out_dir, "sam_interpretation_opps.csv")
    md_path = os.path.join(out_dir, "sam_interpretation_opps.md")

    if all_opps:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_opps[0].keys())
            writer.writeheader()
            writer.writerows(all_opps)
        print(f"CSV saved: {csv_path}")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# SAM.gov Interpretation & ASL Opportunities\n")
        f.write(f"**Pulled:** {today.strftime('%Y-%m-%d')} | ")
        f.write(f"**Posted range:** last 120 days | **Total:** {len(all_opps)}\n\n")
        f.write(f"Target NAICS: {', '.join(TARGET_NAICS.keys())} | ")
        f.write(f"Target states: {', '.join(TARGET_STATES)} + national\n\n---\n\n")

        for i, o in enumerate(all_opps, 1):
            f.write(f"## {i}. {o['title']}\n")
            f.write(f"**Type:** {o['type']} | **NAICS:** {o['naics']} | "
                    f"**Posted:** {o['posted']} | **Closes:** {o['close_date']}\n\n")
            if o["est_value"]:
                f.write(f"**Estimated Value:** {o['est_value']}\n\n")
            if o["set_aside"]:
                f.write(f"**Set-Aside:** {o['set_aside']}\n\n")
            if o["department"]:
                f.write(f"**Agency:** {o['department']}\n\n")
            if o["location"]:
                f.write(f"**Location:** {o['location']}\n\n")
            if o["solicitation_number"]:
                f.write(f"**Solicitation #:** {o['solicitation_number']}\n\n")
            poc_line = " ".join(x for x in (o["poc_name"], o["poc_email"], o["poc_phone"]) if x)
            if poc_line:
                f.write(f"**POC:** {poc_line}\n\n")
            if o["link"]:
                f.write(f"**Link:** {o['link']}\n\n")
            f.write("---\n\n")

    print(f"Markdown saved: {md_path}")
    return all_opps


if __name__ == "__main__":
    main()
