# O'zgarishlar tarixi

Versiyalar [Semantic Versioning](https://semver.org/) bo'yicha: `MAJOR.MINOR.PATCH`.
`1.0.0` Agent rejimi haqiqiy belgilangan holatlarda baholangach (ROADMAP 6.8) qo'yiladi.
Versiya raqami bitta joyda turadi: `backend/VERSION`.

Ish tartibi: `feat/xxx → dev → stage → main`. Har bir `main` chiqarilishi teg
(`vX.Y.Z`) va GitHub Release oladi.

## [Unreleased]

### Qo'shildi
- **heretic (alohida vosita)**: `tools/heretic/run.sh` — modelni qayta o'qitmasdan o'zgartirish
  (heretic 2.1.0, AGPL; o'z virtualenv'ida, NEXUS uni chaqirmaydi). Standart konfiguratsiya `nosyco`
  (xushomad kamayadi); Ollama'ga qo'shish yo'riqnomasi `tools/heretic/README.md`'da.

## [0.11.0] — 2026-11-21
Ixtiyoriy Globe servisi (gods-eye-view).

### Qo'shildi
- **Globe (ixtiyoriy)**: gods-eye-view — ochiq manbalar 3D globusi (samolyot, kema, sun'iy yo'ldosh,
  yong'in, Sentinel-2) alohida servis sifatida: `docker compose --profile geo up -d globe`. Aniq upstream
  commit'idan build, faqat `127.0.0.1:4173`. Servis ishlasa konsolda "Globe ↗" havolasi chiqadi.

## [0.10.0] — 2026-11-21
Aniqlik (Faza 10.1–10.3, 10.5).

### Qo'shildi
- **Aniqlikni o'lchash (10.3)**: `scripts/eval_agent.py` — javobi ma'lum holatlarda hit@1/3, MRR,
  noto'g'ri "kuchli" nomzodlar, xato chetga olingan profillar; `scripts/eval_cases_wikidata.py` —
  30 ta ochiq holat (Wikidata). Birinchi o'lchov: hit@1 87%, hit@3 93%, xato chetga olingan 0.
  Shaxsiy holatlar (`*.private.jsonl`) git'ga ham, Docker image'ga ham tushmaydi.

### Tuzatildi
- **Bir xil username, boshqa odam (10.1)**: bitta username ostida bir nechta odamning profillari
  bo'lsa, boshqa odamniki chetga olinadi va sababi bilan alohida ko'rsatiladi (UI va PDF karta).
  Faqat ishonchli belgilar bo'yicha: ism aniq boshqa (kirill/lotin imlosi va laqab bir xil ism
  hisoblanadi), tug'ilgan yil siz aytgan yoshga mos emas, yoki shahar VA ish joyi birga farq qiladi
  (kamida bittasi siz aytganiga zid). Ajratish profil tekshirilishi bilanoq, uning havolalari
  kuzatilishidan oldin bajariladi; chetga olingan profilning havolalari kuzatilmaydi.
  Tasdiqlanmagan profil bio'sidagi sayt avtomatik o'qilmaydi. Bio ichidagi "Company name:",
  "Previous location:" endi ism yoki manzil deb o'qilmaydi.
- **Ko'p so'zli joy nomlari (10.5)**: "from United States", "from San Francisco" endi ismga qo'shilib
  ketmaydi (birinchi o'lchovda Terence Tao va Ian Goodfellow shu sababli topilmagan edi).
- **"Tekshirilmadi" shovqini (10.5)**: GitLab javoblari keshlanadi (kalitsiz limit 30 holatdan 24 tasida
  tugagan); Hacker News'ga u qabul qilmaydigan username yuborilmaydi; nomzodning ro'yxatiga faqat
  profil qidiradigan manbalar kiradi (domen tekshiruvlari emas).
- **Ball o'zgaruvchanligi (10.2)**: GitHub javoblari keshlanadi (profil 24 soat, "yo'q" 1 soat;
  qisman qidiruv natijasi va o'chirish paytida kelgan javob keshlanmaydi); javob bermagan
  manbalar nomzodda "tekshirilmadi" deb yoziladi.

## [0.9.0] — 2026-11-21
O'quv kursining yakuniy moduli (Faza 9). Reja yangilandi: Faza 8b (review tuzatishlari), Faza 10 (aniqlik va 1.0.0).

### Qo'shildi
- **9-modul: yakuniy loyiha** (`09-yakuniy-loyiha/`): self-OSINT metodologiyasi, dalillarni
  hujjatlashtirish, Admiralty bahosi, 8 bosqichli loyiha va baholash mezonlari,
  hisobot va rozilik shablonlari.
- `evidence_log.py`: dalil jurnali — URL, UTC vaqt, SHA-256, nusxa va `verify`, NEXUS JSON
  eksportidan import (`retrieved_at` bilan), Markdown ilova.
- `evidence_log.py` uchun 7 ta avtomatik test; CI ularni ham ishga tushiradi.

### Tuzatildi (review 8b.11–8b.14)
- `evidence_log.py`: nusxa yo'li jurnal papkasiga nisbiy (`verify` istalgan papkadan ishlaydi);
  5 MB dan katta sahifa `truncated` deb belgilanadi; buzilgan qatorlar dasturni to'xtatmaydi;
  hisobotda URL va nomlar escape qilinadi; HTTP ulanish yopiladi.

## [0.8.1] — 2026-11-21
Xavfsizlik tuzatishlari (uchinchi review, Faza 8b).

### Xavfsizlik
- **DNS rebinding**: kalitsiz rejimda API faqat `localhost`, `127.0.0.1`, `::1` nomlariga javob beradi
  (`ALLOWED_HOSTS` bilan kengaytiriladi); "hammasini o'chirish" faqat konsol `Origin`'idan.
- **Audit log'ni to'ldirish**: mavjud bo'lmagan yo'llar yozilmaydi; rad etilgan so'rovlar bitta IP'dan
  daqiqasiga 20 tagacha, qolgani bitta yig'ma yozuvga.
- `OSINT_USERS`'da `admin`, `local`, `refused` nomlari band (admin huquqini olib qo'ymasin).

### Tuzatildi
- "Hammasini o'chirish": baza band bo'lsa ogohlantiradi; xato bo'lsa ham Redis tozalanadi;
  qidirilgan domenlarning DNS tarixi va `arq:retry` ham o'chadi; o'chirish paytida tugagan
  qidiruv natijasi saqlanmaydi; xabarda kesh muddati to'g'rilandi (24 soat).
- Noto'g'ri `AUDIT_RETENTION_DAYS` backend'ni to'xtatmaydi.

## [0.8.0] — 2026-11-19
Qonuniy va operatsion talablar (Faza 8).

### Qo'shildi
- **Manba vaqti (8.1)**: har bir natijada `retrieved_at`; keshdan kelgan javob asl vaqtni saqlaydi;
  Agent maydon manbalari, PDF karta, Markdown hisobot va case topilmalarida ko'rinadi.
- **To'liq o'chirish (8.2)**: Agent run'ni o'chirish; `DELETE /api/data` — case, topilma, watch,
  Agent run, Redis kesh va job natijalari; `secure_delete` va `VACUUM`.
- **Audit log (8.3)**: kim, qachon, nima — lokal SQLite, Data tabida ko'rish va filtr,
  `AUDIT_RETENTION_DAYS`, `AUDIT_LOG_QUERIES=0` (faqat hash).
- **Kirish (8.4)**: nomli kalitlar `OSINT_USERS`, admin huquqlari, `hmac.compare_digest`;
  kalitsiz rejimda ommaviy IP'dan so'rov 403 (`ALLOW_OPEN_ACCESS=1` bilan ochiladi);
  qisqa kalit haqida ogohlantirish. Yangi **Data** tabi: kalit, Agent run'lar, audit, o'chirish.
- **Foydalanish shartlari (8.5)** README'da.

## [0.7.1] — 2026-11-19
Faza 7 sinovi tuzatishlari.

### Tuzatildi
- Contacts: `file:`, `ftp:`, `javascript:` manzillariga aniq xabar; App Store va ulashish havolalari "website" emas.
- Contacts tabi: natija kartasi to'liq kenglikda, har bir manba sahifa yo'li bilan ("/contact").
- So'rov cheklovi (429) xabari UI'da ko'rinadi; fayl nomi "_" bilan boshlanmaydi.
- Contacts: `#` bilan tugagan havolalar (`/contact#form`) endi o'qiladi; robots.txt 401/403 qaytarsa
  sayt o'qilmaydi; `mycdn.uz` kabi saytlar CDN deb tashlab yuborilmaydi.
- Graf eksporti: noto'g'ri tuzilgan `scan` (kalitsiz tugun, ro'yxat o'rniga matn) 500 xato emas, 200 beradi.

## [0.7.0] — 2026-11-19
Shaxs kartasi va yangi manbalar (Faza 7).

### Qo'shildi
- **Shaxs kartasi (7.1)**: Agent nomzodi uchun PDF — manbali maydonlar, kontaktlar, dalillar zanjiri, qaroringiz.
- **Kontakt ajratuvchi (7.2, 7.7)**: profil matni va shaxsiy saytdan email, telefon, profil havolalari;
  yangi Contacts tab (istalgan sahifa URL'i).
- **orginfo.uz (7.4)**: ism bo'yicha rahbar/ta'sischi bo'lgan kompaniyalar, kompaniya bo'yicha rahbar va ta'sischilar.
- Ism qidiruvida hujjat dork'lari (PDF/Word/Excel) va qo'lda tekshirish havolalari (public.sud.uz,
  data.egov.uz, orginfo.uz); emailda Epieos havolasi (7.3, 7.5).
- Agent'da ish joyi va o'qish joyi; "Narrow down" maydonlari (7.6).
- Graf eksporti: GraphML va Maltego CSV (7.8).

### Tuzatildi
- Agent parseri "Samarqanddan" kabi qo'sh harfli shahar nomlarini tanimas edi.

## [0.6.0] — 2026-11-19
Agent rejimi (Faza 6).

### Qo'shildi
- **Agent rejimi (Faza 6)**: erkin matn ("lutfullo abdubaniyev 19 yosh namangandan") → jonli
  qadamlar → manbali nomzodlar; yosh va shahar saralashda; "Confirm / Reject" qarori insonda.
- Pivot filtri (5.4): ma'lumoti tavsifga zid namesake'lar kengaytirilmaydi.
- Username soxta natija filtri: kunlik canary; holati Sources panelida.

### Tuzatildi
- Sherlock 42 ta saytda istalgan username'ni "found" derdi — endi e'tiborsiz qoldiriladi.

## [0.5.1] — 2026-11-19
### Qo'shildi
- Versiyalash: `backend/VERSION`, shu CHANGELOG, eski bosqichlarga orqaga qarab teglar.
- GitHub Actions CI: har push va PR'da Docker testlari va frontend sintaksis tekshiruvi.
- `dev` va `stage` branchlari; `main` himoyalangan (CI o'tmasa merge yo'q).

### O'zgardi
- API ko'rsatadigan versiya endi `backend/VERSION`'dan olinadi (avval qo'lda yozilgan `1.0.0` edi).

## [0.5.0] — 2026-11-18
To'liq bepul ishlash, yangi bepul manbalar, rasm geolokatsiyasi, lokal AI.

### Qo'shildi
- Bepul sanksiya/PEP indeksi: BMT, OFAC, EI, Buyuk Britaniya ro'yxatlari (OpenSanctions API o'rniga).
- Rasm geolokatsiyasi: EXIF, OCR, GeoCLIP, lokal vision model, xaritada natija.
- O'zbekiston rasmiy reyestrlari (data.egov.uz, 19 to'plam) kompaniya va ism qidiruvida.
- openinfo.uz: kompaniya rahbariyati rasmiy oshkor qilingan ma'lumotdan.
- DNS tarixi (o'z kuzatuvlari + Mnemonic + Robtex), SecurityTrails o'rniga.
- E'lon qilingan emaillar (security.txt, DMARC, sayt sahifalari), Hunter o'rniga.
- Breach natijalari HIBP'ning bepul katalogi bilan boyitildi.
- Server tomonidagi lokal AI qatlami: dalilga asoslangan, uydirmasiz, faqat zaif signal.

### O'zgardi
- Pullik kalitlar ixtiyoriy; kalit bo'lmasa manba jim o'tkazib yuboriladi.
- SearXNG qidiruv tizimlari aniq yoqildi, natijalar keshlanadi, tizimlar holati ko'rsatiladi.
- Kompaniya qidiruvi tezroq: sho'ba kompaniyalar, Companies House.

### Tuzatildi
- Ikkinchi code review topilmalari (B1–B3, M1–M6): uzun so'rovda xotira tugashi,
  jim "toza" sanksiya javobi, katta javoblar, rasm "decompression bomb", Ollama proxy ochiqligi va boshqalar.

## [0.4.0] — 2026-11-16
Yangi ROADMAP bo'yicha Faza 1–4.

### Qo'shildi
- Faza 1: Deep Scan sifati.
- Faza 2: ehtimoliy bog'lash (Fellegi–Sunter uslubida ball).
- Faza 3: yangi manbalar va qamrov.
- Faza 4 (poydevor): Holehe jarayon ichida, xavfsiz modullar ro'yxati bilan.
- XposedOrNot: kalitsiz breach tekshiruvi.

### Tuzatildi
- Faza 1b: review tuzatishlari.
- Telefon natijasida tekshirilmagan havolalar aniq belgilandi.
- Tez tuzatishlar: CORS, watch keshi, dossier nomi.

## [0.3.0] — 2026-11-09
### Qo'shildi
- Monitoring (Watch): jadval bo'yicha qayta skan va o'zgarishlarni aniqlash.

## [0.2.0] — 2026-11-09
### Qo'shildi
- Case (tergov) boshqaruvi.
- Deep Scan: pivotlarni avtomatik kuzatish.
- Korrelatsiya dvigateli (identity clusters).
- PDF dossier (Unicode shrift bilan).

### Tuzatildi
- Korrelatsiyada handle shovqini (stoplist va chastota chegarasi).

## [0.1.0] — 2026-11-07
Birinchi to'liq to'plam.

### Qo'shildi
- Username, email, telefon, ism qidiruvlari (Sherlock, Maigret, Holehe va boshqalar).
- Kompaniya: SEC EDGAR, GDELT, OpenCorporates; Corporate Exposure Scanner.
- Domen: Wayback CDX, favicon hash, robots/security.txt, SAN pivotlari.
- Digital Footprint hisoboti, entity graph, PDF eksport.
- Lokal Qwen (Ollama) orqali AI xulosa va rasm tahlili.

[Unreleased]: https://github.com/lutfullo-hbai/osint/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/lutfullo-hbai/osint/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/lutfullo-hbai/osint/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/lutfullo-hbai/osint/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/lutfullo-hbai/osint/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/lutfullo-hbai/osint/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/lutfullo-hbai/osint/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/lutfullo-hbai/osint/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/lutfullo-hbai/osint/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/lutfullo-hbai/osint/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/lutfullo-hbai/osint/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lutfullo-hbai/osint/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lutfullo-hbai/osint/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lutfullo-hbai/osint/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lutfullo-hbai/osint/releases/tag/v0.1.0
