# Vize: Kayıt düğmeli IMU veri toplayıcı

Berkay Derin, 2510140024. İleri Gömülü Sistemler.

ESP32-S3, MPU-6050'yi 50 Hz okuyup ölçümleri UART ile Raspberry Pi'ye gönderir. ESP32 kartındaki **BOOT tuşu (GPIO0)** kayıt düğmesidir: her basışta ESP32 `$BTN,<n>` gönderir, Pi kaydı başlatır veya durdurur. Kayıt sürerken Pi `$LED,1` ile LED'i yakar. Kayıt bitince Pi örnek sayısı, süre, ortalama ivme ve en büyük dönü hızından oluşan bir özet yazar.

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

## Çalıştırma

```
cd esp32 && idf.py set-target esp32s3 && idf.py build flash monitor     # ESP-IDF v6.1
cd pi && python alici.py                  # Pi'de
python sim_esp32.py                       # donanımsız deneme (çıkan portu alici.py --port ile ver)
```

## Dosyalar

- `esp32/main/main.c`: ölçüm (esp_timer + görev), komut alma, BOOT tuşu (kesme + sıçrama süzme), gönderim kuyruğu
- `pi/protokol.py`: kodla / coz / imu_coz
- `pi/alici.py`: doğrulama, `$BTN` ile kayıt aç/kapa, LED, kayıt özeti, ACK süresi ölçümü
- `pi/sim_esp32.py`: ESP32 benzetici (Enter = BOOT tuşu)
