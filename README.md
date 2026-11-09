# Vize: Kayıt düğmeli IMU veri toplayıcı

Berkay Derin, 2510140024. İleri Gömülü Sistemler.

ESP32-S3, MPU-6050'yi 50 Hz'de okuyup ölçümleri UART ile Raspberry Pi'ye gönderir. ESP32 kartındaki **BOOT tuşu (GPIO0)** kayıt düğmesidir: her basışta ESP32 `$BTN,<n>` gönderir, Pi kaydı başlatır veya durdurur. Kayıt sürerken Pi `$LED,1` ile LED'i yakar. Kayıt bitince Pi örnek sayısı, süre, ortalama ivme ve en büyük dönü hızından oluşan bir özet yazar.

## Malzemeler

| Malzeme | Adet | Not |
|---|---|---|
| ESP32-S3 DevKitC-1 uyumlu kart (YD-ESP32-S3) + USB veri kablosu | 1 | programlama ve besleme |
| Raspberry Pi 4 + 5,1 V / 3 A adaptör + microSD | 1 | Raspberry Pi OS Lite 64-bit, SSH açık |
| MPU-6050 modülü (GY-521; kartımdaki çip MPU-6500, WHO_AM_I = 0x70) | 1 | I²C, adres 0x68 |
| LED + 330 Ω direnç | 1 | GPIO4 |
| Breadboard, dişi-erkek atlama kabloları | ~10 | |

## Bağlantılar

| ESP32-S3 | Nereye |
|---|---|
| GPIO17 (TX) | Pi pin 10 (RXD) |
| GPIO18 (RX) | Pi pin 8 (TXD) |
| G | Pi pin 6 (GND), ortak GND rayı |
| GPIO4 | 330 Ω → LED → GND |
| 3V3 / G | MPU-6050 VCC / GND |
| GPIO8 / GPIO9 | MPU-6050 SDA / SCL |
| GPIO0 | kart üzerindeki BOOT tuşu (kablo yok) |

## Protokol

`$GOVDE*HH\r\n`: HH, `$` ile `*` arasındaki karakterlerin XOR'udur. Bağlantı 115200 8N1.

| Yön | Satır |
|---|---|
| ESP32 → Pi | `$IMU,t_ms,ax,ay,az,gx,gy,gz` (g, °/s) · `$BTN,n` · `$ACK,komut,değer` · `$ERR,BICIM\|CHECKSUM\|KOMUT\|I2C` |
| Pi → ESP32 | `$LED,0\|1` · `$HIZ,1..100` |

## Raspberry Pi kurulumu (bir kez)

```
sudo raspi-config nonint do_serial_cons 1      # seri konsol kapalı
sudo raspi-config nonint do_serial_hw 0        # seri donanım açık
echo "dtoverlay=disable-bt" | sudo tee -a /boot/firmware/config.txt   # serial0 -> ttyAMA0 (sabit hızlı UART)
python3 -m venv ~/yz && ~/yz/bin/pip install pyserial
sudo reboot
ls -l /dev/serial0                             # -> ttyAMA0
```

## Çalıştırma

```
cd esp32 && idf.py set-target esp32s3 && idf.py build flash monitor     # ESP-IDF v6.1
cd pi && ~/yz/bin/python alici.py         # Pi'de; --ack-testi 20, --sure 60
python sim_esp32.py                       # donanımsız deneme (çıkan portu alici.py --port ile ver)
```

## Dosyalar

- `esp32/main/main.c`: ölçüm (esp_timer + görev), komut alma, BOOT tuşu (kesme + sıçrama süzme), gönderim kuyruğu
- `pi/protokol.py`: kodla / coz / imu_coz
- `pi/alici.py`: doğrulama, `$BTN` ile kayıt aç/kapa, LED, kayıt özeti, ACK süresi ölçümü
- `pi/sim_esp32.py`: ESP32 benzetici (Enter = BOOT tuşu)
- `olcum/`: ölçüm kayıtları ve açıklaması (`olcum/README.md`)
- `rapor/rapor.pdf`: 3 sayfalık rapor; `rapor/sekil_ciz.py` şekilleri `olcum/`dan yeniden çizer
