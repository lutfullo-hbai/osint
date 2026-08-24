# 2-modul: Username va Email izlash

## Nazariya: Nega bu ishlaydi?
Odamlar ko'p platformalarda **bir xil username** dan foydalanadi. Bitta usernameni topsangiz — boshqa akkauntlarini ham topish mumkin.

## Username qidirish vositalari

### 1. Sherlock (Python skript)
400+ saytda username tekshiradi:
```bash
pip install sherlock-project
sherlock username_bu_yerda
```

### 2. Veb-saytlar (kod yozmasdan)
| Sayt | Nima qiladi |
|------|-------------|
| whatsmyname.app | 600+ saytda tekshiradi |
| instantusername.com | Tez tekshiruv |
| namecheckup.com | Domen + ijtimoiy tarmoq |

## Email manzil tekshirish

### Email mavjudligini tekshirish
- **holehe** — email ro'yxatdan o'tgan saytlarni topadi:
```bash
pip install holehe
holehe email@example.com
```

### Email formatini taxmin qilish
Kompaniyalarda email formatlari standart:
- `ism.familiya@kompaniya.uz`
- `i.familiya@kompaniya.uz`
- `familiya@kompaniya.uz`

Hunter.io orqali kompaniya formatini aniqlash mumkin.

### Breach (o'tkazib yuborilgan ma'lumotlar) bazalari
- **haveibeenpwned.com** — email sizgan bazalarda bormi?
- ⚠️ Bu ma'lumotlardan faqat o'z hisoblaringizni himoya qilish uchun foydalaning

## Kod: O'z username tekshirgichimiz yozamiz!
→ [kod/username_checker.py](kod/username_checker.py)

Skript oddiy mantiqda ishlaydi:
1. Foydalanuvchi usernameni kiritadi
2. Skript bir nechta saytga so'rov yuboradi
3. HTTP javob kodiga qarab: `200` = band, `404` = bo'sh

O'rganadigan narsalar:
- `requests` kutubxonasi bilan HTTP so'rovlar
- HTTP status kodlari
- Exception handling (sayt ochilmasa)

### ⚠️ Muhim dars: False Positive (soxta musbat)
Sinovda skript Instagram'da mavjud bo'lmagan usernameni ham "TOPILDI" dedi!
Sababi: ba'zi saytlar **har doim 200** qaytaradi (login sahifasiga yo'naltiradi).

Xulosa — **OSINTning oltin qoidasi:** avtomatik vosita *gipoteza* beradi,
*tasdiqlash* har doim qo'lda (brauzerda) bajariladi. Vosita natijasiga ko'r-ko'rona ishonmang!

## Mashqlar
→ [mashqlar.md](mashqlar.md)
