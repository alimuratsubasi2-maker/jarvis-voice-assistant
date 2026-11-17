#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. API Sunucusu (telefon <-> bilgisayar koprusu)
=============================================================
Telefonundaki web uygulamasi (mobile/ klasoru) buraya komut gonderir,
bu da komutu yerel Claude Code CLI'ye (`claude -p --chrome`) iletir,
cevabi hem bilgisayarda sesli okur hem telefona geri yollar.

Kurulum ozet (detay: KURULUM.md):
    1) pip install flask (zaten kuruldu)
    2) Tailscale'i bilgisayarina VE telefonuna kur, ayni hesapla gir.
    3) python jarvis_api_server.py calistir.
    4) Ilk calismada bir JARVIS_API_TOKEN uretilip .env'e yazilir ve
       ekrana basilir - bunu telefondaki uygulamaya bir kere girmen
       gerekecek.
    5) Telefonda Tailscale uzerinden bilgisayarinin adresine git
       (ör. https://bilgisayar-adi.tailXXXX.ts.net:8765), ana ekrana ekle.

GUVENLIK NOTU: Bu sunucu, komutlari HICBIR onay istemeden calistirir
(kullanicinin acik tercihi). Tailscale, sadece SENIN yetkilendirdigin
cihazlarin bu sunucuya erisebilmesini saglar - internete acik degildir.
JARVIS_API_TOKEN, ayni Tailscale agindaki BASKA cihazlara/kisilere karsi
ek bir koruma katmanidir.
"""

import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv, set_key
from flask import Flask, jsonify, request, send_from_directory

HERE = Path(__file__).resolve().parent

# pythonw.exe ile (konsolsuz) calistirilirsa stdout/stderr None olur, print() cokerdi.
if sys.stdout is None or sys.stderr is None:
    _log_file = open(HERE / "jarvis_api_log.txt", "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_file
    sys.stderr = _log_file
    print(f"\n{'='*60}\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] API sunucusu uygulama modunda baslatildi\n{'='*60}")

ENV_FILE = HERE / ".env"
MOBILE_DIR = HERE / "mobile"
STATUS_FILE = HERE / "jarvis_status.json"

CLAUDE_CLI = r"C:\Users\MSI\AppData\Roaming\npm\claude.cmd"  # tam yol - PATH sorunlarina takilmasin
PROJECT_DIR = r"C:\Users\MSI\Desktop\ETSY MAGAZASI İÇİN ÜRÜNLER"  # uretim raporlarinin oldugu klasor
USE_BROWSER = True
PORT = 8765

# ---------------------------------------------------------------------------
# Token: yoksa uret, .env'e yaz
# ---------------------------------------------------------------------------
if not ENV_FILE.exists():
    ENV_FILE.write_text("", encoding="utf-8")

load_dotenv(ENV_FILE)
API_TOKEN = os.getenv("JARVIS_API_TOKEN")
if not API_TOKEN:
    API_TOKEN = secrets.token_urlsafe(24)
    set_key(str(ENV_FILE), "JARVIS_API_TOKEN", API_TOKEN)
    print(f"\nYENI API TOKEN URETILDI: {API_TOKEN}")
    print("Bu token'i telefondaki uygulamaya bir kere girmen gerekecek.\n")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_VOICE_NAME = os.getenv("GEMINI_VOICE_NAME", "Charon")
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"

ELEVEN_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "Zpbxhg6LG47cY8y5BJrf")
VOICE_PITCH = float(os.getenv("VOICE_PITCH", "1.0"))
EDGE_VOICE = os.getenv("EDGE_TTS_VOICE", "tr-TR-AhmetNeural")
EDGE_RATE = os.getenv("EDGE_TTS_RATE", "+15%")

app = Flask(__name__, static_folder=None)


# ---------------------------------------------------------------------------
# Yardimcilar (jarvis_voice_server.py ile ayni mantik ve AYNI oturum dosyasi -
# masaustu ve telefon ayni konusma hafizasini paylasir)
# ---------------------------------------------------------------------------
SESSION_FILE = HERE / "jarvis_session.json"
RESET_PHRASES = ("hafizani sifirla", "hafızanı sıfırla", "yeni konusma baslat", "yeni konuşma başlat")

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


def ask_claude(prompt: str) -> str:
    if prompt.strip().lower() in RESET_PHRASES:
        try:
            SESSION_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return "Tamam, hafizami sifirladim. Yeni bir sohbete basliyoruz."

    session_id = _load_session_id()
    cmd = [CLAUDE_CLI, "-p", "--output-format", "json"]
    if USE_BROWSER and _needs_browser(prompt):
        cmd.append("--chrome")
    if session_id:
        cmd += ["--resume", session_id]
    cmd.append(prompt)

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=240,
            encoding="utf-8", errors="replace", cwd=PROJECT_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        return f"'{CLAUDE_CLI}' komutu bulunamadi."
    except subprocess.TimeoutExpired:
        return (
            "Islem zaman asimina ugradi. Hassas bir islemse (gonderme, silme, "
            "satin alma) Claude onay bekliyor olabilir - islem TAMAMLANMADI."
        )
    if result.returncode != 0:
        if session_id:
            try:
                SESSION_FILE.unlink(missing_ok=True)
            except OSError:
                pass
        return "Bir hata olustu, tekrar dener misin?"

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip() or "Bos bir yanit geldi."

    new_session_id = data.get("session_id")
    if new_session_id:
        _save_session_id(new_session_id)

    return (data.get("result") or "").strip() or "Bos bir yanit geldi."


def tts_to_bytes(text: str) -> bytes | None:
    """Metni sese cevirir, mp3 byte'lari dondurur (once Gemini/Charon, sonra
    ElevenLabs, sonra ucretsiz edge-tts)."""
    if GEMINI_API_KEY:
        data = _tts_gemini(text)
        if data:
            return data
    if ELEVEN_API_KEY:
        data = _tts_elevenlabs(text)
        if data:
            return data
    return _tts_edge(text)


def _tts_gemini(text: str) -> bytes | None:
    import base64
    import requests

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
        if resp.status_code != 200:
            print(f"Gemini TTS hatasi: {resp.status_code} {resp.text[:300]}")
            return None
        audio_b64 = resp.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        pcm_bytes = base64.b64decode(audio_b64)
    except Exception as exc:
        print(f"Gemini TTS hatasi: {exc}")
        return None

    with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as f:
        f.write(pcm_bytes)
        pcm_path = f.name
    mp3_path = pcm_path.replace(".pcm", ".mp3")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", pcm_path, mp3_path],
            capture_output=True, timeout=30, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        data = Path(mp3_path).read_bytes()
        os.unlink(pcm_path)
        os.unlink(mp3_path)
        return _apply_pitch(data)
    except Exception as exc:
        print(f"Gemini ses donusturme hatasi: {exc}")
        return None


def _get_sample_rate(path: str) -> int:
    """Dosyanin GERCEK orneklem hizini ffprobe ile okur."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=sample_rate", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=10, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return int(result.stdout.strip())
    except Exception:
        return 44100


def _apply_pitch(mp3_bytes: bytes) -> bytes:
    """ffmpeg ile ses tonunu ayarlar (VOICE_PITCH). Basarisiz olursa orijinali dondurur."""
    if VOICE_PITCH == 1.0:
        return mp3_bytes
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3_bytes)
            in_path = f.name
        source_rate = _get_sample_rate(in_path)
        out_path = in_path.replace(".mp3", "_pitch.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-i", in_path, "-af", f"asetrate={source_rate}*{VOICE_PITCH},aresample=44100", out_path],
            capture_output=True, timeout=30, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        data = Path(out_path).read_bytes()
        os.unlink(in_path)
        os.unlink(out_path)
        return data
    except Exception as exc:
        print(f"ffmpeg ton ayari basarisiz ({exc}), orijinal ses kullaniliyor.")
        return mp3_bytes


def _tts_elevenlabs(text: str) -> bytes | None:
    import requests

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"}
    payload = {
        "text": text, "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        if resp.status_code == 200:
            return _apply_pitch(resp.content)
    except requests.RequestException:
        pass
    return None


def _tts_edge(text: str) -> bytes | None:
    import asyncio
    import edge_tts

    async def _generate() -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            mp3_path = f.name
        communicate = edge_tts.Communicate(text, EDGE_VOICE, rate=EDGE_RATE)
        await communicate.save(mp3_path)
        data = Path(mp3_path).read_bytes()
        os.unlink(mp3_path)
        return data

    try:
        raw = asyncio.run(_generate())
        return _apply_pitch(raw)
    except Exception as exc:
        print(f"edge-tts hatasi: {exc}")
        return None


def play_locally(mp3_bytes: bytes) -> None:
    """Bilgisayarin kendi hoparlorunden de calar (telefonda uzaktaysan bile
    evdeki bilgisayar sesli yanit versin diye)."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(mp3_bytes)
        path = f.name

    # winsound, playsound'a gore ~1.5sn daha az sabit gecikmeyle calar
    try:
        import winsound
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
    except Exception as exc:
        print(f"Yerel oynatma hatasi: {exc}")


def set_status(state: str, text: str = "") -> None:
    try:
        STATUS_FILE.write_text(
            json.dumps({"state": state, "text": text, "ts": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def check_auth() -> bool:
    header = request.headers.get("Authorization", "")
    token = header.replace("Bearer ", "").strip()
    return secrets.compare_digest(token, API_TOKEN)


# ---------------------------------------------------------------------------
# Rotalar
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    return send_from_directory(MOBILE_DIR, "index.html")


@app.get("/<path:filename>")
def mobile_static(filename):
    return send_from_directory(MOBILE_DIR, filename)


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


@app.get("/api/status")
def status():
    try:
        return jsonify(json.loads(STATUS_FILE.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return jsonify({"state": "idle", "text": "", "ts": 0})


@app.post("/api/command")
def command():
    if not check_auth():
        return jsonify({"error": "yetkisiz - token yanlis"}), 401

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "bos komut"}), 400

    print(f"[telefon] Komut alindi: {text}")
    set_status("thinking", text)
    reply = ask_claude(text)
    set_status("speaking", reply)

    mp3 = tts_to_bytes(reply)
    audio_b64 = None
    if mp3:
        play_locally(mp3)
        audio_b64 = base64.b64encode(mp3).decode("ascii")

    set_status("idle")
    return jsonify({"reply": reply, "audio_base64": audio_b64})


if __name__ == "__main__":
    print("=" * 60)
    print("  J.A.R.V.I.S. API Sunucusu")
    print(f"  Port: {PORT}")
    print(f"  Telefon icin token: {API_TOKEN}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=PORT, debug=False)
