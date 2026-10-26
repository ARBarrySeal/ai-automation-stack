"""Security-headers audit for prospect domains.

Checks each domain for the six standard HTTP security headers and assigns
a letter grade (same idea as securityheaders.com / Geekflare's checker).
Use the grade as a cold-outreach hook: "your site scores an F on security
headers" — passive check, only reads public HTTP response headers.

Usage:
    python security_headers_audit.py example.com another.com
    python security_headers_audit.py --file domains.txt
    python security_headers_audit.py --file domains.txt --csv results.csv

domains.txt: one domain per line (blank lines and # comments ignored).
"""

import argparse
import csv
import ssl
import sys
import urllib.request

# The six headers graders like securityheaders.com score on
HEADERS = [
    "Strict-Transport-Security",
    "Content-Security-Policy",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
]

GRADES = {6: "A+", 5: "A", 4: "B", 3: "C", 2: "D", 1: "E", 0: "F"}

TIMEOUT = 15
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SecurityHeadersAudit/1.0"


def fetch_headers(domain):
    """GET https://domain and return the final response headers, or an error string."""
    url = domain if domain.startswith("http") else f"https://{domain}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    # certifi bundle first: Python's default Windows store can miss newer
    # roots (e.g. ISRG X2) and mis-report valid certs as expired.
    contexts = []
    try:
        import certifi
        contexts.append(ssl.create_default_context(cafile=certifi.where()))
    except ImportError:
        pass
    contexts.append(ssl.create_default_context())

    err = None
    for ctx in contexts:
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
                return dict(resp.headers), None
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
    return None, err


def audit(domain):
    headers, err = fetch_headers(domain)
    result = {"domain": domain, "grade": "ERR", "error": err or "", "notes": []}
    if err:
        return result

    lower = {k.lower(): v for k, v in headers.items()}
    present = []
    for h in HEADERS:
        val = lower.get(h.lower())
        result[h] = "yes" if val else "MISSING"
        if val:
            present.append(h)

    result["grade"] = GRADES[len(present)]

    # Weak-configuration flags (present but poorly set)
    hsts = lower.get("strict-transport-security", "")
    if hsts and "max-age" in hsts:
        try:
            age = int(hsts.split("max-age=")[1].split(";")[0].strip())
            if age < 15552000:  # < 180 days
                result["notes"].append("HSTS max-age under 180 days")
        except (ValueError, IndexError):
            pass
    csp = lower.get("content-security-policy", "")
    if "unsafe-inline" in csp:
        result["notes"].append("CSP allows unsafe-inline")
    server = lower.get("server", "")
    if any(c.isdigit() for c in server):
        result["notes"].append(f"Server version disclosed: {server}")

    return result


def main():
    ap = argparse.ArgumentParser(description="Grade domains on HTTP security headers")
    ap.add_argument("domains", nargs="*", help="domains to check")
    ap.add_argument("--file", help="file with one domain per line")
    ap.add_argument("--csv", help="write results to this CSV file")
    args = ap.parse_args()

    domains = list(args.domains)
    if args.file:
        with open(args.file, encoding="utf-8-sig") as f:
            domains += [
                line.strip() for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
    if not domains:
        ap.error("no domains given (pass domains or --file)")

    results = []
    for d in domains:
        r = audit(d)
        results.append(r)
        missing = [h for h in HEADERS if r.get(h) == "MISSING"]
        line = f"{r['domain']:<35} {r['grade']:>3}"
        if r["error"]:
            line += f"  ({r['error']})"
        elif missing:
            line += f"  missing: {', '.join(missing)}"
        if r["notes"]:
            line += f"  [{'; '.join(r['notes'])}]"
        print(line)

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["domain", "grade"] + HEADERS + ["notes", "error"])
            for r in results:
                w.writerow(
                    [r["domain"], r["grade"]]
                    + [r.get(h, "") for h in HEADERS]
                    + ["; ".join(r["notes"]), r["error"]]
                )
        print(f"\nCSV written to {args.csv}")

    graded = [r for r in results if r["grade"] != "ERR"]
    bad = sum(1 for r in graded if r["grade"] in ("D", "E", "F"))
    print(f"\n{len(graded)} checked, {bad} graded D or worse (your outreach targets)")


if __name__ == "__main__":
    main()
