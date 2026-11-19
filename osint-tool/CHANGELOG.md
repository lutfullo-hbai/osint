# O'zgarishlar tarixi

Versiyalar [Semantic Versioning](https://semver.org/) bo'yicha: `MAJOR.MINOR.PATCH`.
`1.0.0` Agent rejimi haqiqiy belgilangan holatlarda baholangach (ROADMAP 6.8) qo'yiladi.
Versiya raqami bitta joyda turadi: `backend/VERSION`.

Ish tartibi: `feat/xxx → dev → stage → main`. Har bir `main` chiqarilishi teg
(`vX.Y.Z`) va GitHub Release oladi.

## [Unreleased]
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

[Unreleased]: https://github.com/lutfullo-hbai/osint/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/lutfullo-hbai/osint/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/lutfullo-hbai/osint/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/lutfullo-hbai/osint/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/lutfullo-hbai/osint/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/lutfullo-hbai/osint/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lutfullo-hbai/osint/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lutfullo-hbai/osint/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lutfullo-hbai/osint/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lutfullo-hbai/osint/releases/tag/v0.1.0
