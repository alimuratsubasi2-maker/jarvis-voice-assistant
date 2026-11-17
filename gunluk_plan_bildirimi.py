# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. - Gunluk Plan Bildirimi
--------------------------------------
Her sabah "Aylik Plan Takip - Etsy Magazasi" tablosundan o gune ait
yapilacaklari Telegram'dan Ali Murat'a gonderir.

  Test (gondermeden onizle) : python gunluk_plan_bildirimi.py --dry
  Test (gercek gonder)      : python gunluk_plan_bildirimi.py --test
  Normal calisma            : pythonw gunluk_plan_bildirimi.py

Gorev Zamanlayici bu dosyayi her gun sabah calistirir.
Sadece "requests" degil, standart kutuphane kullanir - her Python ile calisir.
"""
import os
import csv
import os
import io
import os
import sys
import os
import datetime
import os
import urllib.request
import os
import urllib.parse
import os
from pathlib import Path

# ==================== AYARLAR ====================
# Planin "1. Hafta 1. Gun"u hangi tarihe denk geliyor? (dukkani actigin gun)
# YANLISSA SADECE BU SATIRI DEGISTIR:
BASLANGIC_TARIHI = datetime.date(2026, 9, 1)

KULLANICI_ADI = "Ali Murat"

# Telegram (genel Etsy raporlari botu - TripoHelper_bot)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Google Sheet - link paylasimi ACIKSA canli okunur (senin "Bitti" isaretlerini de gorur),
# kapaliysa yanindaki plan_verisi.csv kopyasi kullanilir.
SHEET_ID = "1XSw5UcX-4T4GLtYAHCu4Wbt-Zpy_t8NkXgACHbiGXTM"
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/%s/export?format=csv&gid=0" % SHEET_ID

# Bilgisayardaysan Jarvis'in sesiyle de okusun mu? (edge-tts + playsound gerekir)
SESLI_OKU = False
# ================================================

KLASOR = Path(__file__).parent
YEREL_CSV = KLASOR / "plan_verisi.csv"
LOG_DOSYASI = KLASOR / "gunluk_plan_log.txt"

ONCELIK_IKON = {"Yüksek": "🔴", "Orta": "🟡", "Düşük": "🟢"}
AYLAR_TR = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
            "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
GUNLER_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def log(mesaj):
    satir = "[%s] %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), mesaj)
    print(satir)
    try:
        with open(LOG_DOSYASI, "a", encoding="utf-8") as f:
            f.write(satir + "\n")
    except OSError:
        pass


def plani_yukle():
    """Once Google Sheet'ten, olmazsa yerel kopyadan plan satirlarini okur."""
    metin = None
    try:
        istek = urllib.request.Request(SHEET_CSV_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(istek, timeout=15) as r:
            if r.status == 200:
                metin = r.read().decode("utf-8")
                log("Plan Google Sheet'ten (canli) okundu.")
    except Exception as e:
        log("Google Sheet okunamadi (%s). Yerel kopya kullanilacak." % e)

    if metin is None:
        metin = YEREL_CSV.read_text(encoding="utf-8")
        log("Plan yerel kopyadan okundu: %s" % YEREL_CSV.name)

    return list(csv.DictReader(io.StringIO(metin)))


def bugunun_gorevleri(satirlar, hafta, gun):
    sonuc = []
    for s in satirlar:
        try:
            if int(str(s.get("Hafta", "")).strip()) == hafta and \
               int(str(s.get("Gün", "")).strip()) == gun:
                sonuc.append(s)
        except (ValueError, TypeError):
            continue
    return sonuc


def mesaj_olustur(gorevler, bugun, hafta, gun):
    tarih_str = "%d %s %s" % (bugun.day, AYLAR_TR[bugun.month], GUNLER_TR[bugun.weekday()])
    bas = "👋 Merhaba %s!\n\n📅 <b>%s</b>  ·  %d. hafta, %d. gün\n" % (
        KULLANICI_ADI, tarih_str, hafta, gun)

    if not gorevler:
        return bas + ("\n✅ Bugün için planda kayıtlı iş yok.\n"
                      "(Bu haftayı tabloya eklemediysen bana hatırlat, ekleyeyim.)")

    gruplar = {}
    for g in gorevler:
        gruplar.setdefault(g.get("Proje", "Diğer"), []).append(g)

    satirlar = [bas, "📋 <b>Bugün yapılacaklar:</b>"]
    toplam = biten = 0
    for proje, isler in gruplar.items():
        satirlar.append("\n<b>%s</b>" % proje)
        for i in isler:
            toplam += 1
            durum = (i.get("Durum") or "").strip()
            ikon = ONCELIK_IKON.get((i.get("Öncelik") or "").strip(), "▫️")
            metin = (i.get("Yapılacak İş") or "").strip()
            if durum == "Bitti":
                biten += 1
                satirlar.append("  ✔️ <s>%s</s>" % metin)
            elif durum == "Ertelendi":
                satirlar.append("  ⏸️ %s <i>(ertelendi)</i>" % metin)
            else:
                satirlar.append("  %s %s" % (ikon, metin))

    satirlar.append("\n———")
    satirlar.append("Toplam %d iş · %d tamamlandı" % (toplam, biten))
    satirlar.append("🔴 yüksek  🟡 orta  🟢 düşük öncelik")
    return "\n".join(satirlar)


def telegram_gonder(mesaj):
    url = "https://api.telegram.org/bot%s/sendMessage" % TELEGRAM_BOT_TOKEN
    veri = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mesaj,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=veri), timeout=20) as r:
            ok = (r.status == 200)
            log("Telegram mesaji gonderildi." if ok else "Telegram HTTP %s" % r.status)
            return ok
    except Exception as e:
        log("Telegram gonderim hatasi: %s" % e)
        return False


def sesli_oku(mesaj):
    try:
        import re, asyncio, tempfile, edge_tts
        from playsound import playsound
        duz = re.sub(r"<[^>]+>", "", mesaj)
        duz = duz.replace("🔴", "").replace("🟡", "").replace("🟢", "").replace("▫️", "")
        duz = duz.replace("📋", "").replace("📅", "").replace("👋", "").replace("———", "")
        yol = str(Path(tempfile.gettempdir()) / "jarvis_plan.mp3")

        async def uret():
            c = edge_tts.Communicate(duz, "tr-TR-AhmetNeural", rate="+15%")
            await c.save(yol)

        asyncio.run(uret())
        playsound(yol)
        log("Sesli okundu.")
    except Exception as e:
        log("Sesli okuma atlandi: %s" % e)


def main():
    bugun = datetime.date.today()
    fark = (bugun - BASLANGIC_TARIHI).days
    if fark < 0:
        log("Plan henuz baslamadi (baslangic: %s)." % BASLANGIC_TARIHI)
        return
    hafta = fark // 7 + 1
    gun = fark % 7 + 1

    satirlar = plani_yukle()
    gorevler = bugunun_gorevleri(satirlar, hafta, gun)
    mesaj = mesaj_olustur(gorevler, bugun, hafta, gun)

    if "--dry" in sys.argv:
        import re
        onizleme = re.sub(r"<[^>]+>", "", mesaj)
        print("\n----- MESAJ ONIZLEME (%d. hafta %d. gun) -----\n" % (hafta, gun))
        try:
            print(onizleme)
        except UnicodeEncodeError:
            print(onizleme.encode("ascii", "replace").decode("ascii"))
        return

    telegram_gonder(mesaj)
    if SESLI_OKU:
        sesli_oku(mesaj)


if __name__ == "__main__":
    main()
