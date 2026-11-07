# 5-modul: Mashqlar

## Mashq 1: Kutubxonalarni o'rnatish ⭐
```bash
pip install dnspython requests
```

## Mashq 2: Skriptni ishga tushirish 🎯 (KOD!)
```bash
python3 05-domen-ip/kod/domain_info.py example.com
```
Savollar:
1. Nechta subdomen topildi? Ular orasida qiziqarlisi bormi?
2. `Server` sarlavhasida nima yozilgan? CDNmi?
3. RDAP'da registrar va yaratilgan sana qanday?

## Mashq 3: DNS yozuvlarini qo'lda tekshirish ⭐
```bash
dig example.com A
dig example.com MX
dig example.com TXT
dig example.com NS
```
- `TXT` ichida SPF (`v=spf1`) bormi?
- MX qaysi provayderga ishora qiladi?
- NS va RDAP'dagi nameserverlar mos keladimi?

## Mashq 4: WHOIS va RDAP solishtirish ⭐⭐
```bash
whois example.com
curl -s https://rdap.org/domain/example.com | python3 -m json.tool | head -40
```
- Qaysi maydonlar bir xil?
- Qaysi biri o'qish uchun qulay?
- Registrant egasi ko'rinyaptimi? Nega?

## Mashq 5: Subdomenlarni tasdiqlash ⭐⭐
crt.sh'dan topilgan 2-3 subdomenni tanlang va faqat **passiv** tekshiring:
```bash
curl -I https://subdomen.example.com
```
- Javob beradimi? Qaysi status?
- Qaysi biri `dev`, `test`, `admin` kabi nomga ega?

⚠️ Topilgan tizimga kirishga urinmang — faqat ochiq HTTP javobini o'qing.

## Mashq 6: Web texnologiyalar ⭐⭐
```bash
curl -I https://example.com
curl https://example.com/robots.txt
curl https://example.com/sitemap.xml
```
Topshiriq:
- [ ] `Server` va `X-Powered-By` ni yozing
- [ ] Xavfsizlik sarlavhalari bor-yo'qligini tekshiring
- [ ] `robots.txt` yashirgan sahifalarni toping
- [ ] https://securityheaders.com da baho oling

## Mashq 7: TLS sertifikat ⭐⭐
```bash
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```
- Sertifikat kim tomonidan berilgan?
- SAN ro'yxatida qanday domenlar bor?
- Muddat qachon tugaydi?

## Mashq 8: Arxiv va skanerlar ⭐⭐
1. https://web.archive.org da domenning eski versiyasini oching — nima o'zgargan?
2. https://urlscan.io da domenni qidiring — qanday texnologiyalar ko'rinadi?
3. O'z domeningiz uchun `urlscan.io/domain/<domen>` sahifasini yozib oling.

## Mashq 9: Favicon orqali qidirish ⭐⭐⭐
Bir xil ilova ishlatadigan saytlarni favicon hash orqali topish mumkin:
```bash
pip install mmh3
python3 - <<'PY'
import base64, mmh3, requests
data = requests.get("https://example.com/favicon.ico", timeout=10).content
print(mmh3.hash(base64.encodebytes(data)))
PY
```
Natijani Shodan'da `http.favicon.hash:<hash>` ko'rinishida qidiring.
- Nechta boshqa domen bir xil faviconga ega?
- Bu qanday xulosa beradi? (bir xil CMS/framework)

## Mashq 10: Skriptni kengaytirish 🎯⭐⭐ (KOD!)
[domain_info.py](kod/domain_info.py) ga quyidagilarni qo'shing:
- [ ] `--json` rejimi: natijani JSON faylga saqlash
- [ ] SPF/DMARC holatini alohida xulosalash (bor/yo'q + policy)
- [ ] Subdomenlarni parallel tekshirish (faqat HEAD so'rov, 5 ta bir vaqtda)
- [ ] `--skip-crtsh` bayrog'i (sekin manbani o'chirish)
- [ ] IP → ASN/geo ma'lumotini qo'shish (ip-api.com kabi ochiq API)

## Mashq 11: Passiv infratuzilma hisoboti 🎯⭐⭐
Ochiq tashkilot domenini tanlang (masalan, universitet yoki davlat sayti) va hisobot tuzing:
1. DNS va MX provayderi
2. Registrar va domen yoshi
3. 5 ta subdomen + ularning vazifasi (taxmin)
4. Web server va texnologiyalar
5. Xavfsizlik sarlavhalari holati
6. Xulosa: qanday zaifliklar ehtimoliy?

⚠️ Faqat ochiq ma'lumotlar. Hech qanday faol skanerlash yoki kirish urinishi yo'q.

---

✅ Keyingi modul: **Ijtimoiy tarmoqlar razvedkasi (SOCMINT)**
