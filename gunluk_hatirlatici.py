# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. - Gunluk Plan Hatirlaticisi
=========================================
Her gun saat 10:00'da (Gorev Zamanlayici ile) calisir:
  1. Google E-Tablo'daki aylik plandan BUGUNKU isleri okur
  2. Telegram'a "Merhaba Ali Murat, bugun yapilacaklar..." mesaji gonderir
  3. Jarvis'in sesiyle (edge-tts / Ahmet) sesli de okur (hoparlorden)

Plan tablosu:  Ay | Hafta | Gun | Proje | Yapilacak Is | Durum | Oncelik | Not
Baslangic:    Hafta 1 / Gun 1  =  8 Eylul 2026 (Pazartesi)
Haftalar 7 ardisik gun olarak ilerler.

Elle test:   python gunluk_hatirlatici.py            (bugun icin)
             python gunluk_hatirlatici.py 2026-09-08  (belirli tarih)
             python gunluk_hatirlatici.py --sessiz     (Telegram evet, ses hayir)
"""
from __future__ import annotations

import csv
import io
import os
import sys
import time
import asyncio
import tempfile
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

# Windows konsolu cp1254 - emoji/Turkce yazdirinca cokmesin
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# --------------------------------------------------------------------------
# AYARLAR
# --------------------------------------------------------------------------
SHEET_ID = "1XSw5UcX-4T4GLtYAHCu4Wbt-Zpy_t8NkXgACHbiGXTM"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
YEREL_CSV = HERE / "plan_data.csv"          # canli tablo cekilemezse yedek

PLAN_BASLANGIC = date(2026, 9, 7)           # Hafta 1 / Gun 1  (gelecek Pazartesi)
HAFTA_UZUNLUGU = 7                          # gun

KULLANICI_ADI = "Ali Murat"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

EDGE_VOICE = os.getenv("EDGE_TTS_VOICE", "tr-TR-AhmetNeural")
EDGE_RATE = os.getenv("EDGE_TTS_RATE", "+15%")
VOICE_PITCH = float(os.getenv("VOICE_PITCH", "1.0"))

ONCELIK_IKON = {"yüksek": "🔴", "yuksek": "🔴", "orta": "🟡", "düşük": "🟢", "dusuk": "🟢"}
ONCELIK_SIRA = {"yüksek": 0, "yuksek": 0, "orta": 1, "düşük": 2, "dusuk": 2, "": 3}

AYLAR_TR = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
GUNLER_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


# --------------------------------------------------------------------------
# TABLOYU OKU
# --------------------------------------------------------------------------
def plan_satirlarini_getir() -> list[dict]:
    """Once canli Google E-Tablo'yu dener, olmazsa yerel yedegi kullanir."""
    metin = None
    try:
        r = requests.get(CSV_URL, timeout=20, allow_redirects=True)
        if r.status_code == 200 and "text/csv" in r.headers.get("content-type", ""):
            metin = r.content.decode("utf-8")
            YEREL_CSV.write_text(metin, encoding="utf-8")   # yedegi tazele
    except requests.RequestException:
        pass

    if metin is None and YEREL_CSV.exists():
        metin = YEREL_CSV.read_text(encoding="utf-8")

    if not metin:
        raise SystemExit("Plan verisi okunamadi (ne canli tablo ne yerel yedek).")

    okuyucu = csv.DictReader(io.StringIO(metin))
    satirlar = []
    for s in okuyucu:
        s = { (k or "").strip(): (v or "").strip() for k, v in s.items() }
        if s.get("Yapılacak İş") or s.get("Yapilacak Is"):
            satirlar.append(s)
    return satirlar


def alan(s: dict, *adaylar: str) -> str:
    for a in adaylar:
        if s.get(a):
            return s[a]
    return ""


# --------------------------------------------------------------------------
# TARIH -> HAFTA / GUN
# --------------------------------------------------------------------------
def hafta_gun(hedef: date) -> tuple[int, int, int]:
    fark = (hedef - PLAN_BASLANGIC).days
    hafta = fark // HAFTA_UZUNLUGU + 1
    gun = fark % HAFTA_UZUNLUGU + 1
    return fark, hafta, gun


# --------------------------------------------------------------------------
# MESAJ METNI
# --------------------------------------------------------------------------
def bugunku_isler(satirlar: list[dict], hafta: int, gun: int) -> list[dict]:
    out = []
    for s in satirlar:
        try:
            h = int(alan(s, "Hafta") or 0)
            g = int(alan(s, "Gün", "Gun") or 0)
        except ValueError:
            continue
        if h == hafta and g == gun:
            out.append(s)
    return out


def telegram_metni(hedef: date, hafta: int, gun: int, isler: list[dict]) -> str:
    tarih_str = f"{hedef.day} {AYLAR_TR[hedef.month]} {GUNLER_TR[hedef.weekday()]}"
    bas = f"🌅 Merhaba {KULLANICI_ADI}!\n\n📋 {tarih_str} · Hafta {hafta} / Gün {gun}"

    if not isler:
        return (bas + "\n\nBugün için tabloda planlanmış iş yok. "
                "Ya dinlenme günü ya da tabloya henüz eklenmedi. 🙂")

    bekleyen = [s for s in isler if alan(s, "Durum").lower() not in ("bitti", "ertelendi")]
    biten = [s for s in isler if alan(s, "Durum").lower() == "bitti"]
    ertelenen = [s for s in isler if alan(s, "Durum").lower() == "ertelendi"]

    # projeye gore grupla
    gruplar: dict[str, list[dict]] = {}
    for s in bekleyen:
        gruplar.setdefault(alan(s, "Proje") or "Diğer", []).append(s)

    def grup_oncelik(g):
        return min(ONCELIK_SIRA.get(alan(x, "Öncelik", "Oncelik").lower(), 3) for x in g[1])

    govde = [bas, "", "Bugünkü Etsy planın:", ""]
    for proje, liste in sorted(gruplar.items(), key=grup_oncelik):
        ikon = ONCELIK_IKON.get(alan(liste[0], "Öncelik", "Oncelik").lower(), "•")
        govde.append(f"{ikon} {proje}")
        for s in liste:
            satir = f"   • {alan(s, 'Yapılacak İş', 'Yapilacak Is')}"
            durum = alan(s, "Durum").lower()
            if durum == "devam ediyor":
                satir += "  ⏳"
            not_ = alan(s, "Not")
            if not_:
                satir += f"  — {not_}"
            govde.append(satir)
        govde.append("")

    govde.append("━━━━━━━━━━━━━━━━")
    yuksek = sum(1 for s in bekleyen if alan(s, "Öncelik", "Oncelik").lower() in ("yüksek", "yuksek"))
    ozet = f"📊 {len(bekleyen)} iş bekliyor"
    if yuksek:
        ozet += f" · {yuksek} yüksek öncelik"
    govde.append(ozet)
    if biten:
        govde.append(f"✅ Biten: {len(biten)}")
    if ertelenen:
        govde.append(f"⏸️ Ertelenen: {len(ertelenen)}")
    govde.append("\nKolay gelsin! 💪")
    return "\n".join(govde)


def sesli_metin(hafta: int, gun: int, isler: list[dict]) -> str:
    bekleyen = [s for s in isler if alan(s, "Durum").lower() not in ("bitti", "ertelendi")]
    if not bekleyen:
        return (f"Merhaba {KULLANICI_ADI}. Bugün Hafta {hafta}, Gün {gun}. "
                "Tabloda bugüne planlanmış bir iş görünmüyor. İyi günler.")
    cumleler = [f"Merhaba {KULLANICI_ADI}.",
                f"Bugün planında Hafta {hafta}, Gün {gun} var.",
                f"Toplam {len(bekleyen)} iş bekliyor."]
    for s in bekleyen:
        cumleler.append(alan(s, "Yapılacak İş", "Yapilacak Is").rstrip(".") + ".")
    cumleler.append("Kolay gelsin.")
    return " ".join(cumleler)


# --------------------------------------------------------------------------
# TELEGRAM
# --------------------------------------------------------------------------
def telegram_gonder(metin: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": metin,
                  "disable_web_page_preview": True},
            timeout=20,
        )
        ok = r.status_code == 200 and r.json().get("ok")
        print("Telegram:", "gonderildi" if ok else f"HATA {r.status_code} {r.text[:200]}")
        return bool(ok)
    except requests.RequestException as e:
        print("Telegram hatasi:", e)
        return False


# --------------------------------------------------------------------------
# SESLI OKUMA  (edge-tts / Ahmet - jarvis_api_server.py ile ayni mantik)
# --------------------------------------------------------------------------
def _pitch_uygula(mp3: bytes) -> bytes:
    if VOICE_PITCH == 1.0:
        return mp3
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3); gir = f.name
        cik = gir.rsplit(".", 1)[0] + "_p.mp3"
        # kaynak ornekleme hizi
        pr = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                             "stream=sample_rate", "-of", "csv=p=0", gir],
                            capture_output=True, text=True, timeout=15)
        sr = int((pr.stdout.strip().splitlines() or ["44100"])[0] or 44100)
        subprocess.run(["ffmpeg", "-y", "-i", gir, "-af",
                        f"asetrate={sr}*{VOICE_PITCH},aresample=44100", cik],
                       capture_output=True, timeout=20, check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = Path(cik).read_bytes()
        for p in (gir, cik):
            try: os.unlink(p)
            except OSError: pass
        return data
    except Exception as e:
        print("pitch uygulanamadi:", e)
        return mp3


def sesli_oku(metin: str) -> None:
    try:
        async def uret() -> bytes:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                yol = f.name
            await __import__("edge_tts").Communicate(metin, EDGE_VOICE, rate=EDGE_RATE).save(yol)
            veri = Path(yol).read_bytes()
            os.unlink(yol)
            return veri

        mp3 = _pitch_uygula(asyncio.run(uret()))

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3); mp3_yol = f.name
        try:
            import winsound
            wav = mp3_yol.rsplit(".", 1)[0] + ".wav"
            subprocess.run(["ffmpeg", "-y", "-i", mp3_yol, wav],
                           capture_output=True, timeout=20, check=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            winsound.PlaySound(wav, winsound.SND_FILENAME)
            for p in (wav, mp3_yol):
                try: os.unlink(p)
                except OSError: pass
        except Exception:
            from playsound import playsound
            playsound(mp3_yol)
        print("Sesli okuma: tamam")
    except Exception as e:
        print("Sesli okuma atlandi:", e)


# --------------------------------------------------------------------------
# ANA
# --------------------------------------------------------------------------
def main() -> None:
    args = [a for a in sys.argv[1:]]
    sessiz = "--sessiz" in args
    args = [a for a in args if not a.startswith("--")]
    hedef = datetime.strptime(args[0], "%Y-%m-%d").date() if args else date.today()

    fark, hafta, gun = hafta_gun(hedef)

    if fark < 0:
        gk = -fark
        metin = (f"🌅 Merhaba {KULLANICI_ADI}!\n\nEtsy planın {gk} gün sonra "
                 f"({PLAN_BASLANGIC.day} {AYLAR_TR[PLAN_BASLANGIC.month]}, Pazartesi) başlıyor. "
                 "O güne kadar hazırlık zamanı. 🙂")
        telegram_gonder(metin)
        if not sessiz:
            sesli_oku(f"Merhaba {KULLANICI_ADI}. Etsy planın {gk} gün sonra başlıyor.")
        return

    satirlar = plan_satirlarini_getir()
    isler = bugunku_isler(satirlar, hafta, gun)

    tg = telegram_metni(hedef, hafta, gun, isler)
    print("-" * 50); print(tg); print("-" * 50)
    telegram_gonder(tg)

    if not sessiz:
        sesli_oku(sesli_metin(hafta, gun, isler))


if __name__ == "__main__":
    main()
