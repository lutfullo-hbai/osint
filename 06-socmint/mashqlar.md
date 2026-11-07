# 6-modul: Mashqlar

## Mashq 1: Kutubxonalarni o'rnatish ⭐
```bash
pip install requests
```

## Mashq 2: Skriptni ishga tushirish 🎯 (KOD!)
```bash
python3 06-socmint/kod/social_profile.py sizning_username
```
Savollar:
1. Nechta platformada `TOPILDI` chiqdi?
2. `NOANIQ` natijalar qaysi platformada va nega?
3. Qo'lda tekshirish ro'yxatidagi havolalarni ochib ko'ring.

## Mashq 3: Maigret bilan solishtirish ⭐⭐
```bash
pip install maigret
maigret sizning_username --html
```
- Skriptingiz topmagan, Maigret topgan platformalar bormi?
- Nega farq bor? (Maigret ko'proq sayt biladi)

## Mashq 4: False positive tahlili ⭐⭐
`social_profile.py` dagi `SITES` ga bitta yangi platforma qo'shing:
- Avval 404 qaytaradigan saytni tanlang
- Keyin 200 qaytaradigan, lekin "topilmadi" yozadigan saytni sinang

Savol: status kodiga qarab xulosa qilish qachon xato beradi?

## Mashq 5: Telegram kanalini tahlil qilish ⭐⭐
Ochiq kanal tanlang (masalan, yangiliklar kanali) va login qilmasdan o'qing:
```
https://t.me/s/kanal_nomi
```
Topshiriq:
- [ ] Kanal nomi, tavsifi va obunachilar soni
- [ ] Postlar chastotasi (kuniga nechta?)
- [ ] Qaysi vaqtlarda faol? (vaqt zonasi taxmini)
- [ ] Postlar qayerdan forward qilingan?

⚠️ Shaxsiy kanallar yoki yopiq guruhlarga kirishga urinmang.

## Mashq 6: Profil tahlili checklist ⭐⭐
O'zingizning yoki ochiq shaxsning bitta ommaviy profilini tanlang:
- [ ] Ko'rsatilgan ism va bio
- [ ] Profil/fon rasmi — teskari qidiruvga yuboring
- [ ] Ro'yxatdan o'tgan sana (ko'rinadigan bo'lsa)
- [ ] Postlar soni va oxirgi faollik
- [ ] Til, imlo, emoji odatlari
- [ ] Qaysi havolalar ko'rsatilgan (Linktree, sayt)?

## Mashq 7: Follow grafigi (qo'lda) ⭐⭐⭐
Ochiq akkaunt uchun 10-15 ta bog'lanishni jadvalga yozing:

| Profil | Kim bilan | Turi | Izoh |
|--------|-----------|------|------|
| @ali | @vali | follow | doimiy izohlar |
| @ali | @gani | mention | birga rasm |

- Eng ko'p muloqot qiladigan 3 kishini aniqlang
- Ular orasida qanday umumiy mavzu bor?

## Mashq 8: Cross-platform bog'lash ⭐⭐⭐
Bitta shaxsning 2 ta akkauntini toping va bog'lovchi belgilarni yozing:
- [ ] Bir xil username?
- [ ] Bir xil profil rasmi?
- [ ] Bir xil bio havolasi?
- [ ] Bir xil postlar (cross-post)?
- [ ] Bir xil email/telefon?

Xulosa: nechta mustaqil belgi tasdiqlandi? (kamida 2-3 bo'lishi kerak)

## Mashq 9: Vaqt zonasini taxmin qilish ⭐⭐
Bir nechta post vaqtlarini yozib oling:
```
Dushanba 09:14, 13:40, 22:05
Seshanba 08:55, 18:20
```
- Faollik oralig'i qaysi soatlarga to'g'ri keladi?
- Taxminiy vaqt zonasi qanday?
- Bu boshqa manbalar bilan mos keladimi?

## Mashq 10: Skriptni kengaytirish 🎯⭐⭐ (KOD!)
[social_profile.py](kod/social_profile.py) ga quyidagilarni qo'shing:
- [ ] `--only github,gitlab` orqali platformalarni tanlash
- [ ] Natijani CSV'ga saqlash
- [ ] Har bir natijaga "ishonch darajasi" qo'shish (status + marker asosida)
- [ ] Parallel tekshiruv (5 ta bir vaqtda, lekin rate limitga rioya)
- [ ] `--manual` rejimi: faqat qo'lda havolalarni chiqarish

## Mashq 11: Passiv SOCMINT hisoboti 🎯⭐⭐
Ochiq tashkilot yoki jamoat arbobi sahifasini tanlab, hisobot tuzing:
1. Platformalar ro'yxati va profillar
2. Faollik davri va vaqt zonasi
3. Asosiy mavzular (postlar tahlili)
4. Bog'langan shaxslar/tashkilotlar
5. Ishonch darajasi: qaysi xulosa tasdiqlangan, qaysi biri taxmin?

⚠️ Hisobotni faqat o'zingiz uchun saqlang. Shaxsiy ma'lumotlarni ommaga chiqarmang.

---

✅ Keyingi modul: **Metaqidalar (metadata) va fayllar**
