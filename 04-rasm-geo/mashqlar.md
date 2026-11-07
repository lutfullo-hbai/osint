# 4-modul: Mashqlar

## Mashq 1: Kutubxonalarni o'rnatish ⭐
```bash
pip install pillow ExifRead requests
```

## Mashq 2: Skriptni ishga tushirish 🎯 (KOD!)
O'zingizning telefoningizda GPS yoqilgan holda tushirilgan rasmni oling:
```bash
python3 04-rasm-geo/kod/image_info.py /yo'l/rasm.jpg
```
Savollar:
1. Kamera modeli va sana to'g'ri chiqdimi?
2. GPS koordinatalari bormi? Xarita havolasini ochib tekshiring.
3. `Software` maydonida nima yozilgan?

## Mashq 3: URL orqali tahlil ⭐⭐
Internetdagi ochiq rasm bilan sinang:
```bash
python3 04-rasm-geo/kod/image_info.py "https://httpbin.org/image/jpeg"
```
- Metadata bormi? Nega yo'q?
- Teskari qidiruv havolalarini brauzerda ochib ko'ring.

## Mashq 4: DMS → decimal qo'lda hisoblash ⭐⭐
Quyidagi koordinatani o'zingiz hisoblab, skript natijasi bilan solishtiring:
```
41° 18' 40.8" N
69° 14' 24.0" E
```
Formula: `daraja + daqiqa/60 + sekund/3600`.
So'ng Google Maps'da `41.311333, 69.240000` ni ochib, qaysi joy ekanini ayting.

## Mashq 5: Teskari qidiruv — 4 vositada ⭐⭐
Bitta rasm tanlang (masalan, o'z rasmingiz yoki Wikimedia Commons'dan ochiq rasm) va:
1. Google Lens
2. Yandex Images
3. TinEye
4. Bing Visual Search

Har biri uchun yozib boring:
- [ ] Nechta natija topdi?
- [ ] Qaysi biri bir xil nusxani topdi?
- [ ] Qaysi biri eng yaxshi ishladi?

Xulosa: nega natijalar farq qiladi?

## Mashq 6: Geolokatsiya challenge 🎯⭐⭐
Ochiq manbadan (Bellingcat, Wikimedia, yangiliklar) biror **jamoat joyidagi** rasm tanlang.
Topshiriq:
1. Kamida **3 ta mustaqil vizual belgi** toping (yozuv, arxitektura, transport, tabiat)
2. Taxminiy shaharni aniqlang
3. Google Street View yoki sun'iy yo'ldosh rasmi bilan solishtiring
4. Topilgan joyni hisobot ko'rinishida yozing:
   - Belgi → qanday xulosa → qanday tekshirdim

⚠️ Faqat jamoat joylarini tekshiring. Xususiy uy yoki shaxs manzilini aniqlamang!

## Mashq 7: Chronolocation ⭐⭐⭐
Tanlangan rasm uchun:
1. Soyaning yo'nalishi va uzunligini yozing
2. https://www.suncalc.org da taxminiy koordinatani kiriting
3. Qaysi oy/kun/soatda soya shunday bo'lishini toping
4. Natijani rasmning EXIF sanasi bilan solishtiring (agar mavjud bo'lsa)

## Mashq 8: Skriptni kengaytirish 🎯⭐⭐ (KOD!)
[image_info.py](kod/image_info.py) ga quyidagilarni qo'shing:
- [ ] Natijani JSON faylga saqlash (`--json natija.json`)
- [ ] Bir nechta rasmni birdan tahlil qilish (papka bo'yicha)
- [ ] `--strip` rejimi: EXIFni o'chirilgan nusxani saqlash
- [ ] GPS bo'lsa, teskari geokodlash (OpenStreetMap Nominatim) — manzil nomi

### EXIFni tozalash namunasi
```python
from PIL import Image

image = Image.open("rasm.jpg")
image.save("tozalangan.jpg")  # EXIFsiz saqlanadi
```

## Mashq 9: OPSEC tekshiruvi ⭐
1. Ijtimoiy tarmoqqa yuklagan rasmingizni yuklab oling
2. `image_info.py` bilan tekshiring — GPS qolganmi?
3. Natijani yozing: qaysi platforma metadata'ni o'chiradi, qaysi biri yo'q?

---

✅ Keyingi modul: **Domen, IP va Web texnologiyalar**
