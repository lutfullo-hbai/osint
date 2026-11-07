# 7-modul: Metaqidalar (metadata) va fayllar

## Nazariya: Fayl — bu konteyner
Har bir fayl **mazmun** va **metama'lumot**dan iborat:

```
hisobot.docx
 ├── Matn (ko'rinadigan mazmun)
 ├── docProps/core.xml   → muallif, sana, oxirgi tahrir
 ├── docProps/app.xml    → dastur, kompaniya, sahifalar
 ├── comments.xml        → izohlar
 └── revisions           → tahrir tarixi
```

Metama'lumot ko'pincha **ko'rinmaydi**, lekin aynan u eng qimmatli iz bo'lishi mumkin:
kim yaratdi, qaysi kompyuterda, qachon, qaysi dasturda.

## Metadata turlari

| Fayl turi | Metadata | Nimani beradi |
|-----------|----------|---------------|
| Rasm (JPG/PNG/TIFF) | EXIF, XMP, IPTC | Kamera, GPS, dastur, muallif (4-modul) |
| PDF | Info dictionary, XMP | Author, Creator, Producer, sana |
| Office (DOCX/XLSX/PPTX) | `docProps/core.xml`, `app.xml` | Muallif, kompaniya, oxirgi tahrir |
| Audio (MP3/FLAC) | ID3, Vorbis comments | Artist, album, softwar, sana |
| Video (MP4/MKV) | Atoms, tags | Encoder, qurilma, GPS ba'zan |
| Arxiv (ZIP) | Fayl izlari, comment | Yaratuvchi dastur, yo'llar |
| Fayl tizimi | `mtime`, `atime`, `ctime` | Yaratilgan/o'zgartirilgan vaqt |

## Eng qimmatli maydonlar

- **Author / Creator / LastModifiedBy** — shaxs yoki username
- **Company / Manager** — tashkilot ichki ma'lumoti
- **Application / AppVersion** — qaysi dastur va versiya
- **Template** — hujjat qaysi shablondan olingan
- **TotalTime / Revision** — qancha vaqt tahrirlangan
- **Paths** — `C:\Users\ism\...` kabi yo'llar (Office va PDF'da)
- **Comments / Tracked changes** — o'chirilmagan tahrirlar
- **Printers** — qaysi printerga chiqarilgan (ba'zi formatlarda)

⚠️ Metadata **soxtalashtirilishi** mumkin. Uni dalil sifatida emas, **gipoteza**
sifatida qabul qiling va boshqa manbalar bilan solishtiring.

## Vositalar

| Vosita | Vazifasi |
|--------|----------|
| **ExifTool** | Universal: 100+ formatdagi metadatanı o'qiydi/yozadi |
| `pdfinfo` (poppler) | PDF asosiy ma'lumotlari |
| `strings` | Ikkilik fayldan matn bo'laklarini chiqaradi |
| `binwalk` | Ichki fayllar va imzolarni topadi |
| `mat2` | Metadata tozalash (rasm, PDF, Office) |
| `oletools` | Office makrolarini tahlil qilish |
| `zipinfo` / `unzip -l` | Arxiv tarkibi |

```bash
exiftool hisobot.pdf
exiftool -a -G1 -s rasm.jpg
pdfinfo hujjat.pdf
strings fayl.bin | less
```

## Office hujjatlarini qo'lda ochish
DOCX/XLSX/PPTX — bu ZIP arxiv:

```bash
unzip -l hujjat.docx
unzip -p hujjat.docx docProps/core.xml
unzip -p hujjat.docx docProps/app.xml
```

`core.xml` ichida: `dc:creator`, `cp:lastModifiedBy`, `dcterms:created`, `dcterms:modified`.

## Metadata tozalash (o'z himoyangiz)
Faylni yuborishdan oldin metadatanı olib tashlang:

```bash
# Bitta fayl
mat2 rasm.jpg              # tozalangan nusxa yaratadi
exiftool -all= rasm.jpg    # joyida o'chiradi (ehtiyotkorlik bilan!)

# Office
# Word: File → Info → Inspect Document → Remove All
```

⚠️ `exiftool -all=` faylni **joyida** o'zgartiradi — avval zaxira nusxa oling.

## Metadata va qonuniy chegaralar
- Faqat **ochiq manbalardan** olingan fayllarni tahlil qiling
- Boshqalarning shaxsiy hujjatlarini ommaga chiqarmang
- Metadata'dagi ism/manzil — shaxsiy ma'lumot; uni e'lon qilish huquqiy oqibatlarga olib kelishi mumkin
- Maqsad: xavfsizlik auditi, jurnalistika, himoya — emas: doxxing

## Kod: `file_metadata.py`
→ [kod/file_metadata.py](kod/file_metadata.py)

Skript nimalarni qiladi:
- Fayl hajmi, turi, SHA-256 va vaqt belgilari
- PDF: Author, Creator, Producer, Title, Subject, sanalar
- DOCX/XLSX/PPTX: `core.xml` va `app.xml` maydonlari + izohlar soni
- ZIP: arxiv comment va fayllar ro'yxati
- ExifTool o'rnatilgan bo'lsa — to'liq metadata JSON ko'rinishida
- `--json` bilan natijani saqlash

O'rganadigan narsalar:
- Fayl imzosi va kengaytma har doim mos kelavermasligi
- ZIP/XML va PDF ichki tuzilishi
- `subprocess` orqali tashqi vositalarni xavfsiz chaqirish
- Metadata maydonlarini xavfsizlik nuqtai nazaridan baholash

## Mashqlar
→ [mashqlar.md](mashqlar.md)
