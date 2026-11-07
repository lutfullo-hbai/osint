# OSINT Investigation Tool

Local OSINT helper: FastAPI backend (Sherlock, Maigret, Holehe, Truecaller best-effort,
DNS/RDAP/crt.sh) + static nginx frontend.

## Ishga tushirish

```bash
docker compose up -d --build
```

- Frontend: http://127.0.0.1:8080
- Backend: http://127.0.0.1:8000
- API docs: http://127.0.0.1:8000/docs

To'xtatish: `docker compose down`

## Case (tergov) boshqaruvi

Har bir qidiruv alohida emas — bir **case**ga yig'iladi:
- **Cases** bo'limida case ochasiz; istalgan natijada **"Save to case"** bosasiz
- Case ichida barcha topilmalar manba va vaqt (provenance) bilan saqlanadi (SQLite,
  restart'da yo'qolmaydi)
- **Birlashtirilgan hisobot**: butun case bo'yicha Export MD/JSON, Print/PDF, entity
  graf va **AI xulosa** (barcha topilmalar ustidan)

Ma'lumotlar `osint-data` volume'ida (`/app/data/cases.db`) saqlanadi.

## AI tahlil (lokal Qwen)

Har qanday natijada **"AI Summary"** tugmasi bor. Bosilganda brauzer
to'g'ridan-to'g'ri lokal **Ollama** (Qwen) modeliga murojaat qiladi va natijalarni
qisqa analitik xulosaga (topilganlar, qarama-qarshiliklar, ishonch darajasi,
keyingi qadam) aylantiradi. **Kalit kerak emas, ma'lumot kompyuterдан chiqmaydi.**

Talab: hostда Ollama + Qwen modeli ishlab turishi (`ollama pull qwen2.5:7b`).

**Rasm tahlili (AI Vision):** Image bo'limida "AI Vision" tugmasi rasmni lokal
vision modelga yuboradi (joy, belgilar, til, ob'ektlar — geolokatsiyaga yordam).
Vision model kerak: `ollama pull qwen2.5vl:7b` (yoki `llava`, `moondream`).
Standart model `qwen2.5vl:7b`, `osint_ollama_vision_model` bilan o'zgartiriladi.
Standart: `http://127.0.0.1:11434`, model `qwen2.5:7b`. O'zgartirish:

```js
localStorage.setItem("osint_ollama_url", "http://127.0.0.1:11434");
localStorage.setItem("osint_ollama_model", "qwen3:8b");
```

## Xavfsizlik

Backend faqat `127.0.0.1`ga bog'lanadi. Quyidagi himoyalar yoqilgan:

### CORS
Faqat `ALLOWED_ORIGINS` (vergul bilan ajratilgan) ro'yxatidagi saytlar API'ni brauzerdan
chaqira oladi. Default: `http://127.0.0.1:8080,http://localhost:8080`.

### SSRF himoyasi
`backend/tools/net_guard.py` qidiruv natijalaridan kelgan URL'larni ochishdan oldin
tekshiradi:

- faqat `http`/`https`, faqat 80/443 portlar
- `user:pass@` ko'rinishidagi URL'lar taqiqlanadi
- hostname DNS orqali resolve qilinadi; private, loopback, link-local, reserved va
  multicast IP'lar rad etiladi
- redirect'lar qo'lda kuzatiladi va har bir manzil qayta tekshiriladi

### API key (ixtiyoriy)
`OSINT_API_KEY` bo'sh bo'lsa API ochiq (lokal rejim). O'rnatilsa, barcha `/api/*`
so'rovlar `X-API-Key` sarlavhasini talab qiladi (`/health` ochiq qoladi).

```bash
OSINT_API_KEY=my-secret docker compose up -d --build
```

Barcha sozlamalar `.env.example` faylida hujjatlashtirilgan (nusxalab `.env` qiling).
Kalit bo'lmasa, tegishli manba o'tkazib yuboriladi (buzilmaydi).

Frontend kalitni brauzer `localStorage`'ida saqlaydi:

```js
localStorage.setItem("osint_api_key", "my-secret");
```

O'chirish: `localStorage.removeItem("osint_api_key")`.

### Rate limiting
IP bo'yicha, `slowapi` orqali (env bilan sozlanadi):

| Env | Default | Endpointlar |
|-----|---------|-------------|
| `RATE_LIMIT_HEAVY` | `4/minute` | `/api/username`, `/api/email`, `/api/phone`, `/api/image` |
| `RATE_LIMIT_LIGHT` | `15/minute` | `/api/name`, `/api/domain` |
| `RATE_LIMIT_GENERAL` | `60/minute` | `/api/catalog` |
| `RATE_LIMIT_POLL` | `120/minute` | `/api/jobs/{id}` polling |

`POST /api/jobs` `RATE_LIMIT_HEAVY` ostida.

Limitdan oshsa `429` va `X-RateLimit-*` / `Retry-After` sarlavhalari qaytadi.

### Kalitli (ixtiyoriy) manbalar
Kalit `.env`da bo'lsa ishlaydi, bo'lmasa o'sha manba o'tkazib yuboriladi:
`BRAVE_API_KEY` (Google sifatidagi qidiruv, DuckDuckGo o'rniga), `HIBP_API_KEY`,
`OPENSANCTIONS_API_KEY`, `OPENCORPORATES_API_KEY`, `SECURITYTRAILS_API_KEY`
(subdomenlar/DNS tarixi), `HUNTER_API_KEY` (exposure email'lari). To'liq ro'yxat —
`.env.example`.

### Async joblar (Redis + ARQ)
Og'ir skanlar (ayniqsa Maigret — bir necha daqiqa) HTTP so'rovni bloklamaydi.
Frontend avtomatik ravishda job API'dan foydalanadi, job queue mavjud bo'lmasa
sinxron endpointlarga qaytadi.

```bash
# 1) job yaratish
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"category":"username","query":"johndoe"}'

# 2) natijani kuzatish (queued | in_progress | complete | failed)
curl http://127.0.0.1:8000/api/jobs/<job_id>
```

Kategoriyalar: `name`, `username`, `email`, `phone`, `domain`, `image`.
`username` qidiruvi Sherlock va Maigret'dan tashqari 11 ta ochiq manbani (Telegram ochiq
sahifasi, GitHub, GitLab, Hacker News, Keybase, DEV, Bluesky, Mastodon, Docker Hub,
Lichess, Codeforces) va qidiruv indekslarini tekshiradi. Instagram, TikTok, X, Facebook, Reddit kabi
login talab qiluvchi yoki avtomatik so'rovlarni bloklaydigan platformalar to'g'ridan-to'g'ri so'ralmaydi: ular faqat indeks orqali
topiladi yoki qo'lda tekshirish havolasi sifatida ko'rsatiladi.

`name` qidiruvi ism tartibi va lotin/kirill variantlarini, yangilik, ish va ilmiy saytlarni,
Wikipedia indeksi, ORCID, OpenAlex va GitHub'ni qamrab oladi. Ism mos kelmagan natijalar olib tashlanadi.

`domain` kategoriyasi ochiq IP manzilni ham qabul qiladi (RDAP, geolokatsiya, reverse DNS,
Shodan InternetDB); bu faqat mavjud indeksni o'qiydi, nishonni skanerlamaydi.
Worker `docker compose`da alohida `worker` servisi sifatida ishlaydi
(`arq worker.WorkerSettings`), navbat va natijalar Redis'da saqlanadi.

| Env | Default | Ma'nosi |
|-----|---------|---------|
| `REDIS_URL` | `redis://redis:6379/0` | Navbat/kesh uchun Redis |
| `WORKER_MAX_JOBS` | `4` | Bir vaqtda ishlaydigan joblar |
| `WORKER_JOB_TIMEOUT` | `1200` | Job timeout (soniya) |
| `WORKER_KEEP_RESULT` | `3600` | Natijani Redis'da saqlash (soniya) |
| `CACHE_TTL_SECONDS` | `900` | Kesh TTL (soniya) |

### Kesh
`name`, `username`, `email`, `phone`, `domain`, `image` natijalari Redis'da TTL
bilan keshlanadi. Takroriy so'rovda natija `"cached": true` bilan qaytadi. Redis
mavjud bo'lmasa, jarayon ichidagi xotira keshiga fallback qiladi.

### Qo'shimcha modullar
- **Exposure** (korporativ): domen bo'yicha xavfsizlik hisoboti — SPF/DMARC/DKIM,
  HTTP xavfsizlik sarlavhalari, TLS, domen yoshi, subdomenlar. **Risk bahosi** +
  aniq tavsiyalar. Faqat o'z/ruxsat etilgan domenlar uchun.
- **Footprint** (self-OSINT): o'z email yoki username'ingiz bo'yicha barcha
  ochiq izni (ro'yxatlar, breachlar, Gravatar, profillar) bitta hisobotga jamlaydi,
  **ekspozitsiya bahosi** (low/medium/high) va moslashtirilgan **OPSEC tavsiyalari** beradi.
- **Company**: GLEIF (ochiq LEI registri) — rasmiy nom, manzil, yurisdiksiya,
  mahalliy reg-ID, LEI holati va ota-kompaniya zanjiri; **SEC EDGAR** (filing'lar);
  **GDELT** media (rate-limit bo'lishi mumkin); **OpenCorporates** (kalit bilan).
  Nom yoki LEI bo'yicha.
- **Name**: veb-qidiruv (ism tartibi + lotin/kirill transliteratsiya), ORCID,
  OpenAlex, GitHub va **Wikidata/Wikipedia** shaxs kartasi (tug'ilgan sana, kasb,
  mamlakat, ulangan ijtimoiy handle'lar → pivot). OpenSanctions sanksiya/PEP
  tekshiruvi `OPENSANCTIONS_API_KEY` bo'lsa ishlaydi.
- **Username**: Sherlock + Maigret + 14 ta ochiq API (Telegram, GitHub, GitLab,
  Chess.com, npm, Gravatar, Keybase, Mastodon, Bluesky, Docker Hub, Lichess,
  Codeforces, Hacker News, DEV) + ochiq postlar (Instagram/TikTok/... indeks,
  login'siz). Ishonch darajasi va teg qilingan `@do'stlar` pivoti.
- **Email**: Holehe, HIBP, EmailRep, MX/SPF/DMARC va **Gravatar profil** (ism,
  joylashuv, ish, ulangan tarmoqlar → pivot). Local qism ham username pivoti.
- **Phone**: numbering-plan ma'lumoti (operator, geo, liniya turi, timezone),
  ommaviy eslatmalar va WhatsApp/Viber/Telegram/Truecaller qo'lda tekshirish havolalari.
- **Domain/IP**: RDAP, DNS (A/AAAA/CNAME/MX/NS/SOA/CAA/TXT), subdomenlar
  (crt.sh + OTX + HackerTarget), TLS sertifikat, xavfsizlik sarlavhalari, urlscan,
  Wayback (+ CDX: arxivlangan/o'chirilgan URL'lar), HTTP fingerprint, IP
  geolokatsiya, reverse DNS, Shodan InternetDB, **reverse IP**, favicon hash
  (Shodan), robots.txt/security.txt/sitemap.xml va sertifikat SAN pivotlari.
  Ochiq IP ham qabul qilinadi.
- **Image**: EXIF, GPS (decimal + DMS + balandlik + kamera yo'nalishi), **quyosh
  holati** (soyalarni tekshirish uchun azimut/balandlik), xarita havolalari
  (Google/OSM/Yandex/Bing/Earth/StreetView/SunCalc), **OCR**, **dHash**, EXIF
  thumbnail va teskari rasm qidiruvi. Fayl yuklash yo'q — faqat `http(s)` URL.

### Audit log
Har bir so'rov stdout'ga JSON-lines ko'rinishida yoziladi: `request_id`, metod, yo'l,
client IP, status, davomiylik va **query SHA-256 hash** (xom PII saqlanmaydi). Javobda
`X-Request-ID` sarlavhasi qaytadi.

```bash
docker compose logs -f backend | grep '"event": "audit"'
```

## Testlar

```bash
docker compose --profile test run --rm tests
```

Testlar SSRF (private IP, redirect), API key (401) va rate limit (429)ni qamrab oladi.

## Muhim eslatma

Faqat ochiq manbalardan va **ruxsat etilgan** tekshiruvlar uchun foydalaning.
Truecaller/reverse-search kabi tashqi xizmatlar o'z ToS'iga ega.
