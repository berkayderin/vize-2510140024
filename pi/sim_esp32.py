#!/usr/bin/env python3
"""ESP32 benzetici: donanım olmadan alici.py'yi denemek için.

Sahte bir seri port (pty) açar, adını yazar. O porta:
  - seçilen hızda (varsayılan 50 Hz) sahte $IMU satırları gönderir
  - $LED ve $HIZ komutlarına $ACK / $ERR ile yanıt verir
  - bu pencerede Enter'a basınca $BTN,<n> gönderir (BOOT tuşu yerine)

Kullanım:
    python sim_esp32.py          # çıkan /dev/pts/N adını alici.py --port ile ver
"""
import math
import os
import random
import sys
import threading
import time
import tty

from protokol import ProtokolHatasi, coz, kodla

ana, yan = os.openpty()
tty.setraw(yan)                     # satır sonlarına dokunulmasın
print(f"Sahte ESP32 portu: {os.ttyname(yan)}")
print("Enter = BOOT tuşuna basmak ($BTN). Çıkmak için Ctrl+C.")

kilit = threading.Lock()
hiz_hz = 50
basis = 0
baslangic = time.monotonic()


def yaz(govde):
    with kilit:
        os.write(ana, kodla(govde))


def olcum_dongusu():
    sonraki = time.monotonic()
    while True:
        sonraki += 1 / hiz_hz
        t = time.monotonic() - baslangic
        aci = 0.3 * math.sin(t)              # kart yavaşça sallanıyormuş gibi
        ax, az = math.sin(aci), math.cos(aci)
        gy = 0.3 * math.cos(t) * 180 / math.pi
        g = lambda: random.gauss(0, 0.5)
        yaz(f"IMU,{int(t * 1000)},{ax:.3f},{random.gauss(0, 0.005):.3f},{az:.3f},{g():.2f},{gy + g():.2f},{g():.2f}")
        time.sleep(max(0, sonraki - time.monotonic()))


def komut_dongusu():
    global hiz_hz
    tampon = b""
    satirlar = []
    while True:
        for b in os.read(ana, 256):
            c = bytes([b])
            if c == b"$":                     # ESP32 gibi: her '$' yeni satır, yarım veri atılır
                tampon = b"$"
            elif c == b"\n":
                if tampon:
                    satirlar.append(tampon)
                tampon = b""
            elif tampon:
                tampon += c
        while satirlar:
            satir = satirlar.pop(0)
            try:
                alanlar = coz(satir)
            except ProtokolHatasi as h:
                yaz(f"ERR,{h.neden}")
                continue
            if len(alanlar) == 2 and alanlar[0] == "LED" and alanlar[1] in ("0", "1"):
                yaz(f"ACK,LED,{alanlar[1]}")
                print(f"[sim] LED {'YANDI' if alanlar[1] == '1' else 'söndü'}")
            elif len(alanlar) == 2 and alanlar[0] == "HIZ" and alanlar[1].isdigit() and 1 <= int(alanlar[1]) <= 100:
                hiz_hz = int(alanlar[1])
                yaz(f"ACK,HIZ,{hiz_hz}")
            elif alanlar[0] in ("LED", "HIZ"):
                yaz("ERR,BICIM")
            else:
                yaz("ERR,KOMUT")


threading.Thread(target=olcum_dongusu, daemon=True).start()
threading.Thread(target=komut_dongusu, daemon=True).start()
try:
    for _ in sys.stdin:
        basis += 1
        yaz(f"BTN,{basis}")
        print(f"[sim] BTN,{basis} gönderildi")
except KeyboardInterrupt:
    pass
