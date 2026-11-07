import argparse
import hashlib
import math
import re

import requests

COMMON_PASSWORDS = {
    "password",
    "password1",
    "123456",
    "12345678",
    "123456789",
    "qwerty",
    "qwerty123",
    "admin",
    "admin123",
    "letmein",
    "welcome",
    "iloveyou",
    "dragon",
    "monkey",
    "abc123",
}

KEYBOARD_PATTERNS = ["qwerty", "asdf", "zxcv", "123456", "12345", "111111", "000000"]
HEADERS = {"User-Agent": "osint-course/1.0 (educational use)"}


def charset_size(password: str) -> int:
    size = 0
    if re.search(r"[a-z]", password):
        size += 26
    if re.search(r"[A-Z]", password):
        size += 26
    if re.search(r"[0-9]", password):
        size += 10
    if re.search(r"[^A-Za-z0-9]", password):
        size += 33
    return size or 1


def entropy(password: str) -> float:
    return round(len(password) * math.log2(charset_size(password)), 1)


def audit_passwords(path: str) -> None:
    try:
        with open(path, encoding="utf-8") as handle:
            lines = [line.rstrip("\n") for line in handle]
    except OSError as error:
        print(f"[XATO] Faylni o'qib bo'lmadi: {error}")
        return

    seen = {}
    weak = 0
    reused = 0
    total = 0

    print(f"[i] Parol auditi: {path} (parollar ko'rsatilmaydi)\n")
    for index, password in enumerate(lines, start=1):
        if not password:
            continue
        total += 1

        fingerprint = hashlib.sha256(password.encode("utf-8")).hexdigest()[:10]
        bits = entropy(password)
        flags = []

        if len(password) < 12:
            flags.append("qisqa")
        if bits < 60:
            flags.append(f"zaif entropiya ({bits} bit)")
        if password.lower() in COMMON_PASSWORDS:
            flags.append("mashhur parol")
        if any(pattern in password.lower() for pattern in KEYBOARD_PATTERNS):
            flags.append("klaviatura naqshi")
        if re.fullmatch(r"[0-9]+", password):
            flags.append("faqat raqamlar")
        if re.fullmatch(r"[A-Za-z]+", password):
            flags.append("faqat harflar")
        if password in seen:
            flags.append(f"TAKROR (#{seen[password]} bilan bir xil)")
            reused += 1
        else:
            seen[password] = index
        if flags:
            weak += 1

        status = "; ".join(flags) if flags else "yaxshi"
        print(f"  #{index:<3} len={len(password):<3} entropy={bits:<6} id={fingerprint}  {status}")

    print(f"\n[i] Jami: {total} | Muammoli: {weak} | Takrorlangan: {reused}")
    if reused:
        print("[!] Bir xil parol bir nechta joyda ishlatilgan — bittasi sizsa, hammasi xavfda.")


def network_check() -> None:
    print("[i] Tarmoq tekshiruvi...\n")
    try:
        response = requests.get("https://api.ipify.org?format=json", headers=HEADERS, timeout=10)
        ip = response.json()["ip"]
    except (requests.RequestException, ValueError, KeyError) as error:
        print(f"[XATO] Tashqi IP aniqlanmadi: {error}")
        return

    print(f"  Tashqi IP: {ip}")
    try:
        response = requests.get(f"https://ipwho.is/{ip}", headers=HEADERS, timeout=10)
        info = response.json()
        if info.get("success"):
            connection = info.get("connection", {})
            security = info.get("security", {})
            print(f"  Joylashuv: {info.get('country')}, {info.get('city')}")
            print(f"  ISP: {connection.get('isp', 'n/a')} | ASN: {connection.get('asn', 'n/a')}")
            print(f"  Proxy: {security.get('proxy')} | Hosting: {security.get('hosting')} | Tor: {security.get('tor')}")
    except (requests.RequestException, ValueError) as error:
        print(f"  [i] Geo ma'lumoti olinmadi: {error}")

    try:
        response = requests.get("https://check.torproject.org/api/ip", headers=HEADERS, timeout=10)
        tor = response.json()
        print(f"  Tor orqali: {tor.get('IsTor')}")
    except (requests.RequestException, ValueError) as error:
        print(f"  [i] Tor holati aniqlanmadi: {error}")

    if ip:
        print("\n[!] Agar VPN/Tor yoqilmagan bo'lsa, bu IP sizning haqiqiy manzilingizdir.")
    print("  Brauzer fingerprint: https://amiunique.org")
    print("  DNS leak: https://dnsleaktest.com")
    print("  WebRTC leak: https://browserleaks.com/webrtc")


def checklist() -> None:
    print("[i] Anonimlik self-audit checklist:\n")
    items = [
        "Threat model yozildi: kimdan yashirinmoqdasiz?",
        "Tadqiqot uchun alohida brauzer profili bor",
        "Shaxsiy va ish/tadqiqot akkauntlari aralashmagan",
        "Har bir xizmatda noyob parol (password manager)",
        "2FA yoqilgan (SMS emas, ilova/apparat kaliti)",
        "Email alias ishlatiladi",
        "Profil rasmi boshqa akkauntda ishlatilmagan",
        "Fayl yuborishdan oldin metadata tozalanadi",
        "VPN/Tor ishlatilsa, DNS va WebRTC leak tekshirilgan",
        "Tadqiqot davomida hech qanday like/follow/izoh yo'q",
    ]
    for item in items:
        print(f"  [ ] {item}")
    print("\n  Brauzer: https://coveryourtracks.eff.org")
    print("  IP/DNS/WebRTC: https://ipleak.net")


def main() -> None:
    parser = argparse.ArgumentParser(description="OPSEC self-audit vositasi")
    parser.add_argument("--network", action="store_true", help="tashqi IP va proxy/Tor holatini tekshirish")
    parser.add_argument("--passwords", metavar="FAYL", help="parollar ro'yxatini audit qilish (har biri yangi qatorda)")
    args = parser.parse_args()

    if args.network:
        network_check()
    elif args.passwords:
        audit_passwords(args.passwords)
    else:
        checklist()


if __name__ == "__main__":
    main()
