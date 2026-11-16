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
    {"name": "Social-Analyzer", "url": "https://github.com/qeeqbox/social-analyzer", "category": "Username / Identity", "note": "1000+ sites with a 0-100 detection score (AGPL-3.0)"},
    {"name": "Photon", "url": "https://github.com/s0md3v/Photon", "category": "Domain & Infrastructure", "note": "Website crawler that extracts emails, social links and files"},
    {"name": "WhatsMyName", "url": "https://whatsmyname.app/", "category": "Username / Identity", "note": "Web checker from the OSINT community dataset. The dataset repo was archived in 2026, so its site list no longer gets fixes"},
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
    {"name": "Subfinder", "url": "https://github.com/projectdiscovery/subfinder", "category": "Domain & Infrastructure", "note": "Passive subdomain enumeration from dozens of sources (integrated here)"},
    {"name": "OWASP Amass", "url": "https://github.com/owasp-amass/amass", "category": "Domain & Infrastructure", "note": "In-depth attack-surface mapping; heavier than Subfinder, run it yourself for deep work"},
    {"name": "theHarvester", "url": "https://github.com/laramies/theHarvester", "category": "Domain & Infrastructure", "note": "Emails, hosts and names for a domain; our 'Published emails' check covers its key-free search part"},
    {"name": "SpiderFoot", "url": "https://github.com/smicallef/spiderfoot", "category": "Domain & Infrastructure", "note": "200+ module automation framework; last release 2022, useful as a reference"},
    {"name": "SearXNG", "url": "https://github.com/searxng/searxng", "category": "Search Engines", "note": "Self-hosted metasearch; this tool's web search runs through its own instance"},
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
    {"name": "Reddit search", "url": "https://www.reddit.com/search/", "category": "Social Media", "note": "Keyword search across Reddit (native)"},
    {"name": "Bluesky/Grake/Mastodon lists", "url": "https://github.com/jivoi/awesome-osint#social-media", "category": "Social Media", "note": "Per-platform tool lists in upstream repo"},
    {"name": "Google Lens", "url": "https://lens.google.com/", "category": "Images & Geospatial", "note": "Reverse-image search from URL or upload (linked from Image tab)"},
    {"name": "Bing Visual Search", "url": "https://www.bing.com/visualsearch", "category": "Images & Geospatial", "note": "Alternative reverse-image index (linked from Image tab)"},
    {"name": "Gravatar", "url": "https://gravatar.com/", "category": "Email", "note": "Public avatar lookup by email MD5 (integrated here)"},
    {"name": "MXToolbox", "url": "https://mxtoolbox.com/", "category": "Email", "note": "MX, SPF and DMARC diagnostics"},
    {"name": "EasyDMARC", "url": "https://easydmarc.com/tools/dmarc-lookup", "category": "Email", "note": "DMARC record and policy checker"},
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
