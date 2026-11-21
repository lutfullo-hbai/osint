# heretic — modelni o'zgartirish (alohida vosita)

[heretic](https://github.com/p-e-w/heretic) (AGPL-3.0, versiya 2.1.0) til modelining xulqini qayta
o'qitmasdan o'zgartiradi. Bu **NEXUS'dan alohida** vosita: NEXUS uni import qilmaydi, chaqirmaydi va
uning kodini ko'chirmaydi (AGPL shart). U faqat o'zgartirilgan modelni diskka yozadi; uni Ollama'ga
qo'shish yoki qo'shmaslik — sizning qaroringiz.

## Talablar
- NVIDIA GPU (RTX 5060 8 GB'da tekshirilgan: torch CUDA'ni ko'radi). GPU'siz amalda ishlamaydi.
- [uv](https://docs.astral.sh/uv/). O'z virtualenv'i shu papkada (`.venv/`, git'ga tushmaydi).
  Barcha paketlar `requirements.lock`'da versiya va hash bilan qotirilgan.
- Model Hugging Face'dan yuklanadi (4B model ~8 GB). 8 GB VRAM'da 4-bit kvantlash kerak
  (`--quantization BNB_4BIT`). Bitta run 30–60 daqiqa.

## 1. Ishga tushirish

    tools/heretic/run.sh Qwen/Qwen3-4B-Instruct-2507 nosyco --quantization BNB_4BIT

`run.sh MODEL [KONFIG] [heretic parametrlari...]` — uchinchi argumentdan keyingisi heretic'ga uzatiladi.

| Konfig | Nima qiladi |
|---|---|
| `nosyco` (standart) | xushomad ("great question", "you're absolutely right") kamayadi: model dalilga qarshi chiqishdan tortinmaydi |
| `noslop` | shablon, suvli iboralar kamayadi |
| `terse` | javoblar qisqaradi |

Upstream'ning standart konfiguratsiyasi (rad etishlarni olib tashlash) **ataylab qo'shilmagan**:
NEXUS haqiqiy odamlar haqida ishlaydi va modelning rad etishi himoya qatlamlaridan biri.

Konfiguratsiya upstream'ning aniq commit'idan yuklanadi va sha256 bilan tekshiriladi; mos kelmasa
skript ishlamaydi. Virtualenv shu versiya uchun to'liq o'rnatilgan bo'lsagina qayta ishlatiladi.

Oxirida heretic modelni saqlash yoki Hugging Face'ga yuklashni taklif qiladi: **faqat `work/` ichiga
saqlang** (git'ga tushmaydi), Hugging Face'ga yuklamang.

## 2. Ollama'ga qo'shish
Natija Hugging Face formatida (safetensors). GGUF'ga o'giring
([llama.cpp](https://github.com/ggml-org/llama.cpp) `convert_hf_to_gguf.py`), keyin:

    echo 'FROM ./model.gguf' > Modelfile && ollama create qwen3-nosyco -f Modelfile

## 3. Rad etish testi (majburiy)
Har qanday o'zgartirish (hatto `nosyco`) rad etishlarni zaiflashtirishi mumkin. NEXUS'ga ulashdan oldin
yangi modelni **va asosiy modelni** tekshiring:

    python3 tools/heretic/check_refusals.py qwen3-nosyco
    python3 tools/heretic/check_refusals.py qwen3:8b

Test model'dan to'qima shaxsning telefoni/emaili/manzilini topish yoki taxmin qilishni so'raydi va
javoblarni chiqaradi. Kalit so'z tekshiruvi faqat birinchi filtr: javoblarni o'zingiz o'qing.
**Yangi model asosiysidan yomonroq bo'lsa, uni ishlatmang.**

Eslatma (2026-11-21): hozirgi `qwen2.5:7b` ham to'g'ridan-to'g'ri so'ralganda ba'zan "taxminiy" email
yoki telefon yozadi. Shuning uchun NEXUS kontaktni hech qachon modelning so'ziga ishonib olmaydi: AI
yozgan email/telefon/havola dalilda so'zma-so'z bo'lmasa tashlanadi (`backend/services/ai.py`).

## 4. Aniqlikni o'lchash va ulash
Modelni `.env`'da tanlang (`OLLAMA_FAST_MODEL=qwen3-nosyco` yoki `OLLAMA_SMART_MODEL`), stack'ni qayta
ishga tushiring va Agent aniqligini o'lchang (asosiy README, "Agent aniqligini o'lchash"):

    docker compose exec backend python scripts/eval_agent.py eval/agent_cases.public.jsonl --out /app/data/eval-reports/nosyco

Natija avvalgi o'lchovdan yomon bo'lsa, eski modelga qayting.

## Litsenziya
heretic'ning AGPL'i natija modelga taalluqli emas, lekin **asosiy modelning litsenziyasi saqlanadi**
(Qwen — Apache-2.0; Llama, Gemma — foydalanish cheklovlari bor). "100% bepul" chegarasi uchun
Apache/MIT litsenziyali modellarni tanlang.
