#!/usr/bin/env python3
"""Berkay Derin - 2510140024 - Vize: kayıt düğmeli IMU veri toplayıcı (Pi tarafı)

ESP32'den gelen satırları okur ve doğrular.
ESP32'nin BOOT tuşuna her basışta ($BTN) kaydı başlatır / durdurur:
  - kayıt başlayınca yeni bir CSV açar ve $LED,1 gönderir (LED yanar)
  - kayıt bitince CSV'yi kapatır, $LED,0 gönderir ve kaydın özetini yazar

Kullanım:
    python alici.py                        # /dev/serial0, 115200
    python alici.py --port /dev/pts/3      # sim_esp32.py ile, donanımsız
    python alici.py --sure 60              # 60 s sonra genel özeti yazıp çık
    python alici.py --ack-testi 20         # 20 LED komutunun ACK süresini ölç

Klavyeden (yaz + Enter):  led 0|1   hiz 1..100   k (kaydı elle başlat/durdur)   q (çık)
"""
import argparse
import csv
import math
import queue
import statistics
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import serial

from protokol import ProtokolHatasi, coz, imu_coz, kodla

OLCUM_KLASORU = Path(__file__).resolve().parent.parent / "olcum"


class Kayit:
    """Bir BOOT basışından ötekine kadar gelen IMU örneklerini CSV'ye yazar ve özetler."""

    def __init__(self, klasor: Path):
        self.yol = klasor / time.strftime("kayit_%Y%m%d_%H%M%S.csv")
        self.dosya = open(self.yol, "w", newline="")
        self.yazici = csv.writer(self.dosya)
        self.yazici.writerow(["pi_zaman_s", "t_ms", "ax_g", "ay_g", "az_g", "gx_dps", "gy_dps", "gz_dps"])
        self.ornek = 0
        self.ilk_t = self.son_t = None
        self.ivme_toplami = 0.0
        self.en_buyuk_donu = 0.0

    def ekle(self, o: dict):
        self.yazici.writerow([f"{time.time():.3f}", o["t_ms"],
                              f"{o['ax']:.3f}", f"{o['ay']:.3f}", f"{o['az']:.3f}",
                              f"{o['gx']:.2f}", f"{o['gy']:.2f}", f"{o['gz']:.2f}"])
        self.ornek += 1
        if self.ilk_t is None:
            self.ilk_t = o["t_ms"]
        self.son_t = o["t_ms"]
        self.ivme_toplami += math.sqrt(o["ax"] ** 2 + o["ay"] ** 2 + o["az"] ** 2)
        self.en_buyuk_donu = max(self.en_buyuk_donu, math.sqrt(o["gx"] ** 2 + o["gy"] ** 2 + o["gz"] ** 2))

    def kapat(self):
        self.dosya.close()
        sure = (self.son_t - self.ilk_t) / 1000 if self.ornek > 1 else 0.0
        print("\n=== Kayıt bitti ===")
        print(f"Dosya          : {self.yol.name}")
        print(f"Örnek sayısı   : {self.ornek}")
        print(f"Süre           : {sure:.2f} s (ESP32 saatine göre)")
        if self.ornek:
            print(f"Ortalama ivme  : {self.ivme_toplami / self.ornek:.3f} g  (|a|, düz dururken ~1 g)")
            print(f"En büyük dönü  : {self.en_buyuk_donu:.1f} °/s  (|ω|)")
        print("===================\n")


def klavye_dinle(kuyruk):
    for satir in sys.stdin:
        kuyruk.put(satir.strip())


def komut_cevir(metin):
    """'led 1' -> 'LED,1', 'hiz 20' -> 'HIZ,20'; tanınmıyorsa None"""
    p = metin.lower().split()
    if len(p) == 2 and p[0] in ("led", "hiz") and p[1].isdigit():
        return f"{p[0].upper()},{p[1]}"
    return None


def main():
    ap = argparse.ArgumentParser(description="Kayıt düğmeli IMU alıcısı")
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--sure", type=float, default=0, help="saniye; 0 = q yazılana kadar")
    ap.add_argument("--yazdir", type=int, default=50, help="her N örnekte bir ekrana yaz (0 = yazma)")
    ap.add_argument("--ack-testi", type=int, default=0, metavar="N", help="N adet LED komutunun ACK süresini ölç")
    args = ap.parse_args()

    OLCUM_KLASORU.mkdir(exist_ok=True)
    port = serial.Serial(args.port, args.baud, timeout=0.05)
    port.reset_input_buffer()
    klavye = queue.Queue()
    threading.Thread(target=klavye_dinle, args=(klavye,), daemon=True).start()

    olay_dosyasi = open(OLCUM_KLASORU / "dugme_olaylari.csv", "a", newline="")
    olay_yazici = csv.writer(olay_dosyasi)

    kayit = None                 # açık bir Kayit varsa kayıt sürüyor
    gecerli = 0                  # toplam geçerli IMU satırı
    hatali = Counter()           # Pi'nin yakaladığı bozuk satırlar
    esp_hatalari = Counter()     # ESP32'nin gönderdiği $ERR
    btn_sayisi = 0
    son_btn = None
    atlanan_btn = 0
    bekleyen = {}                # komut adı -> gönderme anı (perf_counter)
    ack_ms = []
    ack_gonderilen = 0
    ack_kayip = 0
    sonraki_ack = time.monotonic() + 2.0

    def gonder(govde):
        port.write(kodla(govde))
        bekleyen[govde.split(",")[0]] = time.perf_counter()

    def kaydi_degistir(neden):
        nonlocal kayit
        if kayit is None:
            kayit = Kayit(OLCUM_KLASORU)
            gonder("LED,1")
            print(f"\n>>> KAYIT BAŞLADI ({neden}) -> {kayit.yol.name}")
            olay_yazici.writerow([f"{time.time():.3f}", neden, "BASLADI", kayit.yol.name])
        else:
            gonder("LED,0")
            ad = kayit.yol.name
            kayit.kapat()
            kayit = None
            olay_yazici.writerow([f"{time.time():.3f}", neden, "BITTI", ad])
        olay_dosyasi.flush()

    baslangic = time.monotonic()
    son_durum, son_durum_gecerli = baslangic, 0
    print(f"Port {args.port} @ {args.baud}. BOOT tuşuna bas: kayıt başlar / durur.")
    print("Klavye: led 0|1, hiz 1..100, k (kayıt), q (çık)")

    try:
        while True:
            simdi = time.monotonic()
            if args.sure and simdi - baslangic >= args.sure:
                break

            # --- klavye
            try:
                metin = klavye.get_nowait()
            except queue.Empty:
                metin = None
            if metin:
                if metin.lower() == "q":
                    break
                if metin.lower() == "k":
                    kaydi_degistir("klavye")
                elif komut_cevir(metin):
                    print(f"-> ${komut_cevir(metin)}")
                    gonder(komut_cevir(metin))
                else:
                    print("Bilinmeyen komut. Örnek: led 1, hiz 20, k, q")

            # --- 1 s içinde yanıt gelmeyen komut kayıp sayılır
            for ad, t0 in list(bekleyen.items()):
                if time.perf_counter() - t0 > 1.0:
                    del bekleyen[ad]
                    ack_kayip += 1
                    print(f"!! {ad} komutuna 1 s içinde yanıt gelmedi")

            # --- otomatik ACK testi (kayıt yokken; LED'i sırayla yakıp söndürür)
            if ack_gonderilen < args.ack_testi and simdi >= sonraki_ack and not bekleyen and kayit is None:
                ack_gonderilen += 1
                gonder(f"LED,{ack_gonderilen % 2}")
                sonraki_ack = simdi + 0.3

            # --- seri porttan bir satır
            ham = port.readline()
            if ham:
                try:
                    alanlar = coz(ham)
                except ProtokolHatasi as h:
                    hatali[h.neden] += 1
                    alanlar = None

                if alanlar and alanlar[0] == "IMU":
                    try:
                        o = imu_coz(alanlar)
                    except ProtokolHatasi as h:
                        hatali[h.neden] += 1
                    else:
                        gecerli += 1
                        if kayit:
                            kayit.ekle(o)
                        if args.yazdir and gecerli % args.yazdir == 0:
                            durum = "KAYIT" if kayit else "bekle"
                            print(f"[{durum}] t={o['t_ms']:>8} ms  a=({o['ax']:+.2f} {o['ay']:+.2f} {o['az']:+.2f}) g  "
                                  f"w=({o['gx']:+6.1f} {o['gy']:+6.1f} {o['gz']:+6.1f}) °/s")

                elif alanlar and alanlar[0] == "BTN" and len(alanlar) == 2 and alanlar[1].isdigit():
                    n = int(alanlar[1])
                    btn_sayisi += 1
                    if son_btn is not None and n != son_btn + 1:
                        atlanan_btn += n - son_btn - 1
                        print(f"!! BTN sırası atladı: {son_btn} -> {n}")
                    son_btn = n
                    print(f"<- BTN {n}")
                    olay_yazici.writerow([f"{time.time():.3f}", f"BTN,{n}", "BASIS", ""])
                    kaydi_degistir(f"BTN {n}")

                elif alanlar and alanlar[0] == "ACK" and len(alanlar) == 3:
                    t0 = bekleyen.pop(alanlar[1], None)
                    if t0 is not None:
                        ms = (time.perf_counter() - t0) * 1000
                        ack_ms.append(ms)
                        print(f"<- ACK {alanlar[1]} {alanlar[2]}  ({ms:.1f} ms)")
                    else:
                        print(f"<- ACK {alanlar[1]} {alanlar[2]}")

                elif alanlar and alanlar[0] == "ERR":
                    neden = alanlar[1] if len(alanlar) > 1 else "?"
                    esp_hatalari[neden] += 1
                    bekleyen.clear()
                    print(f"<- ESP32 hata: {neden}")

                elif alanlar:
                    hatali["BICIM"] += 1

            # --- 5 saniyede bir durum
            if simdi - son_durum >= 5:
                hiz = (gecerli - son_durum_gecerli) / (simdi - son_durum)
                print(f"[{simdi - baslangic:5.0f} s] {hiz:5.1f} Hz | geçerli {gecerli} | hatalı {sum(hatali.values())}"
                      f" | kayıt {'AÇIK' if kayit else 'kapalı'}")
                son_durum, son_durum_gecerli = simdi, gecerli
    except KeyboardInterrupt:
        pass
    except serial.SerialException as h:
        print(f"!! Seri port hatası, durduruldu: {h}")

    if kayit:                      # program kapanırken açık kayıt kalmasın
        kaydi_degistir("çıkış")
        time.sleep(0.1)
    sure = time.monotonic() - baslangic
    port.close()
    olay_dosyasi.close()

    print("\n--- Genel özet ---")
    print(f"Süre: {sure:.1f} s | geçerli IMU satırı: {gecerli} | ortalama hız: {gecerli / sure:.2f} Hz")
    print(f"Hatalı satır: {sum(hatali.values())} {dict(hatali) if hatali else ''}")
    if esp_hatalari:
        print(f"ESP32'nin bildirdiği hatalar: {dict(esp_hatalari)}")
    print(f"BTN mesajı: {btn_sayisi} | sırada atlanan: {atlanan_btn}")
    if ack_ms:
        print(f"Komut-ACK süresi ({len(ack_ms)} komut): en kısa {min(ack_ms):.1f} ms, "
              f"ortalama {statistics.mean(ack_ms):.1f} ms, en uzun {max(ack_ms):.1f} ms")
    if ack_kayip:
        print(f"Yanıtsız kalan komut: {ack_kayip}")


if __name__ == "__main__":
    main()
