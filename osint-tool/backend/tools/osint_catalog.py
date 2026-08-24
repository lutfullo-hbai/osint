CATALOG = [
    {"name": "Awesome OSINT (upstream)", "url": "https://github.com/jivoi/awesome-osint", "category": "Meta", "note": "The full curated list this catalog is based on"},
    {"name": "Bellingcat Toolkit", "url": "https://bellingcat.gitbook.io/toolkit", "category": "Meta", "note": "Investigation tools maintained by Bellingcat"},
    {"name": "OSINT Framework", "url": "https://osintframework.com/", "category": "Meta", "note": "Tree of OSINT resources by category"},
    {"name": "IntelTechniques Tools", "url": "https://inteltechniques.com/tools/", "category": "Meta", "note": "Search tool collection by Michael Bazzell"},
    {"name": "Google", "url": "https://www.google.com/advanced_search", "category": "Search Engines", "note": "Advanced search: site:, intitle:, filetype:, cache operators"},
    {"name": "Google Hacking Database", "url": "https://www.exploit-db.com/google-hacking-database", "category": "Search Engines", "note": "Community dork database (GHDB)"},
    {"name": "DuckDuckGo", "url": "https://duckduckgo.com/", "category": "Search Engines", "note": "No tracking, good for dorking"},
    {"name": "Yandex", "url": "https://yandex.com/", "category": "Search Engines", "note": "Strong on images and CIS-region content"},
    {"name": "Bing", "url": "https://www.bing.com/", "category": "Search Engines", "note": "ip: and feed: operators, different index than Google"},
    {"name": "Startpage", "url": "https://www.startpage.com/", "category": "Search Engines", "note": "Google results without profiling"},
    {"name": "Sherlock", "url": "https://github.com/sherlock-project/sherlock", "category": "Username / Identity", "note": "Hunts a username across 400+ social networks (integrated here)"},
    {"name": "Maigret", "url": "https://github.com/soxoj/maigret", "category": "Username / Identity", "note": "3000+ sites username scan with report extraction (integrated here)"},
    {"name": "WhatsMyName", "url": "https://whatsmyname.app/", "category": "Username / Identity", "note": "Web checker from the OSINT community dataset"},
    {"name": "Namechk", "url": "https://namechk.com/", "category": "Username / Identity", "note": "Quick username availability across platforms"},
    {"name": "Instant Username Search", "url": "https://instantusername.com/", "category": "Username / Identity", "note": "Live check while typing"},
    {"name": "Holehe", "url": "https://github.com/megadose/holehe", "category": "Email", "note": "Checks 200+ sites for registered emails (integrated here)"},
    {"name": "Have I Been Pwned", "url": "https://haveibeenpwned.com/", "category": "Email", "note": "Breach database; API key enables our HIBP module"},
    {"name": "EmailRep", "url": "https://emailrep.io/", "category": "Email", "note": "Email reputation scores (integrated here)"},
    {"name": "Hunter.io", "url": "https://hunter.io/", "category": "Email", "note": "Find email patterns per company domain (freemium)"},
    {"name": "MailTester", "url": "https://www.mailtester.com/", "category": "Email", "note": "SMTP-level mailbox existence verification"},
    {"name": "PhoneInfoga", "url": "https://github.com/sundowndev/phoneinfoga", "category": "Phone", "note": "Number scanning framework (our Telecom info uses same libphonenumber data)"},
    {"name": "Truecaller", "url": "https://www.truecaller.com/", "category": "Phone", "note": "Community caller-ID database (we scrape the public page best-effort)"},
    {"name": "Tellows", "url": "https://www.tellows.com/", "category": "Phone", "note": "Crowd-sourced spam number reports"},
    {"name": "NumLookup", "url": "https://www.numlookup.com/", "category": "Phone", "note": "Free reverse phone lookup with carrier data"},
    {"name": "Free Carrier Lookup", "url": "https://freecarrierlookup.com/", "category": "Phone", "note": "Carrier + line type by number"},
    {"name": "Shodan", "url": "https://www.shodan.io/", "category": "Domain & Infrastructure", "note": "Internet-connected device/service search engine (freemium)"},
    {"name": "Censys Search", "url": "https://search.censys.io/", "category": "Domain & Infrastructure", "note": "Host and certificate intelligence (freemium)"},
    {"name": "crt.sh", "url": "https://crt.sh/", "category": "Domain & Infrastructure", "note": "Certificate transparency log search (integrated here)"},
    {"name": "DNSDumpster", "url": "https://dnsdumpster.com/", "category": "Domain & Infrastructure", "note": "Visual DNS recon map"},
    {"name": "ViewDNS.info", "url": "https://viewdns.info/", "category": "Domain & Infrastructure", "note": "Reverse IP, whois history, DNS toolbox"},
    {"name": "urlscan.io", "url": "https://urlscan.io/", "category": "Domain & Infrastructure", "note": "Scan and archive page structure + resources"},
    {"name": "Wayback Machine", "url": "https://web.archive.org/", "category": "Archives & Metadata", "note": "Historical snapshots of any site"},
    {"name": "archive.today", "url": "https://archive.ph/", "category": "Archives & Metadata", "note": "On-demand permanent page snapshots"},
    {"name": "ExifTool", "url": "https://exiftool.org/", "category": "Archives & Metadata", "note": "Read/write file metadata incl. GPS from photos"},
    {"name": "Jimpl EXIF viewer", "url": "https://jimpl.com/", "category": "Archives & Metadata", "note": "Online photo metadata + GPS viewer"},
    {"name": "ip-api.com", "url": "http://ip-api.com/", "category": "Domain & Infrastructure", "note": "Free IP geolocation API (integrated here)"},
    {"name": "ipinfo.io", "url": "https://ipinfo.io/", "category": "Domain & Infrastructure", "note": "IP ASN/geo/company data (freemium)"},
    {"name": "Google Maps", "url": "https://www.google.com/maps", "category": "Images & Geospatial", "note": "Street View geolocation verification"},
    {"name": "Google Earth", "url": "https://earth.google.com/web/", "category": "Images & Geospatial", "note": "Historical satellite imagery slider"},
    {"name": "Yandex Images", "url": "https://yandex.com/images/", "category": "Images & Geospatial", "note": "Best-in-class reverse image search"},
    {"name": "TinEye", "url": "https://tineye.com/", "category": "Images & Geospatial", "note": "Oldest appearance date of an image"},
    {"name": "Flickr", "url": "https://www.flickr.com/map", "category": "Images & Geospatial", "note": "Geotagged public photos by area"},
    {"name": "SunCalc", "url": "https://www.suncalc.org/", "category": "Images & Geospatial", "note": "Shadow-based time-of-photo estimation"},
    {"name": "LinkedIn", "url": "https://www.linkedin.com/", "category": "Social Media", "note": "Company/person employment graph; X-ray via site:linkedin.com/in"},
    {"name": "Telegram web", "url": "https://web.telegram.org/", "category": "Social Media", "note": "Public channels preview at t.me/s/channelname"},
    {"name": "Reddit search", "url": "https://redditsearch.io/", "category": "Social Media", "note": "Keyword search across Reddit history"},
    {"name": "Bluesky/Grake/Mastodon lists", "url": "https://github.com/jivoi/awesome-osint#social-media", "category": "Social Media", "note": "Per-platform tool lists in upstream repo"},
]

CATEGORY_ORDER = [
    "Meta",
    "Search Engines",
    "Username / Identity",
    "Email",
    "Phone",
    "Domain & Infrastructure",
    "Archives & Metadata",
    "Images & Geospatial",
    "Social Media",
]


def get_catalog() -> dict:
    grouped = {category: [] for category in CATEGORY_ORDER}
    for item in CATALOG:
        grouped.setdefault(item["category"], []).append(item)
    categories = [
        {"name": category, "items": items}
        for category, items in grouped.items()
        if items
    ]
    return {
        "status": "success",
        "count": len(CATALOG),
        "categories": categories,
    }
