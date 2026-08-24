# 1-modul: OSINT Asoslari

## OSINT nima?
**OSINT** (Open Source Intelligence) — ochiq, jamoat manbalaridan ma'lumot to'plash, tahlil qilish va foydali xulosalar chiqarish jarayoni.

### Ochiq manbalar qaysilar?
- Ijtimoiy tarmoqlar (Telegram, Instagram, Facebook...)
- Veb-saytlar, bloglar, forumlar
- Davlat reyestrlari va ochiq ma'lumotlar bazalari
- Whois, DNS yozuvlari
- Rasmlar, videolar (YouTube, TikTok)
- Ochil manbali ma'lumot oqimlari (Shodan va h.k.)

## Razvedka tsikli (Intelligence Cycle)
Har bir OSINT tadqiqoti shu 5 bosqichdan o'tadi:

```
1. REJA      → Nima topmoqchiman? Qanday savolga javob kerak?
2. TO'PLASH  → Ma'lumot manbalarini yig'amiz
3. QAYTA ISHLASH → Saralash, tozalash
4. TAHLIL    → Bog'lanishlarni topish, xulosalar
5. HISBOT    → Natijani rasmiylashtirish
```

**Muhim:** Rejasiz to'plash — bu "ma'lumot axlatxonasi". Har doim aniq savol bilan boshlang.
Masalan: *"Bu username kimniki ekan?"* — emas, *"Bu shaxs qayerda ishlaydi?"*

## OSINT turlari (soha bo'yicha)
| Turi | Nomlanishi | Obyekti |
|------|-----------|---------|
| SOCMINT | Social Media Intelligence | Ijtimoiy tarmoqlar |
| GEOINT | Geospatial Intelligence | Joylashuv, xaritalar |
| IMINT | Imagery Intelligence | Rasmlar, sun'iy yo'ldosh |
| PHONEINT | Phone Number Intelligence | Telefon raqamlari |
| HUMINT | Human Intelligence | Odamlar bilan suhbat |
| TECHINT | Technical Intelligence | Domen, IP, serverlar |

## OPSEC — o'zingizni himoya qilish
Tadqiqot qilayotganda **siz ham kuzatilishingiz mumkin!**

Asosiy qoidalar:
1. **Anonim brauzer** ishlating (Tor Browser yoki VPN + Firefox)
2. **O'z akkauntingizdan** qidiruv qilmang — alohida "sock puppet" (soxta profil) yarating
3. **Logging** ni o'chirib qo'ying
4. Shubhali saytlarga **VM (Virtual Machine)** dan kiring
5. Hech qachon maqsad shaxsga **to'g'ridan-to'g'ri murojaat qilmang**

## Google Dorking — eng kuchli qurol
Google qidiruvining maxsus operatorlari:

| Operator | Misol | Natija |
|----------|-------|--------|
| `site:` | `site:t.me osint` | Faqat Telegram kanallarda |
| `filetype:` | `filetype:pdf parol` | PDF fayllarni topadi |
| `"..."` | `"ism familiya"` | Aniq iborani topadi |
| `-` | `osint -kurs` | So'zni chiqarib tashlaydi |
| `intitle:` | `intitle:index.of` | Katalog ro'yxatlari |
| `inurl:` | `inurl:admin` | URL'da so'z bor sahifalar |

## Mashqlar
→ [mashqlar.md](mashqlar.md) ga o'ting
