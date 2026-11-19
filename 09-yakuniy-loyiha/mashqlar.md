# 9-modul: Yakuniy loyiha — bosqichlar

Loyiha: **o'zingiz haqida to'liq profil tekshiruvi** (self-OSINT) va himoya rejasi.
Muddat: 1–2 hafta, kuniga ~1 soat. Natija: hisobot + dalil jurnali.

Ish papkasi yarating (git'ga **joylamang** — unda shaxsiy ma'lumot bor):
```bash
mkdir -p ~/self-osint && cd ~/self-osint
cp /path/to/osint/09-yakuniy-loyiha/shablon/hisobot.md hisobot.md
alias dalil="python3 /path/to/osint/09-yakuniy-loyiha/kod/evidence_log.py"
```

## Bosqich 0: Doira va rozilik ⭐
`hisobot.md` dagi "Doira" bo'limini to'ldiring:
1. Obyekt: o'zingiz (yoki [rozilik.md](shablon/rozilik.md) imzolangan shaxs)
2. 3–5 ta **savol**, masalan:
   - Begona odam mening ish joyimni topa oladimi?
   - Qaysi akkauntlarim bir-biriga bog'lanadi?
   - Telefon raqamim yoki manzilim ochiq yozilganmi?
3. Taqiqlar ro'yxati (1-bo'lim, nazariya.md) — ko'chirib qo'ying

**Topshiriq:** doira va savollar yozilgan.

## Bosqich 1: Seed va brauzer tayyorlash ⭐
1. 8-moduldagi kabi **alohida brauzer profili** oching (shaxsiy login yo'q)
2. Begona odam nimadan boshlaydi? Odatda **ism + shahar** yoki bitta **username**
3. Seed'larni yozing: ism (barcha yozilishlari: lotin, kirill, `o'`/`o‘`), username'lar, email'lar

**Topshiriq:** seed ro'yxati.

## Bosqich 2: To'plash ⭐⭐
Har bir modul usulini qo'llang. **Har bir topilma darhol jurnalga:**
```bash
dalil add https://github.com/USERNAME --note "username, ism, shahar" --fetch --save
```

| Modul | Nima qilish |
|-------|-------------|
| 1 | Google dork: `"Ism Familiya"`, `"username"`, `site:t.me "username"`, `filetype:pdf "Ism Familiya"` |
| 2 | `02-username-email/kod/username_checker.py`, Sherlock/Maigret |
| 3 | `"+998 XX XXX XX XX"` turli yozilishda qidiruv (akkaunt tekshiruvi emas!) |
| 4 | Profil rasmlaringizni teskari qidiruv (Google Lens, Yandex, TinEye) |
| 5 | Shaxsiy sayt / domen: `05-domen-ip/kod/domain_info.py`, Wayback |
| 6 | Har bir ijtimoiy tarmoqda profilingizni **tashqaridan** ko'ring (chiqib, yoki boshqa brauzerda) |
| 7 | Siz yozgan hujjatlar (PDF, DOCX): `07-metadata-fayllar/kod/file_metadata.py` |

NEXUS bilan (ixtiyoriy, tavsiya etiladi):
1. **Name** yoki **Username** tabida qidiring → natijada **Export JSON**
2. **Agent** tabida: "Ism Familiya, shahar, username" — natija tayyor bo'lgach,
   run JSON'ini oling (run ID — Data tabidagi ro'yxatda yoki brauzer manzilida):
```bash
curl -s http://localhost:8000/api/agent/RUN_ID -o agent-run.json
```
3. Jurnalga import qiling (har bir manbali yozuv olingan vaqti bilan keladi):
```bash
dalil import osint-ism.json
dalil import agent-run.json
```

**Topshiriq:** kamida 15 ta dalil jurnalda.

## Bosqich 3: Qayta ishlash ⭐⭐
1. `dalil list` — takrorlar, keraksiz yozuvlar bormi?
2. Har bir dalilga **baho** bering (nazariya.md, 5-bo'lim):
```bash
dalil grade D004 B2
```
3. Baholanmagan dalil qolmasin: `dalil report` oxirida ⚠️ chiqmasin

**Topshiriq:** barcha dalillar baholangan.

## Bosqich 4: Tahlil ⭐⭐⭐
1. **Pivot daraxtini** chizing (qo'lda yoki NEXUS GraphML → Gephi/yEd)
2. Har bir chiziqqa bog'lanish sababini yozing
3. Kamida **2 ta yolg'on topilma** toping: sizning ismingiz, lekin boshqa odam.
   Qaysi belgi bo'yicha ajratdingiz? (shahar, yosh, rasm, kasb)
4. **Xavfli birikmalar**: alohida zararsiz, birga xavfli ma'lumotlar
   (masalan: maktab + mahalla + kun tartibi)
5. Savollaringizga (Bosqich 0) javob bering: ha / yo'q / qisman + dalil ID

**Topshiriq:** daraxt, 2 ta yolg'on topilma tahlili, xavf ro'yxati.

## Bosqich 5: Hisobot ⭐⭐
1. `hisobot.md` shablonini to'ldiring
2. Ilova:
```bash
dalil verify                      # nusxalar o'zgarmagan
dalil report -o ilova-dalillar.md
```
3. Hisobotdagi **har bir fakt** yonida dalil ID bo'lsin: `(D007)`
4. "Topilmadi" bo'limini to'ldiring — bu ham natija

**Topshiriq:** hisobot + ilova.

## Bosqich 6: Himoya ⭐⭐
Xavf ro'yxatidagi har bir band uchun chora (nazariya.md, 8-bo'lim):

| Topilma | Xavf | Chora | Bajarildi |
|---------|------|-------|-----------|
| D007 telefon forumda | yuqori | admin'ga o'chirish so'rovi | ⬜ |
| D012 eski Instagram | o'rta | akkauntni yopish | ⬜ |

**Topshiriq:** kamida 3 ta chora bajarilgan.

## Bosqich 7: Tozalash va qayta tekshirish ⭐
1. NEXUS'da: **Data** tabi → keraksiz Agent run'larni o'chiring; Cases → case'ni o'chiring
2. Audit log'da nima qidirganingizni ko'ring — hisobotdagi "Usul" bilan mos kelsinmi?
3. Kalendarga eslatma: **3 oydan keyin** shu jurnal bilan qayta tekshirish
   (`dalil add ... --fetch` — sahifa hash'i o'zgardimi, sahifa yo'qoldimi?)

## Baholash mezonlari

| Mezon | Ball |
|-------|------|
| Doira va savollar aniq, taqiqlar yozilgan | 10 |
| Kamida 15 dalil, har biri URL + vaqt + baho | 20 |
| 7 modul usulidan kamida 5 tasi qo'llangan | 15 |
| Pivot daraxti va bog'lanish sabablari | 15 |
| Yolg'on topilmalar va qarama-qarshiliklar tahlili | 15 |
| Hisobotda har bir fakt dalil ID bilan; "Topilmadi" bo'limi | 15 |
| Himoya rejasi, kamida 3 ta bajarilgan chora | 10 |
| **Jami** | **100** |

**Avtomatik 0 ball:** doiradan tashqari shaxs rozilisiz tekshirilgan, sizib chiqqan
baza yoki parol bilan kirish ishlatilgan, hisobot ommaga joylangan.

## Topshirish
Hisobotni menga ko'rsating (shaxsiy ma'lumotlarni `[yashirildi]` bilan almashtirib) —
birga tahlil qilamiz: nima o'tkazib yuborildi, qaysi xulosa zaif.

🎓 Tabriklaymiz — bu kursning oxirgi moduli!
