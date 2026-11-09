"""Rapor şekilleri, olcum/ klasöründeki kayıtlardan çizilir.

Kullanım: python sekil_ciz.py <olcum klasörü> <çıktı klasörü>     (matplotlib gerekir)
"""
import csv
import math
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

OLCUM, CIKTI = Path(sys.argv[1]), Path(sys.argv[2])
CIKTI.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({
    "font.family": "Carlito", "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#8a8984", "axes.linewidth": 0.6, "xtick.color": "#52514e", "ytick.color": "#52514e",
})
ANA = "#0f6e56"          # rapor ana rengi (koyu teal)
DOLGU = "#e1f5ee"
IVME, DONU = "#2a78d6", "#eb6834"
GRI = "#52514e"


# ------------------------------------------------------------ Şekil 1: blok şema
def kutu(ax, x, y, w, h, baslik, satirlar):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006,rounding_size=0.012",
                                fc=DOLGU, ec=ANA, lw=1.0))
    ax.text(x + w / 2, y + h - 0.04, baslik, ha="center", va="top", fontsize=8.6, fontweight="bold", color=ANA)
    ax.text(x + 0.012, y + h - 0.12, "\n".join(satirlar), ha="left", va="top", fontsize=7.1,
            color="#1a1a1a", linespacing=1.3)


def ok(ax, x0, y0, x1, y1, yazi, alt=False):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=8, lw=0.9, color="#2b2b2a"))
    ax.text((x0 + x1) / 2, (y0 + y1) / 2 + (-0.02 if alt else 0.02), yazi, ha="center",
            va="top" if alt else "bottom", fontsize=6.9, color="#2b2b2a")


fig = plt.figure(figsize=(7.1, 2.05))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
kutu(ax, 0.005, 0.50, 0.15, 0.45, "MPU-6050", ["(çip: MPU-6500)", "±2 g · ±250 °/s", "I²C adres 0x68"])
kutu(ax, 0.005, 0.04, 0.15, 0.36, "BOOT tuşu", ["GPIO0, pull-up", "basınca 0 okunur"])
kutu(ax, 0.245, 0.03, 0.30, 0.94, "ESP32-S3", [
    "esp_timer 20 ms → sensor_gorevi (5)",
    "  14 bayt oku → \\$IMU",
    "GPIO0 kesmesi → dugme_gorevi (4)",
    "  30 ms bekle, hâlâ 0 → \\$BTN,n",
    "komut_gorevi (6): '$' ile senkron,",
    "  checksum → LED (GPIO4) / HIZ",
    "gonderici_gorevi (7): kuyruk → UART",
    "  satırlar asla birbirine karışmaz"])
kutu(ax, 0.685, 0.03, 0.31, 0.94, "Raspberry Pi 4", [
    "protokol.py: kodla / coz / imu_coz",
    "alici.py:",
    "  \\$BTN → kayıt aç/kapa (CSV)",
    "  kayıt açıkken \\$LED,1, bitince \\$LED,0",
    "  kayıt özeti: örnek, süre,",
    "  ort. |a|, en büyük |ω|",
    "  ACK süresi ölçümü",
    "sim_esp32.py: donanımsız deneme"])
ok(ax, 0.155, 0.72, 0.245, 0.72, "I²C 400 kHz")
ok(ax, 0.155, 0.22, 0.245, 0.22, "kesme")
ok(ax, 0.545, 0.70, 0.685, 0.70, "\\$IMU · \\$BTN · \\$ACK · \\$ERR")
ok(ax, 0.685, 0.50, 0.545, 0.50, "\\$LED · \\$HIZ", alt=True)
ax.text(0.615, 0.36, "UART1 115200 8N1\nTX17 → pin 10\nRX18 ← pin 8\nortak GND (pin 6)",
        ha="center", va="top", fontsize=6.6, color=GRI, linespacing=1.2)
fig.savefig(CIKTI / "sekil1_mimari.png", dpi=220)
plt.close(fig)


# ------------------------------------------------------------ Şekil 2: ölçümler
def kayit(ad):
    with open(OLCUM / ad, newline="") as f:
        s = list(csv.DictReader(f))
    t0 = int(s[0]["t_ms"])
    t = [(int(r["t_ms"]) - t0) / 1000 for r in s]
    a = [math.sqrt(sum(float(r[k]) ** 2 for k in ("ax_g", "ay_g", "az_g"))) for r in s]
    w = [math.sqrt(sum(float(r[k]) ** 2 for k in ("gx_dps", "gy_dps", "gz_dps"))) for r in s]
    return t, a, w


def ack_sureleri(ad):
    return [float(x) for x in re.findall(r"ACK LED \d\s+\(([\d.]+) ms\)", (OLCUM / ad).read_text())]


def kenarlar(ad, ilk, son):
    m = re.findall(r"Basis (\d+): bu basista (\d+) ham kenar", (OLCUM / ad).read_text())
    return [(int(n), int(k)) for n, k in m if ilk <= int(n) <= son]


fig = plt.figure(figsize=(7.1, 2.25))
gs = fig.add_gridspec(1, 3, width_ratios=[2.1, 1.05, 1.15], wspace=0.62, left=0.065, right=0.99, top=0.86, bottom=0.2)

t, a, w = kayit("kayit_20261104_003054.csv")
ax1 = fig.add_subplot(gs[0])
ax1.plot(t, w, color=DONU, lw=0.9, label="|ω| (°/s)")
ax1.set_ylabel("|ω| (°/s)", color=DONU)
ax1.set_xlabel("kayıt süresi (s)")
ax1.set_xlim(0, t[-1])
ax1b = ax1.twinx()
ax1b.spines["right"].set_visible(True)
ax1b.plot(t, a, color=IVME, lw=0.9)
ax1b.set_ylim(0.6, 1.6)
ax1b.set_ylabel("|a| (g)", color=IVME)
ax1.set_title("(a) Bir kayıt: BOOT → BOOT, 1291 örnek, 25,8 s", loc="left", fontweight="bold")
ax1.grid(axis="y", color="#e4e3de", lw=0.5)

ax2 = fig.add_subplot(gs[1])
once, ack, btn = [23.7], ack_sureleri("ack_20.txt"), ack_sureleri("btn_20.txt")
for i, (ad, d, renk) in enumerate((("düzeltme\nöncesi", once, "#b4b2a9"), ("ack_20", ack, ANA), ("btn_20", btn, "#1d9e75"))):
    ax2.scatter([i + (j % 5 - 2) * 0.06 for j in range(len(d))], d, s=9, color=renk, zorder=3, lw=0)
ax2.set_xticks([0, 1, 2], ["düzeltme\nöncesi", "ACK testi\n(20)", "tuş testi\n(20)"])
ax2.set_yscale("log"); ax2.set_ylim(3, 30)
ax2.set_yticks([3, 4, 5, 6, 10, 20, 30], ["3", "4", "5", "6", "10", "20", "30"])
ax2.minorticks_off()
ax2.set_ylabel("LED komutu → ACK (ms)")
ax2.set_title("(b) Komut–ACK süresi", loc="left", fontweight="bold")
ax2.grid(axis="y", color="#e4e3de", lw=0.5)

ax3 = fig.add_subplot(gs[2])
k = kenarlar("btn_esp32_monitor.txt", 2, 21)
ax3.bar([n - 1 for n, _ in k], [x for _, x in k], color="#b4b2a9", width=0.75, label="ham kenar")
ax3.scatter([n - 1 for n, _ in k], [1] * len(k), color=ANA, s=10, zorder=3, label="gönderilen \\$BTN")
ax3.set_xlabel("basış (1–20)")
ax3.set_yticks([0, 1, 2, 3])
ax3.set_title("(c) Tuş sıçraması", loc="left", fontweight="bold")
ax3.legend(fontsize=6.8, frameon=False, loc="upper right")
ax3.set_ylim(0, 3.9)
fig.savefig(CIKTI / "sekil2_olcumler.png", dpi=220)
plt.close(fig)
print("şekiller:", sorted(p.name for p in CIKTI.iterdir()))
