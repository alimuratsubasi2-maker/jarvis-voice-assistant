# JARVIS â€” Sesli Asistan

MasaÃ¼stÃ¼ ve telefondan kullanÄ±labilen, **sesli komutla Ã§alÄ±ÅŸan kiÅŸisel yapay zeka asistanÄ±**. KonuÅŸmacÄ± tanÄ±ma (ses profili), gÃ¼nlÃ¼k plan hatÄ±rlatÄ±cÄ±sÄ± ve mobil arayÃ¼z iÃ§erir.

## Ã–zellikler
- Sesli komut ve cevap (masaÃ¼stÃ¼ GUI)
- Ses profiliyle konuÅŸmacÄ± doÄŸrulama (`enroll_voice.py`)
- GÃ¼nlÃ¼k plan bildirimleri ve hatÄ±rlatÄ±cÄ±lar
- Telefon iÃ§in mobil web arayÃ¼zÃ¼ (`mobile/`) ve API sunucusu

## Kurulum
```bash
pip install -r requirements.txt
cp .env.example .env      # API anahtarlarÄ±nÄ± doldur
python jarvis_gui.py
```

> Ses profili ve kiÅŸisel plan verileri depoda yoktur.

**Teknolojiler:** Python Â· Gemini API Â· Speech/TTS Â· Flask Â· PWA