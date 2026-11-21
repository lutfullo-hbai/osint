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

## Watch (jadval bo'yicha kuzatuv)

Bir martalik snapshot o'rniga **uzluksiz kuzatuv**:
- **Watch** bo'limida nishonni (domain/username/email/...) interval bilan kuzatuvga qo'yasiz
- ARQ worker har sikl mavjud public-manba tekshiruvini qayta chaqiradi va natijani oldingisi bilan **solishtiradi**; o'zgarish (yangi profil/subdomain, yo'qolgan narsa) **change event** sifatida yoziladi
- Har watch'da "Run now", pauza/davom, tarix (o'zgarishlar jurnali), o'chirish
- Yangi manba yo'q, saqlangan parol yo'q — faqat public sirtni jadval bo'yicha yangilaydi

Kuzatuv tezligi `WATCH_POLL_MINUTES` (default 5 daqiqa) bilan sozlanadi.

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

### Kirish (API kalit) — ROADMAP 8.4
- **Kalit yo'q** (standart): API faqat shu kompyuter va lokal tarmoqdan (127.0.0.1,
  10.x, 172.16–31.x, 192.168.x) javob beradi. Ommaviy IP'dan kelgan so'rov **403**
  oladi. Ataylab ochish uchun `ALLOW_OPEN_ACCESS=1` qo'ying (tavsiya etilmaydi).
- **`OSINT_API_KEY`**: barcha `/api/*` so'rovlar `X-API-Key` sarlavhasini talab qiladi
  (`/health` ochiq). Bu kalit egasi — `admin`.
- **`OSINT_USERS=alice:<kalit>,bob:<kalit>`**: nomli kalitlar, audit log'da "kim"
  ko'rinadi. Audit log'ni o'qish va hammasini o'chirish faqat `admin`'ga ruxsat.

```bash
OSINT_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))") docker compose up -d --build
```

Kalit kamida 16 belgi bo'lsin (qisqa bo'lsa ishga tushishda ogohlantirish chiqadi).
`admin`, `local` va `refused` nomlari band: `OSINT_USERS`'da ular e'tiborga olinmaydi.

**DNS rebinding himoyasi:** kalitsiz rejimda API faqat `localhost`, `127.0.0.1` va `::1`
nomlari bilan kelgan so'rovlarga javob beradi; boshqa `Host` → 400. Shunday qilib siz
ochgan begona sayt o'z domenini 127.0.0.1 ga yo'naltirib API'ni chaqira olmaydi.
API'ni domen nomi bilan ishlatsangiz, `ALLOWED_HOSTS=osint.example.org` qo'ying.
Kalitsiz rejimda "hammasini o'chirish" faqat konsol manzilidan (`ALLOWED_ORIGINS`) ishlaydi.
Teskari proksi (nginx, Caddy) orqasida tarmoqqa ochsangiz, **albatta** kalit qo'ying:
proksi orqali kelgan so'rov lokal ko'rinadi.

Frontend'da kalit **Data** tabida kiritiladi va faqat shu brauzerda saqlanadi.
Barcha sozlamalar `.env.example` faylida (nusxalab `.env` qiling).

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

### Veb-qidiruv va passiv manbalar (kalitsiz)
- **SearXNG** (`searxng` konteyneri, faqat ichki tarmoqda): bitta so'rov bir nechta qidiruv
  tizimiga tarqaladi (`searxng/settings.yml` → `engines`). Bloklagan tizimni SearXNG o'zi
  vaqtincha to'xtatadi, qolganlari javob beradi; bloklarni aylanib o'tmaymiz. Holati IP'ga
  bog'liq — 2026-11-18 da bu serverdan Brave, Bing va Google CSE ishlagan, Google, Startpage,
  Mojeek, Qwant, DuckDuckGo esa bloklagan. Tartib: Brave API (kalit bo'lsa) → SearXNG →
  DuckDuckGo. Bittasi bloklasa keyingisi ishlaydi. `.env`da `SEARXNG_SECRET` o'rnating.
- **Subfinder** (image ichida): passiv subdomain qidiruvi, crt.sh/OTX/HackerTarget bilan birga.
- **Domen email'lari**: tashkilot ochiq e'lon qilgan manzillar, har biri topilgan sahifasi bilan
  (taxmin qilinmaydi; gmail.com kabi umumiy domenlarda o'chiq).
- **Maigret bazasi**: `/app/data/maigret_db.json` — o'zbek saytlari skanerga kiritilgan, har
  dushanba 04:30 UTC `--self-check --auto-disable` ishlamay qolgan saytlarni o'chiradi.
  Qo'shimcha sayt ta'riflari: `backend/assets/maigret_extra_sites.json`.
- **Wayback**: kuchli topilgan profillarning birinchi arxivlangan sanasi.
- **Manbalar holati**: `GET /api/sources/health` va sarlavhadagi `[SOURCES ...]` belgisi
  (ustiga olib borilsa tafsilotlar).

### Rasm geolokatsiyasi (Geolocate tabi)
Rasm yuklanadi → server EXIF GPS, OCR (eng/rus/uzb/uzb_cyrl) va GeoCLIP (`geoclip`
konteyneri, CPU) natijalarini beradi → brauzer lokal vizual modelni (`ollama pull
qwen2.5vl:7b`) ishga tushirib joy nomlari va belgilarni oladi → server ularni
OpenStreetMap'da topib, barcha manbalarni birlashtiradi va xaritada nomzodlarni
ishonch doirasi va dalillari bilan ko'rsatadi. Birinchi ishga tushishda GeoCLIP
CLIP modelini (~1.7 GB) yuklab oladi. Faqat joy aniqlanadi, odam emas.
Eslatma: xarita fonlari `tile.openstreetmap.org`'dan yuklanadi — ko'rilayotgan hudud
(ya'ni tergov qilinayotgan joy) OSM serverlariga ma'lum bo'ladi.

### Globe (ixtiyoriy, gods-eye-view)
[gods-eye-view](https://github.com/bilawalsidhu/gods-eye-view) (kodi MIT) ochiq manbalarni 3D
globusda ko'rsatadi: samolyotlar, kemalar, sun'iy yo'ldoshlar, yong'inlar, Sentinel-2 suratlari, yangiliklar.
Rasmdagi samolyot/kemani tekshirish yoki hududni "oldin/keyin" solishtirish uchun foydali.
Odam qidirmaydi va NEXUS backend'iga ulanmaydi: alohida servis.

    docker compose --profile geo up -d --build globe      # http://localhost:4173

- Servis ishlayotgan bo'lsa, konsolda **Globe ↗** havolasi chiqadi (aks holda yashirin).
- Upstream'ning aniq commit'idan build qilinadi; yangilash — `docker-compose.yml`'dagi
  commit'ni ko'rib chiqib almashtirish.
- Faqat `127.0.0.1`'da ochiladi: unga kiritilgan provayder kalitlarini u o'zi orqali uzatadi,
  shuning uchun portni tarmoqqa ochmang.
- Kalitsiz qatlamlar yetarli. Pulli kalitlar (Google Maps, OpenAI) kerak emas.
- Har bir qatlam ma'lumotining o'z shartlari bor (ba'zilari faqat notijorat, masalan
  OpenSky): upstream `DATA_SOURCES.md`. Ochiq kamera qatlamlari (CCTV, ALPR) bilan
  ishlaganda maxfiylikni hurmat qiling.
- Ko'rilgan hududlar tashqi provayderlarga (OSM, OpenSky va boshqalar) ma'lum bo'ladi.

### Lokal AI (server tomonda)
Ollama kompyuterda faqat `127.0.0.1`da tinglaydi; `ollama-proxy` konteyneri (socat,
host tarmog'ida) uni faqat compose tarmog'i shlyuziga (`172.20.0.1:11435`) uzatadi —
Ollama LAN'ga ochilmaydi, tizim sozlamasi o'zgarmaydi. AI: Deep Scan nomzodlariga
dalilga asoslangan "zaif ikkinchi fikr" (hech qachon birlashtirmaydi), rasm
geolokatsiyasining vizual bosqichi. Javobdagi email/telefon/URL dalilda bo'lmasa
o'chiriladi. Ollama ishlamasa hammasi AI'siz ishlaydi (`AI_REVIEW=0` bilan o'chiriladi).

### Pul talab qilmaydi
Tool to'liq bepul ishlashi uchun qurilgan. Tavsiya etiladigan bepul sozlamalar:
`GITHUB_TOKEN` (bepul; GitHub limiti soatiga 60 → 5000) va `SEARXNG_SECRET`.

Pullik yoki cheklangan kalitlar (`HIBP_API_KEY`, `BRAVE_API_KEY`,
`SECURITYTRAILS_API_KEY`, `HUNTER_API_KEY`, `OPENCORPORATES_API_KEY`,
`OPENSANCTIONS_API_KEY`) shart emas: bo'sh bo'lsa o'sha manba jimgina o'tkazib
yuboriladi, uning ishini bepul manba bajaradi (XposedOrNot, SearXNG, Subfinder,
"Published emails", GLEIF/SEC EDGAR). Hozircha bepul o'rnini bosuvchisi yo'q
yagona narsa — sanksiya/PEP tekshiruvi. To'liq ro'yxat — `.env.example`.

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
- **Email**: Holehe, breach tekshiruvi (`HIBP_API_KEY` bo'lsa HIBP, bo'lmasa
  bepul **XposedOrNot**), EmailRep, MX/SPF/DMARC va **Gravatar profil** (ism,
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

### Audit log — ROADMAP 8.3
Har bir qidiruv, saqlash, o'chirish va yuklab olish (PDF, graf) lokal SQLite'ga
yoziladi: **kim** (kalit nomi yoki `local`), **qachon** (UTC), **nima** (yo'l,
kategoriya, qidirilgan matn), client IP va status. Rad etilgan so'rovlar ham
(`refused`, 401/403) yoziladi, lekin bitta IP'dan daqiqasiga 20 tagacha; qolgani bitta
"yana N ta rad etildi" yozuviga yig'iladi. Mavjud bo'lmagan yo'llarga so'rovlar yozilmaydi. Ko'rish: **Data** tabi yoki `GET /api/audit` (admin).

- `AUDIT_RETENTION_DAYS=90` — eski yozuvlar avtomatik o'chiriladi
- `AUDIT_LOG_QUERIES=0` — qidirilgan matn o'rniga faqat uning SHA-256 hash'i saqlanadi

Bundan tashqari har bir so'rov stdout'ga JSON-lines bo'lib chiqadi (u yerda faqat
query hash, xom matn yo'q) va javobda `X-Request-ID` qaytadi:

```bash
docker compose logs -f backend | grep '"event": "audit"'
```

### Manba va vaqt — ROADMAP 8.1
Har bir natija o'z manbasini (`platform`, `url`) va **olingan vaqtini**
(`retrieved_at`, UTC) olib yuradi. Keshdan qaytgan javob asl so'rov vaqtini saqlaydi.
Agent nomzodining har bir maydoni, shaxs kartasi (PDF) va case'ga saqlangan
topilmalar ham shu vaqtni ko'rsatadi.

### To'liq o'chirish — ROADMAP 8.2
- Case: **Cases** tabida; Agent run (qadamlar, nomzodlar, qarorlar bilan):
  **Data** tabida yoki `DELETE /api/agent/{id}`
- **Hammasi**: **Data** tabida "DELETE ALL" deb yozib, yoki
  `DELETE /api/data {"confirm": "DELETE ALL", "include_audit": false}` (admin).
  O'chiriladi: case'lar, topilmalar, watch'lar, Agent run'lar, Redis'dagi kesh va job
  natijalari, qidirilgan domenlarning DNS tarixi. `secure_delete` + `VACUUM` bilan diskda
  nusxa qolmaydi. Baza shu payt band bo'lsa (fonda qidiruv ishlayotgan bo'lsa), javobda
  ogohlantirish chiqadi — keyinroq qayta bosing. O'chirish paytida tugagan qidiruv
  natijasi keshga va job natijasiga yozilmaydi. Ochiq ma'lumotlar to'plamlari
  (sanksiyalar, reyestrlar) shaxsiy ma'lumot emas va qoladi.
  Audit log faqat `include_audit: true` bo'lsa o'chadi (unda qidirilgan matnlar bor,
  agar `AUDIT_LOG_QUERIES=0` bo'lmasa); o'chirish so'rovining o'zi audit'ga yoziladi.

## Agent aniqligini o'lchash (ROADMAP 10.3)

Javobi oldindan ma'lum holatlar bo'yicha: to'g'ri profil nechanchi nomzodda chiqdi (hit@1,
hit@3, MRR), qanday darajada (kuchli/mumkin/zaif), nechta "kuchli" nomzod noto'g'ri, to'g'ri
profil "boshqa odam" deb chetga olindimi, qaysi manbalar javob bermadi.

```bash
# ochiq jamoat shaxslari (Wikidata: GitHub username, tug'ilgan yil, yashash joyi)
docker compose exec backend python scripts/eval_cases_wikidata.py > backend/eval/agent_cases.public.jsonl
# o'lchash: har bir holat ~1–2 daqiqa; GITHUB_TOKEN bo'lmasa soatiga ~6 holat
docker compose exec backend python scripts/eval_agent.py eval/agent_cases.public.jsonl --out /tmp/report
```

Holat formati (`*.jsonl`, har qatorda bitta):
`{"id": "...", "text": "Ism Familiya, 30 years old, from Toshkent", "expect": ["https://github.com/..."], "source": "...", "kind": "public|consented"}`.
Oddiy odamlar haqidagi holatlar **faqat o'zlarining roziligi bilan** va `*.private.jsonl`
faylida (git'ga ham, Docker image'ga ham tushmaydi).

## Testlar

```bash
docker compose --profile test run --rm tests
```

Testlar SSRF (private IP, redirect), API key (401) va rate limit (429)ni qamrab oladi.

## Foydalanish shartlari — ROADMAP 8.5

Bu vosita ochiq manbalardagi ma'lumotni **qonuniy maqsadda** tekshirish uchun.
Foydalanish orqali quyidagilarga rozilik bildirasiz.

**Ruxsat etilgan maqsadlar**
- O'zingizni himoya qilish: o'z raqamli izingizni, sizib chiqqan ma'lumotlaringizni,
  sizning nomingizdan ochilgan soxta profillarni tekshirish
- Firibgarlik va ijtimoiy muhandislikdan himoya: kontragent, ish beruvchi, sotuvchi
  yoki tanishuv ilovasidagi shaxsni ochiq manbalar bo'yicha tekshirish
- Kompaniya xavfsizligi va due diligence, ruxsat etilgan pentest va red team
- Jurnalistik tadqiqot, akademik tadqiqot, yo'qolgan odamni qidirish (vakolatli
  tashkilotlar bilan hamkorlikda)

**Taqiqlanadi**
- **Doxxing**: shaxsning manzili, telefoni, oilasi va shunga o'xshash ma'lumotlarini
  uni qo'rqitish, sharmanda qilish yoki unga zarar yetkazish uchun yig'ish yoki tarqatish
- Ta'qib qilish (stalking), kuzatish, tahdid, shantaj, kamsitish
- Sobiq yoki hozirgi sherigingizni, qo'shningizni yoki boshqa shaxsni uning
  roziligisiz kuzatish
- Yig'ilgan ma'lumotni sotish yoki ma'lumotlar bazasiga to'plash
- Sizib chiqqan bazalar, "probiv" xizmatlari yoki login/parol talab qiladigan
  manbalar bilan birlashtirish (vosita ularni ataylab ishlatmaydi)

**Sizning javobgarligingiz**
- Natija — **nomzodlar ro'yxati**, identifikatsiya emas. Har bir qiymat manba
  havolasi bilan beriladi; undan foydalanishdan oldin manbani o'zingiz tekshiring.
  Yakuniy qaror sizda.
- Shaxsga doir ma'lumotlar bilan ishlaganda o'z mamlakatingiz qonunlariga amal
  qiling (O'zbekistonda: "Shaxsga doir ma'lumotlar to'g'risida"gi Qonun, ZRU-547;
  Yevropada: GDPR). Ma'lumotni maqsadga kerakli muddatdan ortiq saqlamang:
  keraksiz case va run'larni o'chiring (8.2).
- Tashqi xizmatlar (Truecaller, qidiruv tizimlari, saytlar) o'z foydalanish
  shartlariga ega; vosita robots.txt va so'rov chegaralariga amal qiladi.
- Bu bo'lim yuridik maslahat emas. Shubha bo'lsa, huquqshunos bilan maslahatlashing.

Vositani tarmoqqa ochgan bo'lsangiz, kirishni kalit bilan cheklang (8.4) va audit
log'ni (8.3) kuzatib boring: kim nimani qidirganini bilish suiiste'molning oldini oladi.

## Versiya va ish tartibi

- Joriy versiya: `backend/VERSION`; o'zgarishlar: [CHANGELOG.md](CHANGELOG.md).
- Branchlar: `feat/xxx → dev → stage → main`.
  - `dev`: kundalik ishlar yig'iladi;
  - `stage`: chiqarishdan oldin to'liq tekshiruv (Docker testlari + jonli sinov);
  - `main`: faqat tekshirilgan, barqaror versiya (himoyalangan, `stage`'dan PR orqali).
- Har bir `main` chiqarilishi `vX.Y.Z` tegi va GitHub Release oladi. CI (GitHub Actions) har push'da testlarni ishlatadi.
