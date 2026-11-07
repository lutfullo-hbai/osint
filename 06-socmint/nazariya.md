# 6-modul: Ijtimoiy tarmoqlar razvedkasi (SOCMINT)

## Nazariya: SOCMINT nima?
**SOCMINT** (Social Media Intelligence) — ochiq ijtimoiy tarmoq ma'lumotlarini
yig'ish va tahlil qilish. Bu "hack" emas: hamma ko'radigan profil, post, izoh va
bog'lanishlar o'rganiladi.

```
username / email / telefon
        │
        ▼
┌─────────────────────────────────────────┐
│  Profil topish → tahlil → bog'lanishlar │
│  postlar → vaqt → geolokatsiya → doira  │
└─────────────────────────────────────────┘
```

⚠️ **Birinchi qoida:** faqat ochiq ma'lumotlar, faqat qonuniy maqsad. Kuzatish,
tahdid, doxxing yoki shaxsiy hayotga aralashish — qat'iyan taqiqlanadi.

## Platformalar va ochiq ma'lumotlar

| Platforma | Ochiq nima ko'rinadi | Eslatma |
|-----------|----------------------|---------|
| Telegram | Kanal nomi, tavsif, postlar, obunachilar soni | `t.me/s/<kanal>` web-preview beradi |
| Instagram | Profil rasmi, bio, postlar (login talab qilishi mumkin) | Avtomatik scraping — cheklangan |
| X (Twitter) | Profil, postlar, follow grafigi | Login ko'pincha talab qilinadi |
| Facebook | Ommaviy sahifalar va guruhlar | Shaxsiy profil ko'pincha yopiq |
| LinkedIn | Ish joyi, ta'lim, ko'nikmalar | Ommaviy profil qismi |
| TikTok | Profil, videolar, izohlar | Dinamik sahifa, ehtiyotkorlik |
| YouTube | Kanal, videolar, izohlar, obunachilar | Google akkaunt bilan bog'liq |
| Reddit | Postlar tarixi, subredditlar | Anonim bo'lsa ham iz qoladi |
| GitHub | Repolar, email (commitlarda), jamoa | Texnik izlar uchun oltin manba |
| VK / OK | Profil, guruhlar, do'stlar | MDH hududida faol |

## Qidirish usullari

### 1. Username bo'yicha qidiruv
Bir xil username ko'p platformalarda ishlatiladi:
- **Maigret** — 3000+ sayt, hisobot chiqaradi
- **Sherlock** — tez va sodda
- **whatsmyname.app** — brauzerda, kod yozmasdan

```bash
pip install maigret
maigret username --html
```

### 2. Profil tahlili
Topilgan profilda quyidagilarni yozib oling:
- Ko'rsatilgan ism, bio, havolalar
- Profil va fon rasmlari (teskari qidiruvga yuboring)
- Ro'yxatdan o'tgan sana (ba'zi platformalarda ko'rinadi)
- Postlar chastotasi va vaqti (timezone taxmini)
- Til, imlo, emoji odatlari

### 3. Grafik tahlil (network analysis)
Bog'lanishlar graf sifatida ko'riladi:
- **Node** — profil
- **Edge** — follow, like, izoh, mention

Vositalar: Maltego (grafik), Gephi (vizualizatsiya). Kichik tadqiqotda qo'lda
jadval ham yetarli: kim kim bilan muloqotda?

### 4. Telegram xususiyatlari
- `t.me/s/kanal` — kanal postlarini login qilmasdan o'qish
- `t.me/username` — profil/kanal bor-yo'qligini tekshirish
- **tgstat.com**, **telemetr.me** — kanal statistikasi va tarixi
- Izohlar va forward'lar — kim tarqatayotganini ko'rsatadi

### 5. Vaqt va geolokatsiya
- Postlar vaqti → taxminiy vaqt zonasi
- Geotag / joy belgisi → joy
- Fon rasmlari va vitrinadagi belgilar → geolokatsiya (4-modul)
- Ob-havo va voqealar → chronolocation

### 6. Cross-platform bog'lash
Bir odamning turli akkauntlarini bog'lovchi belgilar:
- Bir xil username yoki uning varianti
- Bir xil profil rasmi (teskari qidiruv)
- Bir xil bio havolasi (Linktree, shaxsiy sayt)
- Bir xil email yoki telefon (qidiruvda)
- Bir xil postlar (repost / cross-post)

⚠️ Bitta belgi yetarli emas — kamida **2-3 mustaqil belgi** kerak.

## Vositalar va API'lar
| Vosita | Vazifasi |
|--------|----------|
| Maigret | Username bo'yicha keng qidiruv |
| Sherlock | Yengil username qidiruv |
| Instaloader | Instagram ommaviy profillari (ehtiyotkorlik bilan) |
| twscrape | X/Twitter (login talab qiladi) |
| Maltego / Gephi | Grafik tahlil |
| archive.today | O'chirilgan sahifalarni arxivlash |

⚠️ Ko'p platformalar avtomatik scrapingni **ToS'da taqiqlaydi**. API va ruxsat
bo'lsa ishlating; aks holda qo'lda brauzer usuli xavfsizroq va qonuniyroq.

## OPSEC
- Tekshiruv uchun **alohida (sock puppet) akkaunt** ishlating, asosiy akkauntni emas
- VPN/Tor orqali kirish — IP izini kamaytiradi
- Hech qachon **like, follow, izoh yoki xabar yubormang** — bu faol aralashuv
- Skrinshotlarda URL va vaqt ko'rinib tursin (dalil uchun)
- Muhim sahifalarni `archive.today` yoki Wayback'ga saqlang
- Natijalarni shaxsiy jurnalda saqlang: sana, manba, xulosa, ishonch darajasi

## Qonuniy chegaralar
- Shaxsiy ma'lumotlarni ommaga e'lon qilish (doxxing) — jinoyat bo'lishi mumkin
- Kuzatish va tahdid — taqiqlanadi
- O'zbekiston qonunchiligi va platforma qoidalariga rioya qiling
- Tadqiqot maqsadi: himoya, jurnalistika, xavfsizlik audit — emas: zarar

## Kod: `social_profile.py`
→ [kod/social_profile.py](kod/social_profile.py)

Skript nimalarni qiladi:
- Username'ni bir nechta ochiq platformada tekshiradi
- HTTP status + sahifa markerlari orqali `TOPILDI / YO'Q / NOANIQ` ajratadi
- Noto'g'ri musbat (false positive) ni kamaytirish uchun markerlardan foydalanadi
- So'rovlar orasida pauza qo'yadi (platformani bezovta qilmaslik uchun)
- `--json` bilan natijani faylga saqlaydi

O'rganadigan narsalar:
- Turli saytlarda "topilmadi" signallari turlicha bo'lishi
- Status kodiga ko'r-ko'rona ishonmaslik
- Rate limiting va odobli scraping
- Natijalarni ishonch darajasi bilan saqlash

## Mashqlar
→ [mashqlar.md](mashqlar.md)
