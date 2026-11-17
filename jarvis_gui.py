#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S. Pencere
=======================
Gercek, gorunur, basliga sahip bir uygulama penceresi (Obsidian gibi).
jarvis_status.json dosyasini okuyarak (idle/listening/thinking/speaking)
durumuna gore parcacikli kureyi gunceller.

jarvis_voice_server.py tarafindan otomatik acilir; tek basina da calisir:
    python jarvis_gui.py
"""

import json
import math
import os
import random
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATUS_FILE = HERE / "jarvis_status.json"

if sys.stdout is None or sys.stderr is None:
    _log_file = open(HERE / "jarvis_gui_log.txt", "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_file
    sys.stderr = _log_file

STATE_STYLE = {
    "idle": {"color": (110, 227, 234), "label": "Hazır"},
    "listening": {"color": (89, 216, 140), "label": "Dinliyor"},
    "thinking": {"color": (240, 168, 62), "label": "Düşünüyor"},
    "speaking": {"color": (189, 247, 249), "label": "Konuşuyor"},
    "offline": {"color": (92, 96, 103), "label": "Çevrimdışı"},
    "error": {"color": (248, 113, 113), "label": "Hata"},
}


class JarvisApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("J.A.R.V.I.S.")
        w, h = 380, 480
        self.configure(bg="#0a0a0c")
        self.resizable(False, False)

        self.update_idletasks()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self.attributes("-topmost", True)
        self.after(1500, lambda: self.attributes("-topmost", False))
        self.lift()
        self.focus_force()

        tk.Label(self, text="J.A.R.V.I.S.", fg="#eef0f2", bg="#0a0a0c",
                 font=("Segoe UI", 15, "bold")).pack(pady=(22, 2))
        tk.Label(self, text="Kişisel Sesli Asistan", fg="#5c6067", bg="#0a0a0c",
                 font=("Segoe UI", 10)).pack(pady=(0, 10))

        self.canvas = tk.Canvas(self, width=240, height=240, bg="#0a0a0c", highlightthickness=0)
        self.canvas.pack(pady=6)

        self.state_label = tk.Label(self, text="Başlatılıyor…", fg="#9a9ea6", bg="#0a0a0c",
                                     font=("Consolas", 11))
        self.state_label.pack(pady=(6, 2))

        self.text_label = tk.Label(self, text="", fg="#eef0f2", bg="#0a0a0c",
                                    font=("Segoe UI", 9), wraplength=340, justify="center")
        self.text_label.pack(pady=(0, 10), padx=16)

        tk.Label(self, text='Uyanma kelimesi: "merhaba jarvis"', fg="#5c6067", bg="#0a0a0c",
                 font=("Segoe UI", 9)).pack(side="bottom", pady=14)

        self.particles = [(random.uniform(0, math.pi), random.uniform(0, 2 * math.pi)) for _ in range(120)]
        self.rotation = 0.0
        self.last_status_check = 0.0
        self.cached_state = "offline"
        self.cached_text = ""

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._animate()

    def _on_close(self):
        # Kureyi kapatinca arka plandaki sesli asistan sureci de (jarvis.lock'taki
        # PID) kapatilsin - yoksa gorunmez sekilde calismaya devam edip yeni
        # tiklamalarda "zaten calisiyor" deyip hicbir pencere acmiyordu.
        lock_path = HERE / "jarvis.lock"
        try:
            pid = lock_path.read_text().strip()
            subprocess.run(
                ["taskkill", "/F", "/PID", pid],
                capture_output=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass
        self.destroy()
        os._exit(0)

    def _read_status(self):
        now = time.time()
        if now - self.last_status_check < 0.3:
            return self.cached_state, self.cached_text
        self.last_status_check = now
        try:
            data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
            ts = data.get("ts", 0)
            if now - ts > 20:
                self.cached_state, self.cached_text = "offline", ""
            else:
                self.cached_state = data.get("state", "offline")
                self.cached_text = data.get("text", "")
        except (OSError, json.JSONDecodeError):
            self.cached_state, self.cached_text = "offline", ""
        return self.cached_state, self.cached_text

    def _animate(self):
        mode, text = self._read_status()
        style = STATE_STYLE.get(mode, STATE_STYLE["idle"])
        r, g, b = style["color"]
        self.state_label.config(text=style["label"])
        self.text_label.config(text=(text[:140] + "…") if len(text) > 140 else text)

        self.rotation += 0.01
        pulse = 1.0
        if mode in ("listening", "speaking"):
            pulse = 1.0 + 0.08 * math.sin(time.time() * 6)

        self.canvas.delete("all")
        cx, cy, R = 120, 120, 78 * pulse

        rendered = []
        for theta, phi in self.particles:
            x0 = R * math.sin(theta) * math.cos(phi + self.rotation)
            z0 = R * math.sin(theta) * math.sin(phi + self.rotation)
            y0 = R * math.cos(theta)
            depth = (z0 + R) / (2 * R) if R else 0
            rendered.append((depth, cx + x0, cy + y0, 1 + 1.8 * depth))

        rendered.sort(key=lambda it: it[0])
        for depth, x, y, size in rendered:
            shade = 0.35 + depth * 0.65
            color = f"#{min(255,int(r*shade+30)):02x}{min(255,int(g*shade+30)):02x}{min(255,int(b*shade+30)):02x}"
            self.canvas.create_oval(x - size, y - size, x + size, y + size, outline="", fill=color)

        self.after(40, self._animate)


if __name__ == "__main__":
    app = JarvisApp()
    app.mainloop()
