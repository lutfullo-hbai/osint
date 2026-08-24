# 3-modul: Telefon raqami izlash (PHONEINT)

## Nazariya: Raqam nimani aytib beradi?
Telefon raqami tasodifiy emas — u **strukturaga ega**:

```
+998 90 123 45 67
 │   │  └─── abonent raqami
 │   └────── operator kodi → operatorni aniqlaydi!
 └────────── mamlakat kodi (+998 = O'zbekiston)
```

### O'zbekiston operator kodlari
| Kod | Operator |
|-----|----------|
| 90, 91 | Beeline |
| 93, 94 | Ucell |
| 97 | Mobiuz (Uzmobile GSM) |
| 98, 88 | Uzmobile / Humans |
| 99 | Uzmobile (CDMA) |
| 71, 78 | Qutug'i (Toshkent) |

⚠️ **Muhim:** MNP (raqam ko'chirish) tufayli kod hamesha aniq operatorni bermasligi mumkin.

## Qidirish usullari (eng zaifdan kuchligacha)

### 1. Format analizi (kod bilan)
- Mamlakat, operator, raqam to'g'riligini aniqlash
- Vosita: `phonenumbers` Python kutubxonasi

### 2. Messenger tekshiruvi
Raqam qaysi messengerlarda band — shu odamning raqami ekanini ko'rsatadi:
- **Telegram:** `t.me/+998901234567` → profil ochilsa, band
- **WhatsApp:** kontakt qilib ko'rish, profil rasm chiqishi
- ⚠️ Buning uchun o'z raqamingiz kerak bo'ladi — anonimlik uchun ikkinchi SIM ishlating

### 3. Qidiruv tizimlari
Raqamni turli formatlarda Google'da qidiring:
```
"+998 90 123 45 67"
"998901234567"
"90 123 45 67"
```
E'lon saytlari (OLX), forumlar, hujjatlarda uchrasa — topiladi!

### 4. Maxsus xizmatlar
| Xizmat | Nima beradi |
|--------|-------------|
| sync.me | Ijtimoiy tarmoq bog'lanishlari |
| truecaller.com | Abonent nomi (jamoa bazasi) |
| epieos.com | Email/Google akkaunt bog'lanishi |
| phoneinfoga (GitHub) | Skript, ko'p manbali |

⚠️ Truecaller natijalarini har doim tekshirib boring — noto'g'ri nomlar ham uchraydi.

### 5. Breach ma'lumotlari
Sizgan bazalarda raqam bilan birga ism, manzil bo'lishi mumkin.
⚠️ Bu yerda qonuniy chegaralar juda muhim — faqat o'z raqamingizni tekshiring!

## OPSEC eslatma
- Raqamni tekshirishda o'z asosiy akkauntingizdan foydalanmang
- Telegram/WhatsApp tekshiruvda soxta raqam (virtual SIM) ishlatgan yaxshi
- Hech qachon topilgan shaxsga qo'ng'iroq qilmang — bu OSINT emas, tahdid!

## Kod: `phone_info.py`
→ [kod/phone_info.py](kod/phone_info.py)

O'rganadigan narsalar:
- `phonenumbers` kutubxonasi bilan raqam parsing
- Mamlakat, operator, tur, vaqt zonasini olish
- Ko'p raqamni birdan tahlil qilish (argument orqali)
