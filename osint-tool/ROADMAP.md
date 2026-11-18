# NEXUS OSINT — Roadmap

Holat va to'liq reja (2026-11-16). Manba: o'zimizning sinovlar, reviewer va researcher hisobotlari.
Bajarilganlari `[x]`, qisman bajarilganlari `[~]` bilan belgilanadi. Hajm: S = kichik (≤ yarim kun),
M = o'rta (1–2 kun), L = katta (3+ kun).

Ish tartibi: Faza 1b → 2 → 3 → 4 → 5 → 6 → 7. Har bir faza alohida branch'da bajariladi:
testlar o'tadi, keyin commit va main'ga merge.

---

## Faza 0 — boshlangan ishni yakunlash ✅
- [x] Tez tuzatishlar: CORS PATCH/DELETE, watch keshni chetlab o'tadi, dossier case nomi
- [x] Kalitsiz breach tekshiruvi (XposedOrNot; HIBP kaliti bo'lsa HIBP)
- [x] Telefon: qo'lda tekshirish havolalari "checked: false", `found_online`

## Faza 1 — Deep Scan sifati ✅ (1.1–1.4)
- [x] 1.1 Pivot o'zini "shared handle" dalili qilmaydi; ishonch eng zaif a'zo bo'yicha
- [x] 1.2 "Display name mos" akkauntlar faqat nomzod (`candidates`), birlashtirilmaydi
- [x] 1.3 Postdagi `@tag` handle'lar Deep Scan'da kuzatilmaydi
- [x] 1.4 Ixtiyoriy `GITHUB_TOKEN` (faqat api.github.com'ga yuboriladi)

---

## Faza 1b — Review tuzatishlari ✅

Correlation va xavfsizlik:
- [x] R1 **Critical.** Wikidata: pivot faqat eng mos entity'dan olinadi, u inson bo'lishi (P31=Q5)
      va label so'rovga mos kelishi shart. Qolgan entity'lar faqat nomzod (`entity_intel.py:20`) — S
- [x] R2 Umumiy domenlar (linkedin.com, github.io, linktr.ee, …) denylist; profil URL'idagi sayt
      domen pivot'iga aylanmaydi — S
- [x] R3 `_HANDLE_URL_RE`: host chegarasi qat'iy (`budget.me` ≠ `t.me`), tizim yo'llari stoplist'da
      (`/title/`, `/topics/`, `/orgs/`, …) — S
- [x] R4 Email local-part ikki marta hisoblanmaydi (alohida bucket); `nodes_from_findings`
      pivot provenance'ni (`via`) saqlaydi — S
- [x] R6 CLI argument injection: Sherlock/Maigret/Holehe'ga `--` separator, `-` bilan
      boshlanuvchi qiymat rad etiladi — S
- [x] R9 Qidiruv natijalaridagi handle'lar korrelatsiyada faqat zaif signal — S
- [x] R10 SSRF: DNS bir marta resolve qilinadi va ulanish aynan o'sha IP'ga (rebinding yopiladi) — M
- [x] R11 Resurs chegaralari: watch soni (100), `/api/correlate` (200 node), in-memory kesh (1000)
- [ ] R12 Rasm yuklashda hajm chegarasi stream paytida; watch signature 300 ta cheklovi — S

Kesh va watch:
- [x] R8 Qisman natija (biror manba yiqilgan) keshlanmaydi yoki qisqa TTL (60 s) — S
- [x] R5 Watch signature `info` dagi muhim o'zgarishlarni ko'radi (yangi breach, subdomain);
      DDG natijalaridagi tasodifiy o'zgarishlar hisobga olinmaydi — M
- [x] R7 Watch cron'lari ustma-ust ishlamaydi (Redis lease/lock) — S
- [x] 1.10 Manba vaqtincha yiqilsa uning natijalari "removed" deb yozilmaydi — S

Qolganlar:
- [x] 1.6 Sherlock `exit 1` — sababi: har ishga tushganda sayt ro'yxatini GitHub'dan yuklardi;
      endi `--local`. Deep Scan'da og'ir tekshiruvlar bir vaqtda ≤ 3 (ConnectError to'lqini yo'qoldi)
- [x] 1.9 Truecaller: tarmoqdan ulanib bo'lmasa timeout bilan o'chadi — S
- [x] 1.11 Frontend: case nomini escape qilish, `API_BASE` sozlanadigan — S

Har bir band uchun regressiya testi (Michael Jordan namesake, netflix/budget.me URL'lari,
`--web` username, qisman natija keshi, watch'da yangi breach).

---

## Faza 2 — Bog'lash aniqligi (ehtimoliy model) ✅
- [x] 2.1 Fellegi–Sunter uslubidagi vaznlar: har bir belgi uchun log(m/u). Keng tarqalgan ism,
      qisqa yoki umumiy handle → kichik vazn; noyob handle, bir xil avatar, aniq email → katta vazn
- [x] 2.2 Qoida: birlashtirish uchun ≥1 kuchli yoki ≥2 mustaqil o'rtacha dalil; faqat ism — hech qachon
- [x] 2.3 Ziddiyatlar vazni kamaytiradi (boshqa shahar, boshqa yosh, boshqa ish joyi)
- [x] 2.4 Ism variantlari: o'zbek lotin ↔ kirill (o‘/ў, g‘/ғ, sh/ш, ch/ч), ruscha transliteratsiya
      (-ov/-ev/-yev, -ova), apostrof shakllari (o' o‘ oʻ), ajratgichlar (`.`, `_`, `-`, yo'q)
- [x] 2.5 Username variant generatori (ism.familiya, ismfamiliya, i.familiya, tug'ilgan yil) —
      faqat qidiruv uchun, natija nomzod sifatida
- [x] 2.6 Etalon to'plam: 20–30 ta qo'lda belgilangan holat (o'zimiz, ochiq jamoat shaxslari,
      namesake'lar). Har bir o'zgarishda precision/recall o'lchanadi
      (`backend/scripts/eval_linkage.py`; 28 holat, hozir P=1.00 R=1.00)
- [ ] 2.7 Etalonga real, qo'lda belgilangan holatlar qo'shish (o'z scan'larimizdan). Hozirgi
      28 ta holatni men yozganman va vaznlar ularga qarab sozlangan — bu regressiya himoyasi,
      mustaqil aniqlik o'lchovi emas

## Faza 3 — Manbalar va qamrov ✅ (3.9 keyinroq)
- [x] 3.1 (eski 1.5) O'z SearXNG instansiyasi (docker-compose'ga, `formats: [html, json]`);
      zaxira: Mojeek yoki Brave API (kalit bo'lsa). DDG oxirgi zaxira
- [x] 3.2 Sherlock va Maigret'ni yangilash; Maigret `--self-check --auto-disable` haftalik
- [~] 3.3 Maigret uchun o'zbek va rus saytlari ta'riflari: OLX.uz, hh.uz, Uzum, Kun.uz/Daryo
      (muallif sahifalari), VK, OK.ru, Habr, Yandex Zen, Pikabu va boshq. — ochiq profil sahifasi bo'yicha
      Bajarildi: o'z bazamiz, o'zbek saytlari skanerga kiritildi (MDH saytlari allaqachon top-500da).
      Qoldi: yangi o'zbek saytlari ta'riflari — har biri uchun mavjud username bilan jonli sinov
      kerak; OLX.uz/hh.uz/Uzum profillari username emas ID bo'yicha, username qidiruviga mos emas
- [x] 3.4 Wayback Machine: topilgan profillarning birinchi arxivlangan sanasi, eski bio
- [x] 3.5 Manbalar salomatligi paneli: Holehe modullari, GitHub limiti, qidiruv holati, Maigret
      o'chirilgan saytlar soni
- [x] 3.6 **Subfinder** (ProjectDiscovery, MIT, v2.17.0 2026-10): passiv subdomain qidiruvi.
      Docker image'ga binary, kalitsiz manbalar standart, kalitlar ixtiyoriy. Hozirgi crt.sh / OTX /
      HackerTarget / SecurityTrails yonida ishlaydi, natijalar birlashtiriladi. Avval 10 ta domenda
      hozirgi usul bilan solishtiriladi (soni, vaqti) — M
- [x] 3.7 **theHarvester** → o'zimizning "Published emails" (theHarvester Python 3.14 +
      Playwright talab qiladi, image'ga sig'maydi; uning kalitsiz qidiruv qismi SearXNG orqali) (GPL-2.0, 4.11.1 2026-06): domen → tashkilotning ochiq e'lon qilingan
      email va host'lari. Faqat kalitsiz/bepul manbalar, CLI sifatida (subprocess, `--`).
      Har bir email manbasi bilan; hunter.io'ning bepul o'rnini bosadi — M
- [x] 3.8 Katalog yangilash: WhatsMyName "arxivlangan" deb belgilanadi; Subfinder, theHarvester,
      Amass, SpiderFoot, Social-Analyzer, Photon havolalari qo'shiladi — S
- [ ] 3.9 (keyinroq, 3.3'dan keyin baholanadi) **Social-Analyzer** (AGPL-3.0, faol): 1000+ sayt,
      0–100 ishonch bahosi. Uchinchi username dvigateli sifatida faqat Maigret o'zbek ta'riflari
      yetarli bo'lmasa; AGPL — alohida konteyner, kodini o'zimizga aralashtirmaymiz

## Faza 3b — Pullik API'lar o'rniga bepul yechimlar (researcher hisoboti, 2026-11-18)
- [x] 3b.1 Sanksiya/PEP indeksi (OpenSanctions o'rniga): UN, OFAC SDN, EU FSF, UK Sanctions List
      (OFSI 2026-01-28 da yopilgan) → SQLite FTS5, lotin/kirill moslash, tug'ilgan yil veto,
      "keng tarqalgan ism" belgisi; kunlik yangilash (sha256 bo'yicha faqat o'zgarganini).
      PEP: Wikidata P39 (UZ, KZ, KG, TJ, TM) haftalik, WDQS → QLever zaxira.
      Natija hech qachon "sanksiyada" demaydi — "ro'yxatdagi yozuvga o'xshaydi" + manba
- [x] 3b.2 SearXNG: har bir so'rov 24 soat keshlanadi (qisman javob 2 soat; tizimlar bloklagan
      paytdagi bo'sh javob keshlanmaydi); har bir qidiruv tizimining ok/xato statistikasi holat
      panelida
- [ ] 3b.3 O'z passive DNS jadvalimiz + Mnemonic PDNS (1000/kun) + Robtex (10/soat) — S/M
- [ ] 3b.4 E'lon qilingan emaillar: security.txt, DMARC rua/ruf, SOA RNAME; keyin odobli
      kontakt-sahifa crawler (robots.txt, ≤20 sahifa, taxminsiz) — M
- [x] 3b.5a O'zbek rasmiy reyestrlari (data.egov.uz, 19 dataset: soliq, QQS, nohalol yetkazib
      beruvchilar, birja, NNT, diniy, notariuslar, yuridik maslahat, hakamlik, ekstremistik
      tashkilotlar, davlat korxonalari, kuzatuv kengashlari, DXSh) → SQLite FTS5; kompaniya
      qidiruvi STIR yoki nom bo'yicha (lotin/kirill, huquqiy shakl so'zlarisiz), ism qidiruvida
      reyestrda lavozimi bilan turgan shaxslar; haftalik yangilash
- [x] 3b.5b openinfo.uz (emitentlar oshkor qilgan ma'lumot): kompaniya qidiruvida direktor, bosh
      hisobchi, mas'ul xodim, STIR, tiker, manzil, sayt; faqat so'rov bo'yicha, 1 so'rov/s, 7 kun
      kesh; kirill so'rov o'zbek lotiniga o'giriladi; sayt → domen pivot
- [x] 3b.5c GLEIF Level-2 (sho'ba kompaniyalar) + UK Companies House (bepul kalit, kalitsiz jim
      o'tadi); manbalar parallel; GDELT 6 s timeout, 5 s limitga rioya, 6 soat kesh — kompaniya
      qidiruvi ~14 s → 2–5 s; aniq reyestr mosliklari birinchi, qisman mosliklar oxirida
- [ ] 3b.5 Kompaniyalar (eski band matni): egov reyestrlarini STIR bo'yicha birlashtirib qidiruvga ulash →
      openinfo.uz (AJ rahbariyati) → GLEIF L2 + UK Companies House (bepul kalit) — M/L
- [ ] 3b.6 Breach: XposedOrNot saqlanadi, HIBP'ning bepul breach katalogi bilan boyitish — S
- Eslatma: to'liq yuridik shaxslar reyestri data.egov.uz'da manbaning o'zida 65 535 qatorda
  kesilgan — to'liq nusxa faqat Soliq qo'mitasi/portal operatoriga murojaat bilan

## Faza G — Rasm geolokatsiyasi (rasm → xaritadagi joy)
- [x] G1 Rasm faylini yuklash (yoki URL) — "Geolocate" tabi, drag & drop
- [x] G2 OCR: ingliz + rus + o'zbek (lotin/kirill); telefon kodi va domen → mamlakat ishorasi
- [x] G3 Lokal vizual model (Qwen2.5-VL 7B, brauzerdan Ollama) — ko'rinadigan belgilar va joy
      nomlari, JSON schema, odamni aniqlamaydi
- [x] G4 GeoCLIP (MIT) alohida CPU konteyner; galereya embeddinglari bir marta hisoblanadi
- [x] G5 OpenStreetMap Nominatim geokodlash (1 so'rov/s, 30 kun kesh)
- [x] G6 Birlashtirish: yaqin nomzodlar birlashadi, mustaqil manbalar kelishsa ishonch oshadi;
      Leaflet xaritada ishonch doirasi bilan; har nomzodda dalillar va tekshirish havolalari
- [x] G7 Tekshirish havolalari (Google Maps/Earth, OSM, Yandex, SunCalc)
- [ ] G8 Mapillary/KartaView ko'cha fotolari bilan solishtirish havolalari; quyosh/soya tahlili
- [ ] G9 Server tomonda vizual model (Ollama'ni konteynerdan ochish yoki GPU runtime) — API'dan
      to'liq avtomat ishlashi uchun
- Chegara: faqat joy taxmin qilinadi; odamni tanish yoki yuz bo'yicha qidirish — yo'q

## Faza 4 — Holehe kengaytmasi (poydevor ✅, yangi modullar test akkaunt kutmoqda)
Maqsad: email bo'yicha "ro'yxatdan o'tganlik signali"ni ishonchli va kengroq qilish.

Poydevor:
- [x] 4.1 (eski 1.8) Holehe'ni subprocess o'rniga Python ichidan chaqirish (modullar
      `async def site(email, client, out)` shaklida). Natija uch holatli: `used` / `not_used` /
      `unknown` (rate-limit, captcha, xato) + sabab
- [x] 4.2 (eski 1.7) Modul salomatligi: har bir modulning oxirgi 20 natijasi saqlanadi; doim
      `unknown` qaytaradigan modul avtomatik o'chiriladi va panelda ko'rsatiladi
- [x] 4.0 Xavfsizlik siyosati: Holehe'ning 121 modulidan 4 tasi parol tiklash oqimini, 13 tasi
      login formani ishlatadi — ular egasiga xat/ogohlantirish yuborishi mumkin. Parol tiklash —
      hech qachon; login — faqat `HOLEHE_ALLOW_LOGIN=1`; kattalar saytlari (maxsus toifadagi
      ma'lumot) — faqat `HOLEHE_INCLUDE_ADULT=1`. Standart: 100 modul
- [~] 4.3 Ma'lum test email'lari (o'zimizniki: ro'yxatdan o'tgan va o'tmagan) bilan kunlik
      kanareyka tekshiruvi — modul jimgina buzilganini ushlaydi
      Bajarildi: har kuni tasodifiy, hech kim ishlatmagan manzil bilan — "registered" degan modul
      (soxta ijobiy) 7 kunga to'xtatiladi. Qoldi: haqiqiy test akkaunt bilan soxta salbiyni ushlash
- [x] 4.4 Har bir domenga rate-limit va global semafor; 429/captcha'da backoff, `unknown`

Yangi va tuzatiladigan modullar (eski 4.6):
- [ ] 4.5 Buzilganlarini tuzatish: Instagram, Google, GitHub, Discord
- [ ] 4.6 Yangi: OLX.uz, hh.uz, Uzum, Yandex, VK, Mail.ru

Har bir modul uchun majburiy tekshiruv (merge'dan oldin):
1. Faqat "email band/bo'sh" javobini beradigan endpoint ishlatiladi; parol tiklash yoki tasdiqlash
   kodi yuboradigan endpoint — **ishlatilmaydi**
2. O'zimizning test akkauntimizda sinab ko'riladi: egasiga xat, SMS yoki push bormasligi tasdiqlanadi
3. Javoblar fixture sifatida saqlanadi, offline test yoziladi
4. Telefon raqami bo'yicha tekshiruv modullari qo'shilmaydi

UI va sozlash:
- [ ] 4.7 Kengaytirilgan modullar `HOLEHE_EXTENDED=1` bilan yoqiladi (standart: o'chiq)
- [x] 4.8 UI: "Ro'yxatdan o'tganlik signali — tasdiqlanmagan", `unknown` alohida ko'rsatiladi;
      korrelatsiyada faqat zaif signal (o'zi birlashtirmaydi)
- ~~Ignorant (telefon → Instagram/Snapchat)~~ — qo'shilmaydi (telefon bo'yicha akkaunt tekshiruvi)

## Faza 5 — Backend AI qatlami (Ollama) — M
- [ ] 5.1 Ollama klient: JSON schema, timeout, `think: false`; qwen2.5:7b tez ishlar,
      qwen3:8b yakuniy xulosa (8 GB GPU'da birga yuklamaslik)
- [ ] 5.2 Har bir chaqiruv bitta tor vazifa, javobda `evidence_ids[]` majburiy
- [ ] 5.3 Nomzodlarni saralash: "shu odammi?" ha / yo'q / noaniq + sabab. Bu faqat zaif signal,
      birlashtirish qarorini Faza 2 modeli qiladi
- [ ] 5.4 Pivot filtri: keyingi qadamga qaysi pivot arziydi
- [ ] 5.5 Uydirmaga qarshi tekshiruv: javobdagi har bir email, raqam, URL dalilda so'zma-so'z
      bo'lishi shart, aks holda olib tashlanadi
- [ ] 5.6 AI o'chirilgan yoki Ollama yo'q bo'lsa hamma narsa AI'siz ishlaydi

## Faza 6 — "Thinking / Agent" rejimi — L
- [ ] 6.1 Erkin matn parser: ism (lotin/kirill variantlari), yosh, shahar, handle, email, telefon
      (masalan "lutfullo abdubaniyev 19 yosh namangandan")
- [ ] 6.2 Reja → barcha tekshiruvlar parallel + Deep Scan → saralash (Faza 2 + 5) → manbali xulosa
- [ ] 6.3 Deep Scan va agent worker'da; qadamlar UI'da jonli (SSE yoki job polling)
- [ ] 6.4 Yosh va shahar nomzodlarni saralashda ishlatiladi (ziddiyat → vazn tushadi)
- [ ] 6.5 Natija: nomzodlar ro'yxati, har bir maydon yonida manba havolasi va "nima uchun bog'landi";
      topilmagan maydon — "topilmadi"
- [ ] 6.6 Yakuniy qaror insonda: nomzodni "tasdiqlash / rad etish" tugmalari (AI qonuni talabi)

## Faza 7 — Shaxs kartasi va yangi manbalar — M/L
- [ ] 7.1 Shaxs kartasi + PDF: profillar, ochiq kontaktlar, dalillar zanjiri
- [ ] 7.2 Ochiq sahifalardan kontakt ajratish (bio, kanal tavsifi, OLX e'lon, sayt "Kontakt"
      sahifasi) — har biri manbasi bilan
- [ ] 7.3 `filetype:pdf/doc/xls` dork'lari ism qidiruviga
- [ ] 7.4 orginfo.uz: rahbar/ta'sischi → Company, Name pivot (ishonchliligi o'rta deb belgilanadi)
- [ ] 7.5 public.sud.uz, Epieos, data.egov.uz — qo'lda tekshirish havolalari
- [ ] 7.6 Aniqlashtiruvchi maydonlar: shahar, ish joyi, yosh, o'qish joyi
- [ ] 7.7 Kontakt ajratuvchi (Photon g'oyasi, o'zimizning kod): sayt yoki profil sahifasidan
      1 chuqurlikda ≤ 10 sahifa, `safe_get` orqali, robots.txt hurmat qilinadi → email, ijtimoiy
      havolalar, telefon — har biri sahifa URL'i bilan (7.2 shu modulni ishlatadi) — M
- [ ] 7.8 Grafni eksport qilish: GraphML va Maltego CE uchun CSV (Deep Scan node/edge,
      dalillari bilan) — S

## Faza 8 — Qonuniy va operatsion talablar — S/M
- [ ] 8.1 Har bir maydon manbasi va olingan vaqti saqlanadi (ZRU-547, 30-modda)
- [ ] 8.2 Case va natijalarni to'liq o'chirish funksiyasi
- [ ] 8.3 Audit log: kim, qachon, nimani qidirdi (lokal)
- [ ] 8.4 Kirish: kamida oddiy autentifikatsiya, agar tool tarmoqqa ochilsa
- [ ] 8.5 README'da foydalanish shartlari (himoya, tadqiqot, jurnalistika; doxxing emas)

## Faza 9 — O'quv kursi
- [ ] 9-modul: yakuniy loyiha (self-OSINT, manbalarni hujjatlashtirish)

---

## Tashqi OSINT loyihalari tahlili (2026-11-16, GitHub ma'lumotlari bo'yicha)

| Loyiha | Holati | Bizda | Qaror |
|---|---|---|---|
| Sherlock | faol, MIT | ✅ bor | yangilash (3.2) |
| Maigret | faol, MIT | ✅ bor | yangilash, self-check, o'zbek saytlari (3.2–3.3) |
| Holehe | 2024-09 dan beri commit yo'q | ✅ bor | Faza 4 |
| Shodan | — | ✅ InternetDB (kalitsiz) + kalit bilan | yetarli |
| Awesome-OSINT, OSINT Framework, Bellingcat | faol | ✅ katalogda | — |
| WhatsMyName | **arxivlangan** | katalogda | belgilash (3.8) |
| Subfinder | faol, MIT, v2.17.0 | ❌ | **qo'shiladi** (3.6) |
| theHarvester | faol, GPL-2.0 | ❌ | **qo'shiladi** (3.7) |
| Photon | oxirgi release 2019 | ❌ | g'oyasi o'zimizning kodda (7.7) |
| Maltego CE | yopiq kod, GUI | ❌ | faqat eksport (7.8) |
| Social-Analyzer | faol, AGPL-3.0 | ❌ | keyinroq baholanadi (3.9) |
| OWASP Amass | faol, v5 (og'ir, DB engine) | ❌ | hozircha yo'q: passivda Subfinder yetarli |
| SpiderFoot | oxirgi commit 2023-11, release 2022 | ❌ | integratsiya yo'q, modul g'oyalari uchun manba |
| Recon-ng | faol, interaktiv framework | ❌ | yo'q: bizning platforma bilan bir xil vazifa |
| PhoneInfoga | README: "stable but unmaintained" | qisman (libphonenumber) | yo'q: bizda bor narsani qiladi |
| Blackbird | faol | ❌ | yo'q: username bazasi arxivlangan WhatsMyName, email qismi Holehe bilan bir xil |
| GHunt | faol | ❌ | **yo'q**: Google akkauntiga login/cookie talab qiladi |
| Osintgram | faol | ❌ | **yo'q**: Instagram login, obunachilar kontaktlarini yig'adi |

## Optimallashtirish (fazalar bilan birga)
- Tezlik: Deep Scan (ism) hozir ~2 daqiqa; 2-chuqurlikda Maigret o'rniga yengil tekshiruv
- Har bir tashqi manbaga timeout + semafor; rate-limit'li manbalarga navbat va backoff
- Redis `appendonly` (restartda kesh va job natijalari yo'qolmasin)
- Kod: `investigate.py` va `app.js`ni modullarga bo'lish; FastAPI `lifespan`; test ogohlantirishlari
- Docker: worker va backend uchun memory/CPU limitlari

## O'zgarmaydigan chegaralar
- Faqat ochiq manbalar, har bir natija manba havolasi bilan
- Sizib chiqqan bazalar, "probiv" botlari, Telegram/WhatsApp akkauntini avtomatik tekshirish — yo'q
- Telefon raqami bo'yicha servislarda akkaunt tekshiruvi — yo'q
- Holehe: nishonga xat/SMS yuboradigan endpoint'lar — yo'q
- Login/cookie talab qiladigan vositalar (GHunt, Osintgram va shunga o'xshash) — yo'q
- AI dalilsiz kontakt "taxmin qilmaydi"; topilmasa "topilmadi"
- Natija — bitta profil emas, nomzodlar ro'yxati; yakuniy qaror insonda
