# 4-modul: Rasm tahlili va Geolokatsiya

## Nazariya: Rasm — bu faqat tasvir emas
Har bir raqamli rasm ichida **ko'rinmas ma'lumotlar** bo'lishi mumkin:

```
photo.jpg
 ├── Piksellar        → ko'zga ko'rinadigan tasvir
 ├── EXIF metadata    → kamera, vaqt, GPS, dastur
 ├── Fayl nomi/yo'li  → ba'zan joy yoki sana
 └── Vizual belgilar  → imorat, belgi, quyosh soyasi
```

OSINTda rasm bilan ishlash 3 bosqichdan iborat:

1. **Texnik tahlil** — metadata (EXIF) va fayl izlari
2. **Teskari qidiruv** — rasm boshqa joyda uchraydimi?
3. **Geolokatsiya** — rasm qayerda olinganini vizual belgilar orqali aniqlash

## 1. EXIF metadata

EXIF — kamera rasmga avtomatik yozadigan ma'lumotlar:

| Maydon | Nimani beradi |
|--------|---------------|
| `Make`, `Model` | Kamera/telefon brendi va modeli |
| `DateTimeOriginal` | Suratga olingan sana va vaqt |
| `Software` | Tahrirlash dasturi (Photoshop, Instagram...) |
| `LensModel`, `FNumber`, `ExposureTime`, `ISO` | Linza va suratga olish sozlamalari |
| `GPSLatitude`, `GPSLongitude` | Koordinatalar (agar yoqilgan bo'lsa) |

⚠️ Ijtimoiy tarmoqlar (Instagram, Telegram, WhatsApp) ko'pincha EXIFni **o'chirib tashlaydi**.
Shuning uchun metadata yo'qligi — rasm "toza" degani emas.

### GPS koordinatalarini o'qish
EXIF GPS **daraja–daqiqa–sekund (DMS)** formatida saqlanadi:

```
40° 26' 46.8" N   →  40 + 26/60 + 46.8/3600 = 40.4463
```

Janubiy (`S`) va g'arbiy (`W`) qiymatlar **manfiy** bo'ladi.

## 2. Teskari qidiruv (reverse image search)

| Vosita | Kuchli tomoni | Kamchiligi |
|--------|---------------|------------|
| Google Lens | Keng indeks, obyektlarni taniydi | Yuzlarni yaxshi topmaydi |
| Yandex Images | MDH hududi va yuzlar uchun kuchli | G'arb manbalarida kamroq |
| TinEye | Aynan nusxalarni topadi, tarixni ko'rsatadi | Yangi rasmlarni kam topadi |
| Bing Visual Search | Muqobil indeks | Natijalari cheklangan |

Amaliy qoida: **bir nechta vositada** tekshiring — indekslar bir xil emas.

⚠️ Yuz bo'yicha qidiruvchi xizmatlar (PimEyes va shunga o'xshashlar) jiddiy
maxfiylik va qonuniy cheklovlarga ega. Faqat o'zingizni yoki ruxsat berilgan
tekshiruvni himoya qilish uchun ishlating.

## 3. Geolokatsiya: vizual belgilar

Rasmda joyni aniqlash uchun quyidagilarni izlang:

- **Yozuvlar va til** — ko'cha belgilari, do'kon nomlari, alifbo
- **Arxitektura** — uy uslubi, tom shakli, deraza turi
- **Tabiat** — daraxt turlari, relyef, tuproq rangi
- **Transport** — mashina raqamlari, yo'l belgilari, avtobuslar
- **Osmon va soya** — quyosh balandligi orqali vaqtni taxmin qilish
- **Ob-havo** — rasmdagi holat bilan arxiv ma'lumotlarini solishtirish

### Chronolocation (vaqtni aniqlash)
Soya uzunligi va yo'nalishi orqali taxminiy **kun va soat**ni aniqlash mumkin:
- Quyosh qaysi tomondan tushmoqda? (shimoliy yarim sharda janubdan)
- Soya qancha uzun? (tong/kechqurun uzun, tush payti qisqa)
- Vosita: suncalc.org — istalgan koordinata uchun quyosh holatini ko'rsatadi

### Tekshirish qoidasi
Bitta belgi — bu gipoteza. **Kamida 2-3 mustaqil belgi** bir joyga ishora qilsagina
xulosa qiling. Bellingcat uslubi: topilgan joyni Google Street View yoki sun'iy
yo'ldosh rasmlari bilan solishtiring.

## OPSEC eslatma
- Rasmni teskari qidiruvga yuklashdan oldin **EXIFni tozalang** (o'z rasmlaringizni)
- Shaxsiy akkauntlardan teskari qidiruvga kirmang — tarix va fingerprint qoladi
- Topilgan shaxsning uyini, manzilini ommaga e'lon qilmang — bu doxxing
- Faqat jamoat manbalari va qonuniy maqsadlar (himoya, jurnalistika, tadqiqot)

## Kod: `image_info.py`
→ [kod/image_info.py](kod/image_info.py)

Skript nimalarni qiladi:
- Rasmni URL yoki lokal fayldan yuklaydi (maks. 15 MB)
- O'lcham, format va SHA-256 hashni chiqaradi
- EXIF: kamera, sana, dastur, linza, ISO va boshqalar
- GPS bo'lsa — decimal koordinata va xarita havolasi
- Google Lens/Yandex/TinEye/Bing uchun tayyor teskari qidiruv havolalari

O'rganadigan narsalar:
- `Pillow` bilan rasm ochish va format aniqlash
- `ExifRead` bilan metadata o'qish
- DMS → decimal koordinata konvertatsiyasi
- URL orqali rasm yuklashda xavfsizlik (hajm chegarasi, timeout)

## Mashqlar
→ [mashqlar.md](mashqlar.md)
