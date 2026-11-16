# NEXUS OSINT — Roadmap

Holat va reja (2026-11-16). Har bir band yonida qayerda topilgani yozilgan.
Bajarilganlari `[x]` bilan belgilanadi.

## Faza 0 — boshlangan ishni yakunlash
- [x] Tez tuzatishlar: CORS PATCH/DELETE, watch keshni chetlab o'tadi, dossier case nomi
- [x] Kalitsiz breach tekshiruvi (XposedOrNot; HIBP kaliti bo'lsa HIBP)
- [x] Telefon: qo'lda tekshirish havolalari "checked: false", `found_online`

## Faza 1 — Poydevor: ma'lumot sifati (eng muhim)
- [x] 1.1 Korrelatsiya: pivot o'zini "shared handle" dalili qilmaydi; ishonch eng zaif a'zo bo'yicha
      (Torvalds scan'i 5 xil odamni HIGH bilan birlashtirgan edi)
- [x] 1.2 Ism bo'yicha "display name mos" akkauntlar — faqat nomzod (`candidates`), birlashtirilmaydi
- [x] 1.3 Postdagi `@tag` handle'lar Deep Scan'da kuzatilmaydi (Prezident scan'i Qatar amiriga o'tib ketgan edi)
- [x] 1.4 Ixtiyoriy `GITHUB_TOKEN` (faqat api.github.com'ga yuboriladi; limit 60 → 5000/soat)
- [ ] 1.5 Veb-qidiruv: DuckDuckGo o'rniga/yonida o'z SearXNG (DDG rate-limit qilyapti)
- [~] 1.6 Sherlock scan paytidagi `exit 1` — qayta chiqmadi; xato xabariga stdout qo'shildi, kuzatish kerak
- [ ] 1.7 Holehe salomatlik monitoringi (121 moduldan faqat 38 tasi javob berdi)
- [ ] 1.8 Holehe'ni kod ichidan chaqirish (aniq used / not used / unknown)
- [ ] 1.9 Truecaller: tarmoqdan ulanib bo'lmasa o'chirish (timeout)
- [ ] 1.10 Watch: manba vaqtincha yiqilsa uning natijalari "removed" deb yozilmasin
- [ ] 1.11 Frontend: case nomini escape qilish (`app.js` case summary), `API_BASE`ni sozlanadigan qilish

## Faza 2 — Backend AI qatlami (Ollama: qwen2.5:7b tez, qwen3:8b aniqroq)
- [ ] 2.1 Backend → Ollama klient (JSON schema, timeout)
- [ ] 2.2 Nomzodlarni saralash: "shu odammi?" ha/yo'q/noaniq + sabab (sinovda 4 namesake'ni to'g'ri rad etdi)
- [ ] 2.3 Pivot filtri (keyingi qadamdan oldin)
- [ ] 2.4 Uydirmaga qarshi tekshiruv: javobdagi email/raqam/URL dalilda so'zma-so'z bo'lishi shart

## Faza 3 — "Thinking / Agent" rejimi
- [ ] Erkin matn → ism (lotin/kirill variantlari), yosh, shahar, handle, email, telefon
- [ ] Barcha tekshiruvlar parallel + Deep Scan → saralash → manbali xulosa
- [ ] Qadamlar UI'da jonli (SSE yoki job polling)
- [ ] Telefon raqami ochiq sahifada uchrasa (OLX, kanal tavsifi) — manbasi bilan bog'lash

## Faza 4 — Shaxs kartasi va yangi manbalar
- [ ] 4.1 Shaxs kartasi: nomzodlar ro'yxati (profillar, ochiq kontaktlar, "nima uchun bog'landi") + PDF
- [ ] 4.2 Ochiq sahifalardan kontakt ajratish (har biri manbasi bilan)
- [ ] 4.3 `filetype:pdf/doc/xls` dork'lari ism qidiruviga
- [ ] 4.4 orginfo.uz (robots.txt ruxsat beradi): rahbar/ta'sischi → Company, Name, pivot
- [ ] 4.5 public.sud.uz va Epieos — qo'lda tekshirish havolalari (sud.uz bu tarmoqdan ochilmadi)
- [ ] 4.6 Holehe modullarini tuzatish/kengaytirish (Instagram, Google, GitHub, Discord; OLX.uz, hh.uz, Uzum, Yandex, VK, Mail.ru)
- [ ] 4.7 Ignorant sinovi (telefon → Instagram/Snapchat; 2021-yildan beri yangilanmagan)
- [ ] 4.8 Aniqlashtiruvchi maydonlar: shahar, ish joyi, yosh

## Faza 5 — O'quv kursi
- [ ] 9-modul: yakuniy loyiha (self-OSINT, manbalarni hujjatlashtirish)

## Optimallashtirish
- Tezlik: Deep Scan (ism) 5–6 daqiqa — avval har bir tekshiruvni o'lchash; 2-chuqurlikda
  Maigret o'rniga yengil tekshiruv; Deep Scan'ni worker'ga o'tkazib jonli progress
- Har bir tashqi manbaga timeout + semafor; rate-limit'li manbalarga navbat va backoff
- Manbalar salomatligi paneli (Holehe, GitHub limiti, qidiruv holati)
- Redis `appendonly` (hozir restartda kesh/job natijalari yo'qoladi)
- Ollama: tez ishlarga qwen2.5:7b, yakuniy xulosaga qwen3:8b (8 GB GPU'da birga yuklamaslik)
- Kod: `investigate.py` va `app.js`ni modullarga bo'lish; `lifespan`; test ogohlantirishlari

## O'zgarmaydigan chegaralar
- Faqat odamning o'zi ochiq e'lon qilgan ma'lumot, har biri manba havolasi bilan
- Sizib chiqqan bazalar, "probiv" botlari, Telegram/WhatsApp akkauntini avtomatik tekshirish — yo'q
- AI dalilsiz kontakt "taxmin qilmaydi"; topilmasa "topilmadi"
- Natija — bitta profil emas, nomzodlar ro'yxati
