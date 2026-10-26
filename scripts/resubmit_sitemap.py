#!/usr/bin/env python3
"""
Resubmit a sitemap to Google Search Console via the Search Console API.

Keyless: mints a short-lived webmasters-scoped access credential by impersonating
the sitemap-submitter service account through gcloud (no JSON key on disk).

Prereq (one-time, done by a property owner in the Search Console UI):
  Add your service account (GSC_SERVICE_ACCOUNT in .env) as an Owner of the property at https://search.google.com/search-console
  -> Settings -> Users and permissions -> Add user.

Usage:
  python resubmit_sitemap.py                      # every domain in SITE_DOMAINS (.env)
  python resubmit_sitemap.py --domain example.com # any site the SA can access
"""
import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error

from _env import require, env

SA = require("GSC_SERVICE_ACCOUNT")
SCOPE = "https://www.googleapis.com/auth/webmasters"
API = "https://www.googleapis.com/webmasters/v3"


def mint_cred():
    """Mint a webmasters-scoped access credential via SA impersonation."""
    cmd = [
        "gcloud", "auth", "print-access-token",
        "--impersonate-service-account=" + SA,
        "--scopes=" + SCOPE,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    if out.returncode != 0:
        sys.exit("Credential mint failed:\n" + out.stderr.strip())
    return out.stdout.strip()


def api(cred, method, path):
    """Call the Search Console API. Returns (status, body)."""
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Authorization", "Bearer " + cred)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, (r.read().decode() or "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def find_property(cred, domain):
    """Return the siteUrl the SA can access that matches `domain`."""
    status, body = api(cred, "GET", "/sites")
    if status == 403:
        sys.exit(
            "403 Forbidden listing sites.\n"
            "The service account is not yet a user on any property.\n"
            "Add " + SA + " as an Owner in Search Console first."
        )
    if status != 200:
        sys.exit("Could not list sites (HTTP %s): %s" % (status, body))
    entries = json.loads(body).get("siteEntry", [])
    candidates = ["sc-domain:" + domain, "https://%s/" % domain, "https://www.%s/" % domain]
    for c in candidates:
        for e in entries:
            if e.get("siteUrl") == c:
                return c
    accessible = ", ".join(e.get("siteUrl", "?") for e in entries) or "(none)"
    sys.exit(
        "No property matching '%s' is accessible to the service account.\n"
        "Accessible properties: %s\n"
        "Add the matching property's Owner access for %s." % (domain, accessible, SA)
    )


def submit(cred, domain, sitemap=None):
    sitemap = sitemap or ("https://%s/sitemap.xml" % domain)
    site = find_property(cred, domain)
    print("Property: " + site)
    print("Sitemap : " + sitemap)

    feed = urllib.parse.quote(sitemap, safe="")
    site_enc = urllib.parse.quote(site, safe="")

    status, body = api(cred, "PUT", "/sites/%s/sitemaps/%s" % (site_enc, feed))
    if status in (200, 204):
        print("Submitted OK -> forcing recrawl.")
    else:
        sys.exit("Submit failed (HTTP %s): %s" % (status, body))

    status, body = api(cred, "GET", "/sites/%s/sitemaps/%s" % (site_enc, feed))
    if status == 200:
        d = json.loads(body)
        contents = d.get("contents", [{}])
        submitted = contents[0].get("submitted", "?") if contents else "?"
        print("  URLs submitted : " + str(submitted))
        print("  Errors         : " + str(d.get("errors", "0")))
        print("  Warnings       : " + str(d.get("warnings", "0")))
        print("  Last submitted : " + str(d.get("lastSubmitted", "?")))
    print("Done.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--domain", default=None, help="default: every domain in SITE_DOMAINS")
    p.add_argument("--sitemap", default=None)
    args = p.parse_args()
    domains = [args.domain] if args.domain else [d.strip() for d in env("SITE_DOMAINS").split(",") if d.strip()]
    if not domains:
        sys.exit("Pass --domain or set SITE_DOMAINS in .env")
    cred = mint_cred()
    for d in domains:
        print("--- %s ---" % d)
        submit(cred, d, args.sitemap)


if __name__ == "__main__":
    main()
