"""When a supplier's website domain was registered, from public RDAP records. A site a few weeks old is a classic scam sign."""
import re
from urllib.parse import urlparse

import httpx

# Hosted pages and marketplaces: their age says nothing about the supplier
PLATFORMS = ("business.site", "wixsite.com", "blogspot.com", "wordpress.com", "facebook.com", "instagram.com", "linkedin.com",
             "indiamart.com", "justdial.com", "tradeindia.com", "google.com", "sites.google.com", "linktr.ee", "wa.me")


def domain_of(website: str | None) -> str | None:
    if not website:
        return None
    host = (urlparse(website if "//" in website else f"https://{website}").hostname or "").lower()
    host = re.sub(r"^www\d?\.", "", host)
    if not host or "." not in host or any(p in host for p in PLATFORMS):
        return None
    # The registrable part: example.co.in, example.com
    parts = host.split(".")
    keep = 3 if len(parts) > 2 and parts[-2] in ("co", "org", "net", "gov", "ac", "edu", "firm", "gen", "ind") else 2
    return ".".join(parts[-keep:])


def registered(domain: str, client: httpx.Client | None = None) -> str | None:
    """The registration date (YYYY-MM-DD) RDAP reports for a domain, or None if it cannot say."""
    http = client or httpx.Client(timeout=8, follow_redirects=True)
    try:
        response = http.get(f"https://rdap.org/domain/{domain}", headers={"Accept": "application/rdap+json"})
        if response.status_code != 200:
            return None
        for event in response.json().get("events", []):
            if event.get("eventAction") == "registration" and event.get("eventDate"):
                return event["eventDate"][:10]
    except (httpx.HTTPError, ValueError):
        return None
    return None
