# 8-modul: Mashqlar

## Mashq 1: Self-audit checklist ⭐
```bash
python3 08-anonimlik/kod/opsec_check.py
```
Har bir bandni o'zingiz uchun baholang. Qaysi biri eng zaif bo'g'in?

## Mashq 2: Parol auditi 🎯 (KOD!)
**Haqiqiy parollaringizni faylga yozmang!** Demo ro'yxat yarating:
```
password123
qwerty2024
Ali2020!
correct-horse-battery-staple
Tr0ub4dor&3-Uzun-Parol!
qwerty2024
```
```bash
python3 08-anonimlik/kod/opsec_check.py --passwords demo.txt
```
Savollar:
1. Qaysi parollar zaif deb belgilandi?
2. Takrorlangan parol bormi?
3. Entropiya 60 bitdan past bo'lsa nima uchun xavfli?

## Mashq 3: Parollarni yaxshilash ⭐⭐
Demo faylni tahrirlang:
- Har bir zaif parolni uzun passphrase bilan almashtiring (4-5 so'z)
- Takrorni yo'q qiling
- Qayta audit qiling — barchasi "yaxshi" chiqdimi?

## Mashq 4: Tarmoq tekshiruvi ⭐⭐
```bash
python3 08-anonimlik/kod/opsec_check.py --network
```
1. Tashqi IP va joylashuvni yozib oling
2. VPN yoqing (agar mavjud bo'lsa) va qayta tekshiring
3. `Proxy`, `Hosting`, `Tor` maydonlari o'zgardimi?
4. IP qaysi ISP/ASN'ga tegishli?

## Mashq 5: Tor bilan solishtirish ⭐⭐⭐
1. Tor Browser'ni o'rnating va ishga tushiring
2. https://check.torproject.org sahifasini oching
3. CLI bilan solishtiring:
```bash
python3 08-anonimlik/kod/opsec_check.py --network
```
- IP o'zgardimi?
- Tezlik qanday farq qildi?
- Qaysi holatda qaysi vositani ishlatasiz?

## Mashq 6: DNS va WebRTC leak ⭐⭐
Brauzerda oching:
- https://dnsleaktest.com — DNS so'rovlari qayerdan ketmoqda?
- https://browserleaks.com/webrtc — haqiqiy IP ko'rinadimi?
- https://ipleak.net — barcha qatlamlarni birga tekshiring

VPN yoqilgan va o'chirilgan holatda natijalarni solishtiring.

## Mashq 7: Brauzer fingerprint ⭐⭐
1. https://amiunique.org da fingerprintingizni ko'ring
2. Boshqa brauzerda (yoki inkognito + boshqa profil) qayta tekshiring
3. https://coveryourtracks.eff.org da "tracking" natijasini o'qing

Savol: ikki profil fingerprinti bir xilmi? Nega?

## Mashq 8: Sock puppet rejasi ⭐⭐⭐
Platformada akkaunt ochmasdan, reja tuzing:
- [ ] Maqsad va threat model
- [ ] Alohida brauzer profili nomi
- [ ] Email alias (SimpleLogin/AnonAddy)
- [ ] Noyob username
- [ ] Tarmoq tanlovi (uyda/VPN/Tor)
- [ ] Qaysi harakatlar taqiqlanadi (like/follow/izoh)
- [ ] Dalillarni saqlash usuli

## Mashq 9: Metadata va rasm izi ⭐⭐
1. `07-metadata-fayllar/kod/file_metadata.py` bilan rasmni tozalang
2. Bir xil rasmni ikki xil nom bilan saqlang
3. `imagehash` bilan perceptual hash solishtiring:
```bash
pip install imagehash pillow
python3 - <<'PY'
import imagehash
from PIL import Image
print(imagehash.phash(Image.open("rasm1.jpg")))
print(imagehash.phash(Image.open("rasm2.jpg")))
PY
```
- Hash'lar bir xilmi? Metadata o'chirilgandan keyin ham rasm tanilinadimi?

## Mashq 10: Pwned Passwords (k-anonymity) ⭐⭐⭐
Parolni to'liq yubormasdan sizib chiqqanligini tekshirish:
```python
import hashlib
import requests

password = "demo-parol"
digest = hashlib.sha1(password.encode()).hexdigest().upper()
prefix, suffix = digest[:5], digest[5:]
response = requests.get(f"https://api.pwnedpasswords.com/range/{prefix}", timeout=10)
for line in response.text.splitlines():
    part, count = line.split(":")
    if part == suffix:
        print(f"Parol {count} marta sizgan bazalarda uchradi!")
        break
else:
    print("Bu parol topilgan bazalarda yo'q.")
```
- Nega faqat SHA-1 prefiksi yuboriladi?
- Bu nega xavfsiz usul hisoblanadi?

## Mashq 11: Insident stsenariysi ⭐⭐⭐
Faraz qiling: tadqiqot akkauntingiz ostidagi IP oshkor bo'ldi. Yozma javob rejasini tuzing:
1. Nima oshkor bo'ldi?
2. Qaysi akkauntlar bog'langan edi?
3. Qanday darhol choralar (parol, 2FA, ajratish)?
4. Kimga xabar berish kerak?
5. Kelajakda qanday oldini olish mumkin?

---

✅ Keyingi modul: **Yakuniy loyiha — to'liq profil tekshiruvi**
