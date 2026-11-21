# Loyiha bosh rejasi — kiberxavfsizlik o'quv yo'nalishi

Bu repo ikki o'quv bosqichidan iborat: har biri **qo'llanma + bitta amaliy loyiha**.

| Bosqich | Qo'llanma | Loyiha | Holati |
|---|---|---|---|
| 1. OSINT | `01-…`–`09-…` modullari | NEXUS konsoli (`osint-tool/`) | tool ~1.0.0 arafasida |
| 2. Pentest | `pentest/kurs/` | izolyatsiyalangan lab (`pentest/lab/`) | poydevor qurildi (P1) |

Batafsil, mayda bandlar ikkita alohida roadmap'da:
- OSINT tool: [`osint-tool/ROADMAP.md`](osint-tool/ROADMAP.md) — "Ish rejasi — bosqichma-bosqich" (Bosqich 1–5)
- Pentest: [`pentest/ROADMAP.md`](pentest/ROADMAP.md) — P1–P5

Bu fayl — **umumiy ketma-ketlik**: nima avval, nima keyin. Mayda qadamlar yuqoridagi fayllarda.

## Ishlash tartibi (har bir qadamda bir xil)
1. **Tahlil** — sabab dalil bilan (o'lchov, log, kod), taxmin emas
2. **Avval test** — xatoni ko'rsatadigan test
3. **Kod** — eng kichik o'zgarish, `feat/*` branch
4. **Tekshiruv** — barcha testlar; natijaga ta'sir qilsa jonli o'lchov (commit qilingan kodda)
5. **Review** — ball/xavfsizlik/ma'lumotga tegsa reviewer yoki QA agent
6. **dev** — `--no-ff` merge, CI yashil, ROADMAP + CHANGELOG yangilanadi
7. **Reliz** — bosqich tugaganda: stage (test + jonli sinov) → PR → main → teg → GitHub Release.
   **stage va main faqat sizning ruxsatingiz bilan**

## Bajarilgan relizlar
v0.7.1 (#4) · v0.8.0 (#5) · v0.8.1 (#6) · v0.9.0 Faza 9 kurs (#7) · v0.10.0 aniqlik 10.1–10.3 (#8) ·
v0.11.0 Globe (#9) · v0.12.0 heretic vositasi (#10)

---

## Umumiy ketma-ketlik (bosqichlar)

### M1 — NEXUS 1.0.0: OSINT aniqlik yakuni  ⏳ hozir
Manba: `osint-tool/ROADMAP.md` → Bosqich 1.
- [~] M1.1 10.5b-A (ismdosh-yosh) — jonli o'lchov: 7/7 "kuchli" ✅
- [~] M1.2 10.5b-B (joy mos/zid/noma'lum) + salbiy holatlar — jonli o'lchov (ketyapti)
- [ ] M1.3 QA agent: 10.5b ball qoidalari → tuzatishlar → dev
- [ ] M1.4 30 holat + 30 salbiy holat to'liq qayta o'lchov
- [ ] M1.5 **Reliz v0.13.0** (10.5 yakuni)
- [ ] M1.6 **Reliz 1.0.0** (10.4): README'da aniqlik natijalari va cheklov (holatlar — mashhur odamlar)

### M2 — NEXUS 1.1.0: audit va xavfsizlik sayqali
Manba: Bosqich 2 (8b.7–8b.10, R12). Kichik, tez ishlar — OSINT tool'ni yopishdan oldin.
- [ ] M2.1 (**siz**) 8b.10 qarori: umumiy jamoa ish joyimi yoki har kim faqat o'zinikini ko'radimi
- [ ] M2.2 8b.8 `saved_at` (manba vaqti yo'q natija), chaqiruvchi dict'i o'zgarmaydi — S
- [ ] M2.3 8b.9 Audit yozuvi fon vazifasida, eski yozuvlar soatiga bir marta tozalanadi — S
- [ ] M2.4 8b.7 Sezgir o'qishlar auditi (shaxs kartasi, agent run, job — birinchi o'qish) — S
- [ ] M2.5 8b.10 javobiga qarab egalik (`owner`, filtrlar) yoki README'da yozuv — S/M
- [ ] M2.6 R12 Rasm hajmi stream paytida; watch signature 300 ta — S
- [ ] M2.7 Reviewer → **Reliz 1.1.0**

### M3 — Pentest lab: attacker box va asosiy vositalar
Manba: `pentest/ROADMAP.md` → P1 (✅), P2.
- [x] M3.1 P1 Lab poydevori: Juice Shop izolyatsiyada, `make verify` ✅
- [ ] M3.2 P1.3 Ikkinchi nishon DVWA; nishon ↔ attacker tarmog'i
- [ ] M3.3 P2.1 Attacker box konteyneri (nmap, curl, netcat, Python) — lab tarmog'ida, internetsiz;
  o'quvchi shu yerdan ishlaydi va nishonni brauzerda ko'radi
- [ ] M3.4 P2.2 OWASP ZAP, nuclei, sqlmap — har biri konteyner/profil
- [ ] M3.5 P2.3 Har bir vosita uchun "birinchi ishga tushirish" tekshiruvi (nishonga qarshi)
- [ ] M3.6 Reviewer (izolyatsiya) → **Reliz pentest-lab v0.1**

### M4 — Pentest AI capstone (Strix)
Manba: P3.
- [ ] M4.1 Strix'ni alohida konteyner sifatida ulash (Apache-2.0, aniq versiya), lab tarmog'ida;
  LLM kalitini o'quvchi beradi (ixtiyoriy)
- [ ] M4.2 Faqat lab nishoniga qarata ishlash namunasi + cheklov hujjati
- [ ] M4.3 Reviewer: izolyatsiya, litsenziya, LLM kalit brokerligi → **Reliz pentest-lab v0.2**

### M5 — Pentest qo'llanma (kurs to'liq)
Manba: P4.
- [x] M5.1 01 Kirish, axloq, lab ✅
- [ ] M5.2 02 Recon (OSINT bosqichi bilan bog'lanish)
- [ ] M5.3 03 Web zaifliklari (OWASP Top 10, Juice Shop/DVWA mashqlari)
- [ ] M5.4 04 Skanerlash (nmap, nuclei)
- [ ] M5.5 05 Ekspluatatsiya asoslari (sqlmap, ZAP — faqat lab)
- [ ] M5.6 06 Metodologiya (bosqichlar daraxti — PentestGPT g'oyasi), hisobot
- [ ] M5.7 07 AI bilan pentest (Strix, cheklovlari)
- [ ] M5.8 08 Yakuniy loyiha + hisobot shabloni
- [ ] M5.9 **Reliz pentest-kurs v1.0** (pentest bosqichi to'liq)

### M6 — NEXUS 1.2.0: bog'lash mustahkamligi
Manba: Bosqich 3.
- [ ] M6.1 3.1 Jarayonlararo umumiy rate-limit (Redis): dev.to, GitHub, Wikidata, Nominatim — M
- [ ] M6.2 3.2 Klaster ichidagi bilvosita ziddiyat (A–B–C) vetosi — M
- [ ] M6.3 2.7 Etalonga o'z scan'larimizdan real, qo'lda belgilangan holatlar — M
- [ ] M6.4 Reviewer/QA → **Reliz 1.2.0**

### M7 — NEXUS manbalar (test akkaunt kerak)
Manba: Bosqich 4. Ba'zilari sizning test akkauntlaringizga bog'liq.
- [ ] M7.1 3.3 O'zbek saytlari ta'riflari — har biri mavjud username bilan jonli sinov
- [ ] M7.2 (**siz: test akkaunt**) 4.5 Buzilgan Holehe modullari: Instagram, Google, GitHub, Discord
- [ ] M7.3 4.6 Yangi modullar (OLX.uz, hh.uz, Uzum, Yandex, VK, Mail.ru) — 4 bandli xavfsizlik tekshiruvi
- [ ] M7.4 4.7 `HOLEHE_EXTENDED=1`
- [ ] M7.5 (**siz: test akkaunt**) 4.3 Kanareyka: soxta salbiy natijani ushlash
- [ ] M7.6 3b.5 egov reyestrlarini STIR bo'yicha birlashtirish — M/L

### M8 — NEXUS geo va optimallashtirish
Manba: Bosqich 5.
- [ ] M8.1 G8 Mapillary/KartaView havolalari, quyosh/soya tahlili — M
- [ ] M8.2 3.9 Social-Analyzer baholash (M7.1 yetarli bo'lmasa; AGPL — alohida konteyner)
- [ ] M8.3 Optimallashtirish: Redis `appendonly`, memory/CPU limitlari, `investigate.py` va `app.js`ni
  modullarga bo'lish, FastAPI `lifespan`, test ogohlantirishlari

---

## To'xtovsiz (parallel, sizga bog'liq)
- (**siz**) Oddiy odamlar holatlari, rozilik bilan (`*.private.jsonl`) — 1.0.0 dan keyin ham davom
  etadi; har yangi holat o'lchovga qo'shiladi. Hozirgi barcha holatlar Wikidata'dagi mashhur
  odamlar, bu aniqlik o'lchovining asosiy cheklovi
- (**siz**) M2.1 (8b.10), M7.2/M7.5 test akkauntlari, M4 uchun LLM kaliti

## Nega shu tartib
1. **M1 avval:** NEXUS 1.0.0 arafasida, ish allaqachon boshlangan — avval shuni yopamiz.
2. **M2:** kichik, tez xavfsizlik sayqali — OSINT tool'ni "yaxshi holatda" qoldirib, pentestga o'tamiz.
3. **M3–M5:** pentest bosqichi to'liq quriladi (lab → capstone → kurs). Bu yangi o'quv deliverable.
4. **M6–M8:** OSINT tool'ni yanada kuchaytirish — bir qismi sizning test akkauntlaringizga bog'liq,
   shuning uchun oxirroqda.

Pentest va OSINT chegarasi qat'iy: pentest vositalari faqat `pentest/lab/` ichidagi izolyatsiya
qilingan nishonlarga, hech qachon NEXUS'ga aralashtirilmaydi.
