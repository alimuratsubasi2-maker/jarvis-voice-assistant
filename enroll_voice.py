#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ses Kaydı (Konuşmacı Tanıma Kurulumu)
========================================
JARVIS'in SADECE senin sesini tanıyıp başkalarının/etraftaki seslerin
komutlarını görmezden gelmesi için, senin ses örneğini kaydedip bir
"ses profili" oluşturur.

Kullanım:
    python enroll_voice.py

Birkaç cümle söylemen istenecek. Her kayıttan sonra sana GERİ ÇALINIR -
doğru geldiyse Enter'a bas, yanlış/eksik geldiyse "r" yazıp tekrar
kaydedebilirsin. Sonra jarvis_voice_server.py otomatik olarak bu profili
kullanır.

Yeniden kaydetmek istersen bu scripti tekrar çalıştırman yeterli - eski
profilin üzerine yazar.
"""

import tempfile
from pathlib import Path

import numpy as np
import speech_recognition as sr
from resemblyzer import VoiceEncoder, preprocess_wav

HERE = Path(__file__).resolve().parent
PROFILE_FILE = HERE / "voice_profile.npy"

PHRASES = [
    "Merhaba, ben Jarvis'in sahibiyim.",
    "Bugün hava nasıl, saat kaç, ne yapıyoruz.",
    "Bu benim gerçek sesim, lütfen beni tanı.",
]


def _play(wav_path: str) -> None:
    try:
        from playsound import playsound
        playsound(wav_path)
    except Exception as exc:
        print(f"(Geri oynatma basarisiz: {exc} - devam ediyoruz)")


def _record_one(recognizer: sr.Recognizer, mic: sr.Microphone, phrase: str, index: int, total: int) -> str:
    while True:
        input(f'\n[{index}/{total}] Hazır olduğunda Enter\'a bas, sonra şunu oku:\n  "{phrase}"\n> ')
        print("Kaydediliyor... (konuş)")
        with mic as source:
            audio = recognizer.listen(source, timeout=10, phrase_time_limit=8)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio.get_wav_data())
            wav_path = f.name

        print("Kaydedildi. Sana geri çalıyorum, dinle:")
        _play(wav_path)

        choice = input("Doğru geldiyse Enter'a bas, tekrar kaydetmek icin 'r' yaz: ").strip().lower()
        if choice != "r":
            return wav_path
        print("Tamam, tekrar deniyoruz.\n")


def main() -> None:
    print("=" * 60)
    print("  SES KAYDI - Konuşmacı Tanıma Kurulumu")
    print("=" * 60)
    print("\nAşağıdaki cümleleri normal ses tonunla, mikrofona yakın şekilde")
    print("oku. Her kayıttan sonra sana geri çalınacak - doğruysa Enter,")
    print("yanlışsa 'r' yazıp tekrar kaydedebilirsin.\n")

    recognizer = sr.Recognizer()
    mic = sr.Microphone()

    with mic as source:
        print("Ortam gürültüsüne ayarlanıyor, bir sn sessiz kal...")
        recognizer.adjust_for_ambient_noise(source, duration=1.0)

    wav_paths = []
    for i, phrase in enumerate(PHRASES, 1):
        wav_paths.append(_record_one(recognizer, mic, phrase, i, len(PHRASES)))

    print("\nSes profili oluşturuluyor...")
    encoder = VoiceEncoder()
    embeddings = []
    for wav_path in wav_paths:
        wav = preprocess_wav(wav_path)
        embeddings.append(encoder.embed_utterance(wav))

    profile = np.mean(embeddings, axis=0)
    np.save(PROFILE_FILE, profile)

    print(f"\nTamam! Ses profili kaydedildi: {PROFILE_FILE}")
    print("Artık JARVIS'i yeniden başlattığında sadece senin sesinle verdiğin")
    print("komutları işleyecek, başka sesleri/gürültüyü görmezden gelecek.")


if __name__ == "__main__":
    main()
