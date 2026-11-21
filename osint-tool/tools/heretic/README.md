# heretic — modelni o'zgartirish (alohida vosita)

[heretic](https://github.com/p-e-w/heretic) (AGPL-3.0, versiya 2.1.0 qotirilgan) til modelining
xulqini qayta o'qitmasdan o'zgartiradi. Bu **NEXUS'dan alohida** vosita: NEXUS uni import qilmaydi,
chaqirmaydi va uning kodini ko'chirmaydi (AGPL shart). U faqat o'zgartirilgan modelni diskka yozadi,
uni Ollama'ga qo'shish yoki qo'shmaslik — sizning qaroringiz.

## Talablar
- NVIDIA GPU (RTX 5060 8 GB'da tekshirilgan: torch CUDA'ni ko'radi). GPU'siz amalda ishlamaydi.
- [uv](https://docs.astral.sh/uv/). O'z virtualenv'i shu papkada (`.venv/`, git'ga tushmaydi).
- Model Hugging Face'dan yuklanadi (4B model ~8 GB). 8 GB VRAM uchun 4–8B model va
  `--quantization BNB_4BIT` mos. Bitta run 30–60 daqiqa.

## Ishga tushirish

    tools/heretic/run.sh Qwen/Qwen3-4B-Instruct-2507            # nosyco (standart)
    tools/heretic/run.sh Qwen/Qwen3-4B-Instruct-2507 terse      # qisqa javoblar

Konfiguratsiyalar (upstream'ning `config.<nomi>.toml` fayllari):

| Nomi | Nima qiladi | NEXUS uchun |
|---|---|---|
| `nosyco` (standart) | xushomad ("great question", "you're absolutely right") kamayadi | foydali: model dalilga qarshi chiqishdan qo'rqmaydi |
| `noslop` | shablon, suvli iboralar kamayadi | foydali |
| `terse` | javoblar qisqaradi | foydali, tezroq |
| `default` | **rad etishlarni olib tashlaydi** | tavsiya etilmaydi (pastga qarang) |

Oxirida heretic modelni qayerga saqlashni so'raydi (`work/` ichida saqlang, u git'ga tushmaydi).

## Ollama'ga qo'shish (ixtiyoriy)
Natija Hugging Face formatida (safetensors). Ollama uchun GGUF'ga o'giring
([llama.cpp](https://github.com/ggml-org/llama.cpp) `convert_hf_to_gguf.py`), keyin:

    echo 'FROM ./model.gguf' > Modelfile && ollama create qwen3-nosyco -f Modelfile

NEXUS'da ishlatish uchun `.env`'da: `OLLAMA_FAST_MODEL=qwen3-nosyco` (yoki `OLLAMA_SMART_MODEL`).
Undan oldin modelni Agent aniqligi o'lchovida sinab ko'ring (`scripts/eval_agent.py`, README):
o'zgartirilgan model sifatini biroz yo'qotishi mumkin.

## `default` (rad etishni olib tashlash) haqida
NEXUS haqiqiy odamlar haqida ishlaydi. Modelning "bu odamning manzili/telefonini top yoki taxmin qil"
kabi so'rovlarni rad etishi himoya qatlamlaridan biri. NEXUS kodi kontaktni baribir faqat dalildan
oladi (AI taxmin qilgan email/telefon/havola dalilda so'zma-so'z bo'lmasa tashlanadi), lekin bu
qatlamni olib tashlash tavsiya etilmaydi. Loyiha chegaralari (ROADMAP) har qanday modelda o'zgarmaydi.
