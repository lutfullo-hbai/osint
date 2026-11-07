# 7-modul: Mashqlar

## Mashq 1: Vositalarni o'rnatish ⭐
```bash
# Debian/Ubuntu
sudo apt install libimage-exiftool-perl poppler-utils
pip install mat2

# macOS
brew install exiftool poppler
pip install mat2
```
Tekshirish:
```bash
exiftool -ver
pdfinfo -v
```

## Mashq 2: Skriptni ishga tushirish 🎯 (KOD!)
Kompyuteringizdagi biror PDF, DOCX yoki ZIP faylni oling:
```bash
python3 07-metadata-fayllar/kod/file_metadata.py /yo'l/hujjat.pdf
python3 07-metadata-fayllar/kod/file_metadata.py /yo'l/hujjat.docx
```
Savollar:
1. `Author` yoki `lastModifiedBy` kim?
2. Qaysi dasturda yaratilgan?
3. Qanday xavf belgilari (`[!]`) chiqdi?

## Mashq 3: Office hujjatini qo'lda ochish ⭐⭐
```bash
unzip -l hujjat.docx
unzip -p hujjat.docx docProps/core.xml
unzip -p hujjat.docx docProps/app.xml
```
- `dc:creator` va `cp:lastModifiedBy` ni toping
- `Application` va `Company` maydonlarini yozing
- Skript natijasi bilan mos keldimi?

## Mashq 4: PDF metadata ⭐⭐
```bash
pdfinfo hujjat.pdf
exiftool -a -G1 hujjat.pdf | head -30
```
- `Producer` qaysi dastur? (Word, LaTeX, Chrome...)
- `CreationDate` va `ModDate` orasida qancha farq bor?
- PDF ichida Windows yo'li bormi?

## Mashq 5: Metadata tozalash ⭐⭐
**Avval zaxira nusxa oling!**
```bash
cp hujjat.docx hujjat_backup.docx
mat2 hujjat.docx
```
Yoki rasm uchun:
```bash
exiftool -all= rasm.jpg
```
Keyin qayta tekshiring:
```bash
python3 07-metadata-fayllar/kod/file_metadata.py hujjat.cleaned.docx
```
- Qaysi maydonlar yo'qoldi?
- Fayl hajmi o'zgardimi?

## Mashq 6: Rasm metadatası (4-modul bilan bog'liq) ⭐
```bash
exiftool -a -G1 -s rasm.jpg
python3 04-rasm-geo/kod/image_info.py rasm.jpg
```
- GPS, kamera modeli va dastur maydonlarini solishtiring
- Ijtimoiy tarmoqqa yuklangandan keyin qaysi maydonlar o'chadi?

## Mashq 7: `strings` va `binwalk` ⭐⭐⭐
```bash
strings fayl.bin | grep -iE "author|user|path|http" | head -20
binwalk fayl.bin
```
- Ichida qanday matn bo'laklari bor?
- Ichma-ich fayl (embedded) topildimi?

## Mashq 8: Tracked changes va izohlar ⭐⭐⭐
Word yoki Google Docs'da:
1. Hujjat yarating, bir nechta o'zgartirish kiriting (track changes yoqilgan)
2. Izoh qoldiring
3. DOCX qilib saqlang va skript bilan tekshiring

- `trackedChanges` soni chiqdimi?
- `commentFiles` ko'rindimi?
- Hujjatni "tozalash" (Accept all changes / Inspect Document) qilib qayta tekshiring.

## Mashq 9: Metadata soxtaligini tekshirish ⭐⭐⭐
Biror ochiq PDF oling va:
- `Producer` maydoni mantiqan mos keladimi? (masalan, "Microsoft Word" chiqishi kerak bo'lsa)
- `CreationDate` faylning `mtime`'iga mos keladimi?
- Xulosa: metadata'ga qanchalik ishonish mumkin?

## Mashq 10: Skriptni kengaytirish 🎯⭐⭐ (KOD!)
[file_metadata.py](kod/file_metadata.py) ga quyidagilarni qo'shing:
- [ ] MP3 (ID3) va MP4 metadata
- [ ] Papka bo'yicha barcha fayllarni tahlil qilish (`--dir`)
- [ ] Fayl imzosini kengaytma bilan solishtirish (mismatch ogohlantirishi)
- [ ] EXIF GPS bo'lsa xarita havolasi
- [ ] CSV hisobot chiqarish

## Mashq 11: Metadata xavf hisoboti 🎯⭐⭐
Ochiq manbadan 3 xil fayl (PDF, DOCX, rasm) oling va hisobot tuzing:

| Fayl | Tur | Muallif | Dastur | Sana | Xavf |
|------|-----|---------|--------|------|------|
| ... | ... | ... | ... | ... | Yuqori/O'rta/Past |

Xulosa: qaysi fayl turi eng ko'p ma'lumot oshkor qiladi? Nega?

⚠️ Faqat ochiq va ruxsat etilgan fayllar. Shaxsiy hujjatlarni ommaga chiqarmang.

---

✅ Keyingi modul: **Anonimlik va o'z himoyangiz**
