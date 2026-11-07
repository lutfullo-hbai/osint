# 8-modul: Anonimlik va o'z himoyangiz

## Nazariya: Anonimlik — bu sehr emas, boshqaruv
To'liq anonimlik degan sehrli tugma yo'q. Anonimlik — bu **izlarni kamaytirish
va ularni bir-biriga bog'lashni qiyinlashtirish** amaliyoti.

```
Siz ──► Qurilma ──► Brauzer ──► Tarmoq ──► Platforma ──► Kontent
        │           │           │           │
      OS izi    fingerprint    IP/DNS     akkaunt     til/uslub
```

Eng muhim savol: **kimdan yashirinmoqdasiz?** (threat model)

| Raqib | Nimani ko'radi | Qarshi chora |
|-------|----------------|--------------|
| Tasodifiy odam | Ochiq profil, username | Profil maxfiyligi, username ajratish |
| Ish beruvchi | Ish vaqti, qurilma, tarmoq | Vaqt/joy ajratish, alohida qurilma |
| Platforma | IP, fingerprint, akkaunt tarixi | Tor, alohida brauzer, yangi akkaunt |
| ISP / provayder | DNS, SNI, trafik hajmi | VPN + encrypted DNS, Tor |
| Davlat darajasidagi kuzatuv | Ko'p qatlamli metadata | Tails/Whonix, faoliyat ajratish |

⚠️ Qonuniy tadqiqotda ham **qonun doirasida** qoling. Anonimlik vositalari
jinoyat yoki ta'qib uchun emas, **shaxsiy himoya va xavfsiz tadqiqot** uchun.

## 1. Tarmoq qatlami

| Vosita | Nimani yashiradi | Nimani yashirmaydi |
|--------|------------------|--------------------|
| VPN | ISP'dan manzilni, IP'ni | VPN provayderi, brauzer izlari |
| Tor | IP va yo'nalishni (3 hop) | Kirish/chiqish vaqtini, brauzer xatolari |
| Proxy | IP'ni | Ko'p hollarda trafik shifrlanmagan |

- **VPN** — oddiy maxfiylik uchun qulay, lekin provayderga ishonish kerak
- **Tor** — kuchliroq, lekin sekin; **Tor Browser** bilan birga ishlatiladi
- **DNS leak** — VPN yoqilgan bo'lsa ham DNS so'rovlari ochiq ketishi mumkin
- **WebRTC leak** — brauzer haqiqiy IP'ni oshkor qilishi mumkin

Tekshirish: https://ipleak.net, https://dnsleaktest.com, https://browserleaks.com/webrtc

## 2. Brauzer fingerprint

Brauzer o'zini noyob "barmoq izi" orqali tanitadi:
- User-Agent, ekran o'lchami, vaqt zonasi, til
- Shriftlar, canvas/WebGL render natijasi
- O'rnatilgan kengaytmalar, cookie'lar, localStorage

Bir xil IP va bir xil fingerprint — akkauntlar bog'lanishining asosiy sababi.

Tekshirish: https://amiunique.org, https://coveryourtracks.eff.org

**Amaliy qoida:** turli akkauntlar uchun **turli brauzer profillari** (yoki
konteynerlar) ishlating; ular orasida hech qachon login/parol almashmang.

## 3. Akkaunt gigienasi

- Har bir akkaunt uchun **noyob username** (bir xil nik qayta ishlatilmasin)
- Har bir xizmat uchun **noyob parol** + password manager
- **2FA** (ilova yoki apparat kaliti; SMS — zaifroq)
- Email **alias**lar (SimpleLogin, AnonAddy) — asosiy emailni yashirish
- Tiklash savollari — yolg'on, lekin eslab qolinadigan javoblar
- Profil rasmi — boshqa akkauntlarda ishlatilgan rasmni qayta ishlatmang (teskari qidiruv!)

## 4. Tadqiqot OPSEC (sock puppet)

Tadqiqot uchun alohida "persona" yarating:

1. **Alohida qurilma yoki VM** — asosiy shaxsiy akkauntlar bilan aralashmasin
2. **Alohida brauzer profili** — hech qanday shaxsiy login yo'q
3. **Alohida email** — alias orqali
4. **Alohida tarmoq** — VPN/Tor, agar maqsadga mos bo'lsa
5. **Hech qanday aloqa** — like, follow, izoh, xabar yubormang
6. **Vaqtni ajratish** — faoliyat vaqti odatiy ish vaqtingizga to'g'ri kelmasin
7. **Til va uslub** — qisqa, neytral; shaxsiy jargonlardan foydalanmang
8. **Dalillarni saqlash** — skrinshot + URL + vaqt; muhim sahifalarni arxivlang

⚠️ "Ko'rish" ham iz qoldiradi: profil ko'rishlar, story'lar, read receipt'lar.

## 5. Fayl va metadata
- Fayl yuborishdan oldin EXIF/metadata'ni tozalang (7-modul)
- Rasmning **perceptual hash**i o'zgarmaydi — bir xil rasm turli platformalarda bog'lanadi
- Hujjat ichida username, kompaniya, yo'l qolmasin

## 6. Insidentga javob (agar oshkor bo'lsangiz)
1. **To'xtang** — yangi harakatlar izni ko'paytiradi
2. **Baholang** — nima oshkor bo'ldi? (IP, akkaunt, metadata)
3. **Ajrating** — bog'langan akkauntlarni uzib qo'ying
4. **Almashtiring** — parollar, 2FA, aliaslar
5. **Hujjatlashtiring** — nima, qachon, qanday sodir bo'ldi
6. **Xabar bering** — agar shaxsiy ma'lumot tarqalgan bo'lsa, platforma/qonuniy choralar

## Kod: `opsec_check.py`
→ [kod/opsec_check.py](kod/opsec_check.py)

Skript nimalarni qiladi:
- **Tarmoq tekshiruvi** (`--network`): tashqi IP, geo, hosting/proxy belgisi, Tor holati
- **Parol auditi** (`--passwords fayl`): uzunlik, entropiya, zaif naqshlar va takrorlanish
- Parollarni ekranga chiqarmaydi — faqat qator raqami va hash qismi
- **Checklist**: fingerprint, DNS leak va WebRTC test havolalari

O'rganadigan narsalar:
- Threat modelni amaliy tekshirish
- Parol entropiyasi va takrorlanish xavfi
- Tashqi IP va proxy/hosting farqi
- Xavfsizlikni avtomatik audit qilish asoslari

## Mashqlar
→ [mashqlar.md](mashqlar.md)
