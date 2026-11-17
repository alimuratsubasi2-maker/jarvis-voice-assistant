#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. Sesli Asistan Sunucusu
=====================================
Akis:
    Mikrofon (surekli dinleme) -> "merhaba jarvis" uyanma kelimesi algilanir
             -> Yaziya cevirme (Google STT, Turkce)
             -> Claude Code CLI (yerel, headless: `claude -p --chrome --resume`)
             -> Metinden sese: Gemini "Charon" sesi (varsayilan) -> ElevenLabs
                (yedek) -> ucretsiz edge-tts/Ahmet (son care)
             -> Otomatik oynatma

UYARI: Bu mod calisirken mikrofon SUREKLI ACIKTIR. Duyulan her konusma
parcasi, uyanma kelimesi olup olmadigini anlamak icin Google'in ucretsiz
yaziya cevirme servisine gonderilir.

Kullanim:
    - Hicbir tusa basmana gerek yok. "Merhaba jarvis" (ya da "hey jarvis",
      "selam jarvis", tek basina "jarvis") de - script otomatik algilar.
    - "cik" / "kapat" / "dur" de veya Ctrl+C ile sonlandir.
    - "hafizani sifirla" dersen sohbet hafizasi temizlenir, yeni bir
      konusmaya baslar.
"""

import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
import speech_recognition as sr
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# pythonw.exe ile (konsolsuz "uygulama" modunda) calistirilirsa stdout/stderr
# None olur ve print() cokerdi - bu yuzden boyle bir dosyaya yonlendiriyoruz.
# ---------------------------------------------------------------------------
if sys.stdout is None or sys.stderr is None:
    _log_path = Path(__file__).resolve().parent / "jarvis_log.txt"
    _log_file = open(_log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_file
    sys.stderr = _log_file
    print(f"\n{'='*60}\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Uygulama modunda baslatildi (konsol yok)\n{'='*60}")

# ---------------------------------------------------------------------------
# Tek ornek kilidi - ayni anda birden fazla JARVIS calisirsa hepsi mikrofona
# girmeye calisip birbirine karisiyor ("surekli bekliyor" sikayetinin nedeni
# genelde budur). Zaten calisan bir ornek varsa yenisi sessizce kapanir.
# ---------------------------------------------------------------------------
def _acquire_single_instance_lock() -> bool:
    import atexit

    lock_path = Path(__file__).resolve().parent / "jarvis.lock"
    if lock_path.exists():
        try:
            old_pid = int(lock_path.read_text().strip())
            check = subprocess.run(
                ["tasklist", "/FI", f"PID eq {old_pid}"],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if str(old_pid) in check.stdout:
                print(f"Zaten calisan bir JARVIS (PID {old_pid}) var, bu ornek kapanıyor.")
                return False
        except Exception:
            pass  # kilit dosyasi bozuksa/okunmuyorsa devam et, uzerine yaz

    lock_path.write_text(str(os.getpid()))

    def _release():
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    atexit.register(_release)
    return True


if not _acquire_single_instance_lock():
    sys.exit(0)

# ---------------------------------------------------------------------------
# Ayarlar
# ---------------------------------------------------------------------------
USE_WHISPER = False  # True yaparsan yerel/offline STT icin faster-whisper denenir
CLAUDE_CLI = r"C:\Users\MSI\AppData\Roaming\npm\claude.cmd"  # tam yol - PATH sorunlarina takilmasin
STT_LANGUAGE = "tr-TR"

# Claude'u Masaustu'nden calistiriyoruz (2026-10-08'de Etsy disindaki TUM
# projeler "YAPAY ZEKA PROJELER" altina tasindigi icin eskiden sabit olan
# Etsy klasoru artik yetersizdi) - boylece hem Etsy hem de YouTube/otomasyon
# projelerinin hepsine (Narvex, OpenMontage, ai-haber-takip vb.) dogal
# erisimi oluyor, "otomasyonumu kontrol et" gibi isteklerde kendi kesfedip
# ilgili klasoru/logu bulabiliyor.
PROJECT_DIR = r"C:\Users\MSI\Desktop"

# Her claude cagrisina eklenen kalici talimat - e-posta onay kurali ve proje
# yerlesimi hakkinda. --append-system-prompt ile her oturumda gecerli olur,
# session resume ile de korunur.
JARVIS_SYSTEM_PROMPT = (
    "Sen sesli bir asistansin (JARVIS), kullanicinin bilgisayarindan "
    "cagriliyorsun. Onemli kurallar: "
    "(1) E-POSTA: Gmail'den e-posta gonderirken ASLA kullanicinin acik "
    "onayi olmadan Gonder/Send tusuna basma - once taslagi hazirla, icerigini "
    "ozetle, ve kullanici acikca onaylayana kadar bekle. Editorluk isiyle "
    "ilgili postalar novadijitaltr Gmail hesabindadir. "
    "(2) PROJELER: 'C:\\Users\\MSI\\Desktop\\YAPAY ZEKA PROJELER' altinda "
    "kullanicinin YouTube/otomasyon projeleri bulunur (ornegin Narvex kanali "
    "icin AI-Kanal, OpenMontage video pipeline, ai-haber-takip gunluk "
    "bulten). 'Otomasyonumu kontrol et' dendiginde o klasordeki ilgili "
    "projeye gidip log/status dosyalarini oku, calisiyorsa/bittiyse/hata "
    "verdiyse kisa ve net sesli ozet ver. Baslatma istenirse ilgili "
    "scripti/komutu calistir. "
    "(3) Cevaplarin SESLE okunacak - kisa, dogal konusma dilinde, madde "
    "isareti/markdown kullanma."
)

# Gercek, oturum acilmis Chrome'u kontrol etmesi icin (Etsy, Gmail dahil).
USE_BROWSER = True

# Hangi mikrofonu kullanacagi - isminde bu metin gecen ilk cihaz secilir.
# Bos "" = Windows varsayilanini kullanir (Bluetooth kulakliklarla isim
# eslesmesi bazen mikrofonu olmayan bir uc noktayi yakalayip "esik: 0"
# durumuna dusuruyordu - bu yuzden varsayilan olarak kapali).
MIC_DEVICE_NAME_HINT = ""

# test_mikrofon.py ile hangi cihaz numarasinin GERCEKTEN ses aldigini
# bulduysan buraya yaz - isim eslesmesinden ONCELIKLI calisir.
MIC_DEVICE_INDEX_OVERRIDE = None

# Konusmaci tanima: "voice_profile.npy" varsa (enroll_voice.py ile olusturulur)
# SADECE o ses profiline benzeyen konusmalar isleme alinir, etraftaki baska
# sesler/gurultu sessizce yok sayilir. Profil yoksa bu ozellik devre disi.
SPEAKER_PROFILE_FILE_NAME = "voice_profile.npy"
SPEAKER_SIMILARITY_THRESHOLD = 0.70

# Uyanma kelimesi kaliplari - Google STT "jarvis"i bazen "carvis", "harvis"
# gibi de yazabilir, o yuzden birkac yaygin varyant da eklendi.
WAKE_PATTERNS = [
    r"merhaba\s+jarvis",
    r"hey\s+jarvis",
    r"selam\s+jarvis",
    r"merhaba\s+carvis",
    r"hey\s+carvis",
    r"jarvis",
    r"carvis",
    r"harvis",
]
WAKE_LISTEN_LIMIT = 6      # uyanma kelimesini yakalamak icin kisa parcalar dinle (sn)
COMMAND_LISTEN_LIMIT = 20  # uyanma kelimesinden sonraki asil komut icin uzun sure (sn)

# Claude yavas calisacaksa (arama, dosya okuma, tarayici vb.), sessiz kalmak
# yerine hemen bunlardan birini soyleyip sonra gercek cevabi veriyoruz.
THINKING_FILLERS = [
    "Hemen bakıyorum.",
    "Tamam, hallediyorum.",
    "Bir saniye, üzerinde çalışıyorum.",
    "İşlem yapılıyor, hemen dönüyorum.",
    "Bakıyorum, biraz sürebilir.",
]

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

# Secilen ses: Gemini'nin "Charon" sesi (JARVIS-OS-V.2 projesinden ilham
# alindi). .env'e GEMINI_API_KEY eklenirse bu kullanilir, yoksa ElevenLabs'e,
# o da yoksa ucretsiz edge-tts'e (Ahmet) duser.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_VOICE_NAME = os.getenv("GEMINI_VOICE_NAME", "Charon")
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"

ELEVEN_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "Zpbxhg6LG47cY8y5BJrf")

EDGE_VOICE = os.getenv("EDGE_TTS_VOICE", "tr-TR-AhmetNeural")
EDGE_RATE = os.getenv("EDGE_TTS_RATE", "+15%")

# Ses tonu ayari - 1.0 = orijinal. Charon icin ayarsiz (orijinal) haliyle
# karar kilindi.
VOICE_PITCH = float(os.getenv("VOICE_PITCH", "1.0"))
STATUS_FILE = HERE / "jarvis_status.json"


# ---------------------------------------------------------------------------
# Durum dosyasi (local_dashboard.html tarafindan okunur)
# ---------------------------------------------------------------------------
def set_status(state: str, text: str = "") -> None:
    try:
        STATUS_FILE.write_text(
            json.dumps({"state": state, "text": text, "ts": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass  # dashboard senkronu opsiyonel, sesli akisi bozmasin


def find_mic_device_index(name_hint: str) -> int | None:
    """Isminde name_hint gecen ilk SES GIRIS cihazinin index'ini dondurur."""
    if not name_hint:
        return None
    try:
        import pyaudio
    except ImportError:
        return None

    p = pyaudio.PyAudio()
    try:
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0 and name_hint.lower() in info.get("name", "").lower():
                return i
    finally:
        p.terminate()
    return None


# ---------------------------------------------------------------------------
# Konusmaci tanima (opsiyonel - voice_profile.npy varsa aktif olur)
# ---------------------------------------------------------------------------
_voice_encoder = None
_voice_profile = None
_speaker_verification_ready = False


def _init_speaker_verification() -> None:
    """Bir kere calisir: profil dosyasi varsa modeli yukler."""
    global _voice_encoder, _voice_profile, _speaker_verification_ready
    if _speaker_verification_ready:
        return
    _speaker_verification_ready = True  # tekrar denemesin, basarisiz da olsa

    profile_path = HERE / SPEAKER_PROFILE_FILE_NAME
    if not profile_path.exists():
        return

    try:
        import numpy as np
        from resemblyzer import VoiceEncoder
        _voice_profile = np.load(profile_path)
        # device="cpu" bilerek zorlanıyor: model o kadar küçük ki GPU'dan
        # hiçbir kazanç sağlamıyor (CPU'da da <100ms), ama CUDA üzerinde
        # bu ses/mikrofon döngüsüyle aynı anda çalışınca JARVIS'i
        # hiçbir hata/traceback basmadan sessizce çökertiyordu.
        _voice_encoder = VoiceEncoder(device="cpu")
        print("Konusmaci tanima AKTIF - sadece kayitli sesin islenecek.")
    except Exception as exc:
        print(f"Konusmaci tanima yuklenemedi ({exc}), herkesin sesi kabul edilecek.")
        _voice_encoder = None
        _voice_profile = None


def verify_speaker(audio: sr.AudioData) -> bool:
    """voice_profile.npy yoksa her zaman True (ozellik kapali). Varsa, bu
    sesin kayitli profile yeterince benzeyip benzemedigini kontrol eder."""
    _init_speaker_verification()
    if _voice_encoder is None or _voice_profile is None:
        return True  # profil yok, ozellik devre disi - herkes gecer

    try:
        import numpy as np
        from resemblyzer import preprocess_wav

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio.get_wav_data())
            wav_path = f.name
        wav = preprocess_wav(wav_path)
        os.unlink(wav_path)
        if len(wav) < 1000:  # cok kisa, guvenilir olcum yapilamaz - reddetme
            return True
        embedding = _voice_encoder.embed_utterance(wav)
        similarity = float(np.dot(embedding, _voice_profile))
        matched = similarity >= SPEAKER_SIMILARITY_THRESHOLD
        if not matched:
            print(f"Konusmaci eslesmedi (benzerlik: {similarity:.2f}), yok sayiliyor.")
        return matched
    except Exception as exc:
        print(f"Konusmaci dogrulama hatasi ({exc}), guvenlik icin kabul ediliyor.")
        return True


def beep() -> None:
    """Uyanma kelimesi algilaninca kisa bir sesli onay (ucretsiz, TTS cagirmadan)."""
    try:
        import winsound
        winsound.Beep(880, 150)
    except Exception:
        print("\a", end="", flush=True)


# ---------------------------------------------------------------------------
# Uyanma kelimesi tespiti
# ---------------------------------------------------------------------------
def extract_after_wake(text: str) -> str | None:
    lowered = text.lower().strip()
    for pattern in WAKE_PATTERNS:
        match = re.search(pattern, lowered)
        if match:
            return lowered[match.end():].strip(" ,.!?-")
    return None


# ---------------------------------------------------------------------------
# 1) Mikrofon -> metin (tek parca)
# ---------------------------------------------------------------------------
def listen_snippet(
    phrase_time_limit: int,
    recognizer: sr.Recognizer,
    source,
    timeout: float | None = None,
    return_audio: bool = False,
):
    try:
        audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
    except sr.WaitTimeoutError:
        return (None, None) if return_audio else None

    if USE_WHISPER:
        text = _transcribe_with_whisper(audio)
    else:
        try:
            text = recognizer.recognize_google(audio, language=STT_LANGUAGE)
        except sr.UnknownValueError:
            text = None
        except sr.RequestError as exc:
            print(f"STT servis hatasi: {exc}")
            text = None

    return (text, audio) if return_audio else text


def _transcribe_with_whisper(audio: sr.AudioData) -> str | None:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper kurulu degil.")
        return None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio.get_wav_data())
        wav_path = f.name
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(wav_path, language="tr")
    text = " ".join(seg.text.strip() for seg in segments).strip()
    os.unlink(wav_path)
    return text or None


# ---------------------------------------------------------------------------
# 2) Metin -> Claude Code CLI (headless, oturum hafizali)
# ---------------------------------------------------------------------------
SESSION_FILE = HERE / "jarvis_session.json"
RESET_PHRASES = ("hafizani sifirla", "hafızanı sıfırla", "yeni konusma baslat", "yeni konuşma başlat")


def _load_session_id() -> str | None:
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8")).get("session_id")
    except (OSError, json.JSONDecodeError):
        return None


def _save_session_id(session_id: str) -> None:
    try:
        SESSION_FILE.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")
    except OSError:
        pass


def reset_session() -> None:
    try:
        SESSION_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _try_fast_answer(prompt: str) -> str | None:
    """Claude'a hic gitmeden, aninda cevaplanabilecek basit sorular.
    "saat kac" gibi sorularda tum ajan dongusunu beklemek gereksiz yavas."""
    lowered = prompt.strip().lower()
    if any(p in lowered for p in ("saat kac", "saat kaç", "saat ne")):
        now = time.localtime()
        return f"Saat {now.tm_hour}:{now.tm_min:02d}."
    if any(p in lowered for p in ("bugun ayin kaci", "bugün ayın kaçı", "hangi gundeyiz", "hangi gündeyiz", "tarih ne", "bugun tarih")):
        aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
                 "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        now = time.localtime()
        return f"Bugün {now.tm_mday} {aylar[now.tm_mon - 1]} {now.tm_year}."
    return None


_BROWSER_KEYWORDS = (
    "chrome", "tarayici", "tarayıcı", "site", "web", "internet", "google",
    "gmail", "mail", "e-posta", "eposta", "etsy", "sayfa", "link", "url",
    "arastir", "araştır", "arama yap", "ara bak", "bul bana", "gundem", "gündem",
    "haber", "fiyat", "rakip", "hesab", "gonder", "gönder", "yaz bir mail",
)


def _needs_browser(prompt: str) -> bool:
    """--chrome bayragi tarayici altyapisini hazirlarken zaman kaybettiriyor -
    sadece web/mail/site gerektirdigi belli olan komutlarda kullaniyoruz."""
    lowered = prompt.strip().lower()
    return any(kw in lowered for kw in _BROWSER_KEYWORDS)


def ask_claude(prompt: str) -> str:
    if prompt.strip().lower() in RESET_PHRASES:
        reset_session()
        return "Tamam, hafizami sifirladim. Yeni bir sohbete basliyoruz."

    fast = _try_fast_answer(prompt)
    if fast is not None:
        return fast

    set_status("thinking", prompt)
    print("Claude dusunuyor...")

    session_id = _load_session_id()
    cmd = [CLAUDE_CLI, "-p", "--output-format", "json", "--append-system-prompt", JARVIS_SYSTEM_PROMPT]
    # --chrome bayragi her seferinde tarayici altyapisini hazirladigi icin
    # yavaslatiyordu - sadece gercekten web/mail/site gerektiren komutlarda
    # ekliyoruz, sohbet/basit sorularda atlanip hizlanmasi saglaniyor.
    if USE_BROWSER and _needs_browser(prompt):
        cmd.append("--chrome")
    if session_id:
        cmd += ["--resume", session_id]
    cmd.append(prompt)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=240,
            encoding="utf-8",
            errors="replace",
            cwd=PROJECT_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        return (
            f"'{CLAUDE_CLI}' komutu bulunamadi. Claude Code CLI'nin kurulu ve "
            "PATH'te oldugunu kontrol et (terminalde 'claude --version' dene)."
        )
    except subprocess.TimeoutExpired:
        return (
            "Islem zaman asimina ugradi. Eger bu hassas bir islemse (gonderme, "
            "silme, satin alma), Claude muhtemelen senin onayini bekliyordu ve "
            "islem TAMAMLANMADI - terminale bakip elle onaylaman gerekebilir."
        )

    if result.returncode != 0:
        print("Claude Code hata verdi:", result.stderr[:500])
        if session_id:
            reset_session()
        return "Bir hata olustu, tekrar dener misin?"

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip() or "Bos bir yanit geldi."

    new_session_id = data.get("session_id")
    if new_session_id:
        _save_session_id(new_session_id)

    return (data.get("result") or "").strip() or "Bos bir yanit geldi."


# ---------------------------------------------------------------------------
# 3) Metin -> ses -> otomatik oynatma
# ---------------------------------------------------------------------------
def _split_sentences(text: str) -> list[str]:
    """Metni cumlelere boler - noktalama + bosluktan sonra keser. Basit ama
    konusma metni icin yeterli (kisaltmalarda nadiren yanlis bolebilir)."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def speak(text: str) -> None:
    print(f"J.A.R.V.I.S.: {text}")
    sentences = _split_sentences(text)

    if len(sentences) <= 1:
        set_status("speaking", text)
        _speak_one(text)
    else:
        # Cumle cumle uret+cal - tum metnin tek parca sese cevrilmesini
        # beklemek yerine ilk cumle hazir olur olmaz konusmaya baslar.
        for sentence in sentences:
            set_status("speaking", sentence)
            _speak_one(sentence)

    set_status("idle")


def _speak_one(text: str) -> None:
    if GEMINI_API_KEY:
        ok = _speak_gemini(text)
        if not ok:
            print("Gemini TTS basarisiz oldu, sonraki secenege geciliyor...")
            if ELEVEN_API_KEY:
                if not _speak_elevenlabs(text):
                    _speak_edge(text)
            else:
                _speak_edge(text)
    elif ELEVEN_API_KEY:
        ok = _speak_elevenlabs(text)
        if not ok:
            print("ElevenLabs basarisiz oldu, edge-tts'e geciliyor...")
            _speak_edge(text)
    else:
        _speak_edge(text)


def _speak_gemini(text: str) -> bool:
    """Gemini'nin native TTS'i ile konusma. Basarili olursa True doner."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_TTS_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_VOICE_NAME}}
            },
        },
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
    except requests.RequestException as exc:
        print(f"Gemini TTS baglanti hatasi: {exc}")
        return False

    if resp.status_code != 200:
        print(f"Gemini TTS hatasi: {resp.status_code} {resp.text[:300]}")
        return False

    try:
        import base64
        audio_b64 = resp.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        pcm_bytes = base64.b64decode(audio_b64)
    except (KeyError, IndexError, ValueError) as exc:
        print(f"Gemini TTS yanit ayristirma hatasi: {exc}")
        return False

    # Gemini ham PCM donduruyor (16-bit, 24000 Hz, mono). Kaynak orneklem
    # hizini zaten biliyoruz, bu yuzden ffprobe'a gerek yok; pitch (varsa)
    # ve WAV'a cevirme TEK ffmpeg cagrisinda yapiliyor - eskiden bu, ayri
    # ayri "PCM->mp3", "ornek hizi olc", "pitch uygula", "mp3->wav" olmak
    # uzere 4 ayri sureç calistiriyordu; her cumle icin bu kadar surec
    # baslatmak (Windows'ta her biri gozle gorulur gecikme ekliyor)
    # cevaplarin "gec gelmesinin" ana sebebiydi.
    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as f:
        f.write(pcm_bytes)
        pcm_path = f.name
    wav_path = pcm_path.replace(".pcm", ".wav")
    audio_filter = f"asetrate=24000*{VOICE_PITCH},aresample=44100" if VOICE_PITCH != 1.0 else "aresample=44100"
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", pcm_path,
                "-af", audio_filter, wav_path,
            ],
            capture_output=True, timeout=30, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as exc:
        print(f"Gemini ses donusturme hatasi: {exc}")
        return False
    finally:
        try:
            os.unlink(pcm_path)
        except OSError:
            pass

    _play_audio(wav_path)
    return True


def _speak_edge(text: str) -> None:
    """Ucretsiz, anahtar gerektirmeyen TTS (Microsoft edge-tts)."""
    try:
        import asyncio
        import edge_tts
    except ImportError:
        print("edge-tts kurulu degil. `pip install edge-tts` calistir.")
        return

    async def _generate() -> str:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            mp3_path = f.name
        communicate = edge_tts.Communicate(text, EDGE_VOICE, rate=EDGE_RATE)
        await communicate.save(mp3_path)
        return mp3_path

    try:
        mp3_path = asyncio.run(_generate())
    except Exception as exc:
        print(f"edge-tts hatasi: {exc}")
        return

    _play_audio(_apply_pitch(mp3_path))


def _get_sample_rate(path: str) -> int:
    """Dosyanin GERCEK orneklem hizini ffprobe ile okur (varsayim yapmiyoruz -
    yanlis taban (44100 sanip aslinda 24000 olan bir dosyaya uygulamak) sesi
    kalinlastirmak yerine incelttigi bir hataya yol acmisti)."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=sample_rate", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=10, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return int(result.stdout.strip())
    except Exception:
        return 44100  # tahmin edemezsek makul bir varsayim


def _apply_pitch(mp3_path: str) -> str:
    """ffmpeg ile ses tonunu ayarlar (VOICE_PITCH). Basarisiz olursa orijinali dondurur."""
    if VOICE_PITCH == 1.0:
        return mp3_path
    source_rate = _get_sample_rate(mp3_path)
    out_path = mp3_path.replace(".mp3", "_pitch.mp3")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", mp3_path,
                "-af", f"asetrate={source_rate}*{VOICE_PITCH},aresample=44100",
                out_path,
            ],
            capture_output=True, timeout=30, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return out_path
    except Exception as exc:
        print(f"ffmpeg ton ayari basarisiz ({exc}), orijinal ses kullaniliyor.")
        return mp3_path


def _speak_elevenlabs(text: str) -> bool:
    """ElevenLabs ile TTS. Basarili olursa True doner."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
    except requests.RequestException as exc:
        print(f"ElevenLabs baglanti hatasi: {exc}")
        return False

    if resp.status_code != 200:
        print("ElevenLabs hatasi:", resp.status_code, resp.text[:300])
        return False

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(resp.content)
        mp3_path = f.name

    _play_audio(_apply_pitch(mp3_path))
    return True


def _play_audio(path: str) -> None:
    # winsound, playsound'a gore ~1.5sn daha az sabit gecikmeyle calar (MCI
    # yerine dogrudan Windows ses API'sini kullaniyor) - once onu dene, WAV'a
    # cevirmesi gerekiyor. Basarisiz olursa playsound'a, o da olmazsa
    # varsayilan oynaticiya duser.
    try:
        import winsound
        if path.lower().endswith(".wav"):
            # Zaten WAV (Gemini yolu artik dogrudan WAV uretiyor) - bir
            # ffmpeg sureci daha baslatip ayni formata tekrar cevirmeye
            # gerek yok, dogrudan cal.
            winsound.PlaySound(path, winsound.SND_FILENAME)
            try:
                os.unlink(path)
            except OSError:
                pass
            return
        wav_path = path.rsplit(".", 1)[0] + "_play.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", path, wav_path],
            capture_output=True, timeout=15, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        winsound.PlaySound(wav_path, winsound.SND_FILENAME)
        try:
            os.unlink(wav_path)
        except OSError:
            pass
        return
    except Exception as exc:
        print(f"winsound basarisiz ({exc}), playsound deneniyor...")

    try:
        from playsound import playsound
        playsound(path)
    except Exception:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception as exc:
            print(f"Ses oynatilamadi ({exc}). Dosya burada: {path}")


# ---------------------------------------------------------------------------
# Gorsel kure pencresini ac
# ---------------------------------------------------------------------------
def launch_orb() -> None:
    gui_path = HERE / "jarvis_gui.py"
    if not gui_path.exists():
        return
    try:
        subprocess.Popen(
            [sys.executable, str(gui_path)],
            cwd=str(HERE),
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except Exception as exc:
        print(f"Kure widget'i acilamadi ({exc}), sadece arka planda devam ediliyor.")


# ---------------------------------------------------------------------------
# Ana dongu - surekli dinleme + uyanma kelimesi
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("  J.A.R.V.I.S. Sesli Asistan baslatildi")
    print('  Uyanma kelimesi: "merhaba jarvis" (veya "hey jarvis", "jarvis")')
    print("  UYARI: mikrofon surekli aciktir.")
    print("  Cikmak icin Ctrl+C")
    print("=" * 60)

    launch_orb()

    import threading

    def _try_init_mic():
        """Basarili olursa (mic, recognizer, None) doner, olmazsa (None, None, hata_metni)."""
        result = {}

        def _worker():
            try:
                device_index = MIC_DEVICE_INDEX_OVERRIDE
                if device_index is not None:
                    print(f"Mikrofon: elle belirtilen cihaz #{device_index} kullaniliyor.")
                    mic = sr.Microphone(device_index=device_index)
                elif (found := find_mic_device_index(MIC_DEVICE_NAME_HINT)) is not None:
                    print(f"Mikrofon: '{MIC_DEVICE_NAME_HINT}' eslesmesi bulundu (cihaz #{found}) kullaniliyor.")
                    mic = sr.Microphone(device_index=found)
                else:
                    if MIC_DEVICE_NAME_HINT:
                        print(f"UYARI: '{MIC_DEVICE_NAME_HINT}' isminde mikrofon bulunamadi, Windows varsayilani kullaniliyor.")
                    mic = sr.Microphone()

                rec = sr.Recognizer()
                # Konusma bitince daha az bekle (varsayilan 0.8sn -> 0.4sn)
                rec.pause_threshold = 0.4
                rec.non_speaking_duration = 0.3
                with mic as source:
                    print("\nOrtam gurultusune ayarlaniyor, bir sn sessiz kal...")
                    rec.adjust_for_ambient_noise(source, duration=1.0)
                # Esik cok yuksek ya da cok dusuk kalibre olursa makul araliga sabitle.
                # Taban 50'den 200'e cikarildi: dusuk esik, etraftaki her sesi/
                # gurultuyu "konusma basladi" sanip takiliyordu, sadece net/
                # yakin konusmayi yakalasin diye yukseltildi.
                if rec.energy_threshold > 350:
                    print(f"Esik {rec.energy_threshold:.0f} -> 350'e sabitlendi (cok yuksekti).")
                    rec.energy_threshold = 350
                elif rec.energy_threshold < 200:
                    print(f"Esik {rec.energy_threshold:.0f} -> 200'e sabitlendi (cok dusuktu, gurultuye takiliyordu).")
                    rec.energy_threshold = 200
                # Esik zamanla gurultuye gore kendiliginden surunmesin - sabit kalsin
                rec.dynamic_energy_threshold = False
                result["mic"] = mic
                result["recognizer"] = rec
            except Exception as exc:
                result["exc"] = exc

        # Bluetooth'ta takili/donuk bir cihaz PyAudio'nun cihaz taramasini
        # SONSUZA KADAR kilitleyebilir. Ayri thread + zaman asimiyla yakalayip
        # sessizce takili kalmak yerine acik bir hata donuyoruz.
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=12)

        if t.is_alive():
            return None, None, (
                "Mikrofon baslatilamadi - bir Bluetooth cihazi (eslestirilmis ama "
                "yanit vermeyen bir kulaklik) taramayi kilitliyor olabilir. Bluetooth "
                "ayarlarindan kullanmadigin cihazlari kapat, otomatik tekrar denenecek."
            )
        if "exc" in result:
            return None, None, f"Mikrofon baslatilamadi: {result['exc']}"
        return result["mic"], result["recognizer"], None

    mic = recognizer = None
    retry_delay = 20
    while mic is None:
        mic, recognizer, err = _try_init_mic()
        if err:
            print(f"\nHATA: {err}\n{retry_delay} saniye sonra tekrar denenecek...")
            set_status("error", err)
            time.sleep(retry_delay)

    # Konusmaci tanima modelini (varsa) SIMDI yukle, ilk komutta degil -
    # torch/resemblyzer importu birkac saniye surebiliyor, bu ilk "merhaba
    # jarvis" anina denk gelirse donmus/cevrimdisi gibi gorunuyordu.
    if (HERE / SPEAKER_PROFILE_FILE_NAME).exists():
        print("Konusmaci tanima modeli yukleniyor...")
        _init_speaker_verification()

    # edge-tts'in kendisi ~1.3sn'lik bir import gecikmesi tasiyor - bunu ilk
    # gercek cevaba degil, simdi (baslangicta) odetiyoruz.
    try:
        import asyncio as _asyncio
        import edge_tts as _edge_tts
        print("Ses motoru on-yukleniyor...")
    except ImportError:
        pass

    set_status("idle")
    print("\nHazir. Baslamak icin 'merhaba jarvis' de.\n")

    try:
        cycle = 0
        while True:
            cycle += 1
            with mic as source:
                set_status("listening")
                print(f"  ...dinleniyor (deneme #{cycle}, esik: {int(recognizer.energy_threshold)})...", end="\r")
                snippet, snippet_audio = listen_snippet(
                    WAKE_LISTEN_LIMIT, recognizer, source, timeout=WAKE_LISTEN_LIMIT, return_audio=True
                )

            if not snippet:
                if cycle % 5 == 0:
                    print(f"\n  (hala dinliyorum - {cycle} deneme oldu, ses algilanamiyor olabilir)")
                continue

            remainder = extract_after_wake(snippet)
            if remainder is None:
                continue  # uyanma kelimesi yok, gormezden gel, dinlemeye devam

            # Baskasinin/etraftaki bir sesin uyanma kelimesi soylemesi durumu -
            # profil kayitliysa burada elenir, sadece kayitli ses gecer.
            if not verify_speaker(snippet_audio):
                continue

            t_wake = time.time()
            print(f"\nUyanma kelimesi algilandi: \"{snippet}\"")
            beep()

            if not remainder:
                set_status("listening", "buyrun, dinliyorum")
                print("Buyurun, dinliyorum...")
                with mic as source:
                    remainder, cmd_audio = listen_snippet(
                        COMMAND_LISTEN_LIMIT, recognizer, source, return_audio=True
                    )
                if not remainder:
                    print("Bir komut duyamadim, tekrar 'merhaba jarvis' de.")
                    set_status("idle")
                    continue
                if not verify_speaker(cmd_audio):
                    print("Komut baska bir sesten geldi, yok sayiliyor.")
                    set_status("idle")
                    continue

            command = remainder.strip()
            t_command_ready = time.time()
            print(f"Komut: {command}  [+{t_command_ready - t_wake:.2f}s uyanmadan beri]")

            if command.lower() in ("cik", "kapat", "dur", "çık"):
                break

            # Ani/basit sorularda (saat kac vb.) filler'a gerek yok, direkt
            # cevap gelir. Claude'a gidecekse (yavas olabilir) once kisa bir
            # "hemen bakiyorum" ile sessizligi kirip beklemeyi belli ediyoruz.
            if _try_fast_answer(command) is None:
                t_filler_start = time.time()
                speak(random.choice(THINKING_FILLERS))
                print(f"  [ZAMANLAMA] filler konusma suresi: {time.time() - t_filler_start:.2f}s")

            t_claude_start = time.time()
            reply = ask_claude(command)
            print(f"  [ZAMANLAMA] Claude cevap suresi: {time.time() - t_claude_start:.2f}s")
            t_speak_start = time.time()
            speak(reply)
            print(f"  [ZAMANLAMA] son cevap konusma suresi: {time.time() - t_speak_start:.2f}s")
            print(f"  [ZAMANLAMA] TOPLAM (uyanmadan cevap bitene kadar): {time.time() - t_wake:.2f}s")
    except KeyboardInterrupt:
        pass
    finally:
        set_status("offline")
        print("\nGorusuruz.")


if __name__ == "__main__":
    main()
