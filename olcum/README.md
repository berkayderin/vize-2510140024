# Ölçüm kayıtları

Tüm kayıtlar 04.11.2026 gecesi alındı. `.txt` dosyaları programın ekran çıktısıdır (`| tee`), `kayit_*.csv` dosyalarını ise `alici.py` her kayıt için kendisi yazar.

## Dosya biçimleri

| Dosya | Sütunlar |
|---|---|
| `kayit_<zaman>.csv` | `pi_zaman_s` (Pi saati, s), `t_ms` (ESP32 saati, ms), `ax_g ay_g az_g` (g), `gx_dps gy_dps gz_dps` (°/s) |
| `dugme_olaylari.csv` | Pi saati, olay kaynağı (`BTN,n` / `BTN n` / `çıkış`), olay (`BASIS` / `BASLADI` / `BITTI`), kayıt dosyası |

## Dosyalar

| Dosya | Ne |
|---|---|
| `ack_20.txt` | 20 `$LED` komutunun ACK süresi: en kısa 4,0 ms, ortalama 4,2 ms, en uzun 4,3 ms; 20/20 yanıt |
| `btn_20.txt` | 60 s içinde BOOT tuşuna 20 basış: 20 `$BTN` (2→21), sıra atlamadı; aynı çalıştırmada 3001 satır / 60,0 s = 50,00 Hz, 0 hatalı |
| `btn_esp32_monitor.txt` | Aynı 20 basışın ESP32 tarafı (Basış 2–21): basış başına ham kenar sayısı. Basış 4'te 3 kenar (sıçrama), yine de 1 `$BTN` |
| `hiz_60s.txt`, `kayit_20261104_003640.csv` | 65 s'lik çalıştırma, sensör düz: 3251 satır, 49,92 Hz; kayıt 52,46 s, 2624 örnek, aralıkların hepsi 20 ms |
| `kayit_20261104_003808.csv` … `003822.csv` | `btn_20.txt` sırasında açılıp kapanan 10 kısa kayıt (her biri iki basış arası) |
| `kayit_20261104_002919.csv`, `kayit_20261104_003054.csv` | İlk iki kayıt (breadboard elle eğildi). 003054'te LED ACK 23,7 ms ölçüldü; bu, düzeltmeden önceki sürümdür |
| `ilk_deneme_esp32_monitor.txt` | İlk yükleme: "Kuyruk dolu" uyarıları (10 s'de ~350 satır atıldı). Sebep: Pi'de açık seri konsol ve eksik ortak GND |

13 kayıt dosyasındaki 6 607 örnek aralığının hepsi 20 ms'dir (örnek kaybı yok).
