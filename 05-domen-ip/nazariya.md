# 5-modul: Domen, IP va Web texnologiyalar

## Nazariya: Domen → IP → Xizmat zanjiri

Bitta domen ortida butun bir infratuzilma yashiringan:

```
example.com
   │  DNS so'rov
   ▼
IP manzil (104.20.23.154)
   │  hosting / CDN / proxy
   ▼
Server + TLS sertifikat + Web ilova
   │
   ├── subdomenlar (mail., dev., admin.)
   ├── MX / SPF / DMARC (email)
   └── HTTP sarlavhalar, cookies, texnologiyalar
```

OSINTda domen tekshiruvi **passiv** bosqichdan boshlanadi: hech kimning serveriga
ruxsatsiz "urilmaydi", faqat ochiq manbalar o'qiladi.

## 1. DNS yozuvlari

| Yozuv | Ma'nosi | OSINTda nima beradi |
|-------|---------|---------------------|
| `A` | Domen → IPv4 | Server qayerda joylashgan |
| `AAAA` | Domen → IPv6 | Muqobil manzil |
| `MX` | Email serverlar | Qaysi provayder (Google, Yandex...) |
| `NS` | Nameserverlar | DNS boshqaruvi kimda (Cloudflare, registrar) |
| `TXT` | Matnli yozuvlar | SPF, DMARC, domen tasdiqlash kalitlari |
| `CNAME` | Alias | Boshqa xizmatga bog'lanish (CDN, SaaS) |
| `SOA` | Zona ma'lumoti | Asosiy NS va contact email |

```bash
dig example.com A
dig example.com MX
dig example.com TXT
nslookup -type=NS example.com
```
Yoki barchasini birdan: `dig example.com ANY` (har doim ham ishlamaydi).

## 2. Domen ro'yxatga olish (WHOIS / RDAP)

WHOIS eski protokol, **RDAP** uning zamonaviy JSON versiyasi:

| Maydon | Nimani ko'rsatadi |
|--------|-------------------|
| Registrar | Domen qaysi kompaniyada ro'yxatga olingan |
| Creation date | Domen qachon ochilgan (yosh firma belgisi) |
| Expiration date | Muddati tugash sanasi |
| Nameservers | DNS xizmati kimda |
| Registrant | Egasi (ko'pincha maxfiylashtirilgan) |
| Status | `clientTransferProhibited`, `ok` va h.k. |

Ko'p domenlar **privacy protection** bilan yopilgan — egasi ko'rinmaydi.
Bu normal holat, xulosa chiqarishdan oldin buni hisobga oling.

## 3. IP manzil va ASN

- **ASN** (Autonomous System Number) — IP qaysi tarmoqqa tegishli ekanini bildiradi
- **GeoIP** — taxminiy mamlakat/shahar (VPN va CDN tufayli noto'g'ri bo'ladi)
- **Reverse DNS** (`dig -x IP`) — IP → domen nomi
- **Shared hosting** — bitta IPda yuzlab domen bo'lishi mumkin

⚠️ Cloudflare kabi CDN orqasidagi domenning IP'si **haqiqiy server emas**.
`Server: cloudflare` ko'rsangiz, orqadagi asl IPni topish alohida tadqiqot.

## 4. Subdomenlar (passiv usul)

Subdomenlar ko'pincha unutilgan va himoyasiz bo'ladi: `dev.`, `test.`, `admin.`, `vpn.`.

| Manba | Usul |
|-------|------|
| crt.sh | Sertifikat shaffofligi (Certificate Transparency) |
| subfinder | Ko'p manbali passiv qidiruv |
| dnsdumpster | Vizual DNS xarita |
| urlscan.io | Sayt skanerlari tarixi |

```bash
curl -s "https://crt.sh/?q=%25.example.com&output=json" | jq -r '.[].name_value' | sort -u
```

⚠️ Topilgan subdomenlarga **avtomatik hujum qilmang** — faqat ro'yxatini tuzing.
Faol skanerlash faqat ruxsat berilgan tizimlarda (o'zingizniki yoki bug bounty) amalga oshiriladi.

## 5. Web texnologiyalar

Saytning o'zi haqida ochiq ma'lumot beradigan joylar:

- **HTTP sarlavhalar**: `Server`, `X-Powered-By`, `Set-Cookie`, xavfsizlik sarlavhalari
- **HTML izlari**: `wp-content` (WordPress), `_next/` (Next.js), `ng-version` (Angular)
- **robots.txt** va **sitemap.xml**: yashirin bo'limlar va sahifalar
- **security.txt**: xavfsizlik bo'yicha aloqa
- **Favicon hash**: Shodan'da bir xil ilovani topish uchun

```bash
curl -I https://example.com
curl https://example.com/robots.txt
```

Xavfsizlik sarlavhalari yo'qligi ham muhim signal:
`Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`.

## 6. TLS sertifikatlar

Sertifikatdan quyidagilarni olish mumkin:
- Domen egalari (SAN ro'yxati — ko'pincha subdomenlar ham)
- Kim bergan (Let's Encrypt, DigiCert...)
- Amal qilish muddati

```bash
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

crt.sh aynan shu sertifikatlar tarixidan subdomenlarni topadi.

## 7. Arxiv va skanerlar

| Xizmat | Nima beradi |
|--------|-------------|
| Wayback Machine | Saytning eski versiyalari (o'chirilgan sahifalar) |
| urlscan.io | Sayt skanerlari, resurslar, texnologiyalar |
| Shodan | Internetga ochiq serverlar (banner, port) |
| Censys | Hostlar va sertifikatlar indeksi |
| FOFA | Muqobil xitoy indeksi |

⚠️ Shodan/Censys natijalari ham **passiv** — lekin topilgan tizimga kirishga urinish jinoyat.

## OPSEC va qonuniy chegaralar
- Faqat **ochiq manbalar** va **passiv** usullar
- Port skanerlash, brute-force, ekspluatatsiya — ruxsatsiz qilmang
- So'rovlarni rejalashtiring: katta skanerlar IP'ingizni bloklashi mumkin
- Kompaniya infratuzilmasini o'rganishda maqsadni va ruxsatni hujjatlashtiring
- Natijalarni **gipoteza** sifatida saqlang, tasdiqlashni qo'lda qiling

## Kod: `domain_info.py`
→ [kod/domain_info.py](kod/domain_info.py)

Skript nimalarni yig'adi:
- DNS: A, AAAA, MX, NS, TXT, CNAME, SOA
- RDAP: registrar, sana, nameserver, status
- HTTP: status, `Server`, `X-Powered-By`, xavfsizlik sarlavhalari
- crt.sh orqali subdomenlar
- TLS sertifikat: subject, issuer, muddat, SAN

O'rganadigan narsalar:
- `dnspython` bilan DNS so'rovlar va xatolarni boshqarish
- RDAP JSON API bilan ishlash
- `requests` + timeout + exception handling
- `ssl` va `socket` orqali sertifikat olish

## Mashqlar
→ [mashqlar.md](mashqlar.md)
