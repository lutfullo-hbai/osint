# 9-modul: Yakuniy loyiha — to'liq profil tekshiruvi

## Nazariya: 8 ta modul — bitta tadqiqot
Oldingi modullarda har bir usulni alohida o'rgandik. Yakuniy loyihada ularni
**bitta tartibli tadqiqotga** birlashtirasiz. Obyekt sifatida **o'zingizni**
olasiz (self-OSINT): begona odam siz haqingizda ochiq manbalardan nimani bila
olishini topasiz, har bir faktni hujjatlashtirasiz va oxirida izingizni
kamaytirasiz.

Nima uchun aynan o'zingiz?
- **Qonuniy va axloqiy**: roziligi bor yagona obyekt — siz
- **Tekshirib bo'ladi**: qaysi topilma to'g'ri, qaysi biri adashgan — o'zingiz bilasiz
- **Foydali**: tadqiqot oxirida haqiqiy himoya rejasi chiqadi

⚠️ Boshqa odam (do'st, oila a'zosi) haqida faqat uning **yozma roziligi** bilan
ishlang: [shablon/rozilik.md](shablon/rozilik.md). Rozilik bo'lmasa —
loyiha faqat o'zingiz haqida.

## 1. Doira (scope) — nima qilamiz va nima qilmaymiz

| Qilamiz | Qilmaymiz |
|---------|-----------|
| Ochiq sahifalarni o'qish, qidiruv, arxivlar | Parol bilan kirish, birovning akkauntiga kirish |
| Davlat va ochiq reyestrlar | Sizib chiqqan bazalar, "probiv" botlari |
| O'z akkauntlaringizni tashqaridan ko'rish | Do'stlaringizga yozib "tekshirish" (HUMINT) |
| Topilgan dalillarni saqlash | Topilgan ma'lumotni joylashtirish yoki tarqatish |

Doirani loyiha boshida **yozib qo'ying**. Tadqiqot davomida yangi savol chiqsa,
avval doiraga qo'shing, keyin izlang.

## 2. Metodologiya: razvedka tsikli + modullar
1-moduldagi tsikl yakuniy loyihaning skeleti:

```
1. REJA        → savollar, doira, boshlang'ich ma'lumot (seed)
2. TO'PLASH    → 2–7-modullar usullari, har bir topilma jurnalga
3. QAYTA ISHLASH → takrorlarni olib tashlash, vaqt va manba qo'shish
4. TAHLIL      → bog'lash, baholash, qarama-qarshiliklar
5. HISOBOT     → xulosa, dalillar, tavsiyalar (8-modul)
```

| Bosqich | Modul | Nima qilasiz |
|---------|-------|--------------|
| Seed | 1 | Ism, username, email — qaysidan boshlaysiz |
| Username / email | 2 | Sherlock/Maigret, email izlari |
| Telefon | 3 | Raqam qayerda ochiq yozilgan (faqat qidiruv, akkaunt tekshiruvi emas) |
| Rasmlar | 4 | Profil rasmlari, teskari qidiruv, EXIF |
| Domen / IP | 5 | Shaxsiy sayt, Whois, eski versiyalar |
| Ijtimoiy tarmoqlar | 6 | Profil ma'lumotlari, bog'lanishlar, vaqt chizig'i |
| Fayllar | 7 | Siz yozgan hujjatlar, ularning metadata'si |
| Himoya | 8 | Topilganlarni kamaytirish rejasi |

## 3. Pivot daraxti
Har bir topilma yangi qidiruvga **kalit** bo'ladi. Shuni chizib boring:

```
"Ali Valiyev" (seed)
 ├── username: alivaliyev  ──► GitHub ──► email: ali@...  ──► Gravatar
 │                         └─► Instagram ──► rasm ──► teskari qidiruv
 └── orginfo.uz: MCHJ rahbari ──► kompaniya sayti ──► telefon
```

Qoida: har bir chiziq uchun **qanday bog'langanini** yozing
("profilda havola bor", "bir xil rasm", "faqat ism mos").
NEXUS'dagi Deep Scan va Agent shu daraxtni avtomatik chizadi va GraphML'ga
eksport qiladi (7.8).

## 4. Dalillarni hujjatlashtirish
Hisobotdagi har bir fakt dalilga tayansin. **Manba yo'q — fakt yo'q.**

Har bir dalil uchun:
1. **URL** — aniq sahifa, qidiruv natijasi emas
2. **Vaqt (UTC)** — qachon ko'rdingiz (sahifa ertaga o'zgarishi mumkin)
3. **Nusxa** — skrinshot yoki sahifa fayli
4. **Hash (SHA-256)** — nusxa keyin o'zgarmaganini isbotlaydi
5. **Arxiv** — Wayback Machine yoki archive.today havolasi
6. **Izoh** — nima uchun muhim, nimani isbotlaydi

Bu zanjir (**chain of custody**) ishonchni beradi: boshqa odam sizning
xulosangizni qayta tekshira oladi.

`kod/evidence_log.py` shu ishni avtomatlashtiradi:
```bash
python3 09-yakuniy-loyiha/kod/evidence_log.py add https://github.com/alivaliyev \
    --note "username, ism ko'rsatilgan" --fetch --grade B2
python3 09-yakuniy-loyiha/kod/evidence_log.py report -o hisobot-dalillar.md
```

## 5. Ishonchlilikni baholash (Admiralty kodi)
Har bir dalilga ikki baho beriladi: **manba** qanchalik ishonchli va
**ma'lumot** qanchalik tasdiqlangan.

| Manba | Ma'no | | Ma'lumot | Ma'no |
|-------|-------|-|----------|-------|
| A | To'liq ishonchli (rasmiy reyestr) | | 1 | Boshqa manbalar tasdiqlagan |
| B | Odatda ishonchli | | 2 | Ehtimol to'g'ri |
| C | Ba'zan ishonchli | | 3 | Balki to'g'ri |
| D | Odatda ishonchsiz | | 4 | Shubhali |
| E | Ishonchsiz | | 5 | Ehtimoldan yiroq |
| F | Baholab bo'lmaydi | | 6 | Baholab bo'lmaydi |

Misollar:
- `A1` — davlat reyestridagi yozuv, boshqa manba bilan mos
- `B2` — o'zingiz yozgan GitHub profili
- `C3` — forumdagi bir xil nik, boshqa dalil yo'q
- `F6` — noma'lum sayt, tekshirib bo'lmaydi

NEXUS natijalaridagi `reliability` (masalan orginfo.uz — "medium") va
Agent'dagi kuchli/mumkin/zaif nomzod darajalari ham shu fikrga tayanadi.

## 6. Tahlil: adashmaslik
- **Bir xil ism — bir xil odam emas.** "Ali Valiyev" minglab. Ism faqat zaif signal
- **Kuchli bog'lanish**: profilda boshqa profilga havola, bir xil email, bir xil rasm
- **Qarama-qarshilik**ni yozing: shahar, yosh yoki kasb mos kelmasa, bu muhim dalil
- **Muqobil gipoteza**: "Bu boshqa odam bo'lishi mumkinmi?" — har bir xulosaga bering
- **Tasdiqlash xatosi (confirmation bias)**: kutganingizni emas, borini yozing
- **Vaqt**: 2015-yilgi sahifa bugungi holatni ko'rsatmaydi

## 7. Hisobot tuzilmasi
[shablon/hisobot.md](shablon/hisobot.md) asosida:

1. **Qisqa xulosa** — 5 ta eng muhim topilma va xavf darajasi
2. **Doira va usul** — nima tekshirildi, qanday, qachon
3. **Topilmalar** — kategoriya bo'yicha, har biri dalil raqami bilan
4. **Pivot daraxti** — rasm yoki GraphML
5. **Topilmadi** — tekshirilgan, lekin hech narsa chiqmagan joylar ham natija
6. **Xavf tahlili** — qaysi ma'lumot birgalikda xavfli (manzil + kun tartibi)
7. **Himoya rejasi** — nimani o'chirish, yashirish, o'zgartirish
8. **Ilova** — dalil jurnali (`evidence_log.py report`)

## 8. Izni kamaytirish (remediation)
Self-OSINT'ning maqsadi — himoya. Topilganlar bo'yicha:
- Profillarda maxfiylik sozlamalari, eski postlar va rasmlarni tozalash
- Ishlatilmaydigan akkauntlarni o'chirish
- Google: "Results about you" orqali shaxsiy ma'lumotli natijalarni olib tashlashni so'rash
- Sayt egasiga murojaat: eski sahifa, hujjat yoki rasmni olib tashlash
- Rasmlardan EXIF'ni tozalash (7-modul), username'larni ajratish (8-modul)
- 3–6 oydan keyin **qayta tekshirish** — o'zgarish bormi?

## 9. NEXUS bilan yakuniy loyiha
- **Agent**: "Ism Familiya, Shahar, username ..." — nomzodlar, manbalar, PDF karta
- Har bir natijada **manba va olingan vaqt** bor (8.1) — dalil jurnaliga import qiling
- **Data** tabi: audit log — siz nima qidirganingiz, qachon
- Loyiha tugagach: keraksiz case va run'larni **o'chiring** (8.2)

## Mashqlar
→ [mashqlar.md](mashqlar.md) ga o'ting
