/*
 * Berkay Derin - 2510140024
 * İleri Gömülü Sistemler - Vize projesi: kayıt düğmeli IMU veri toplayıcı
 *
 * ESP32-S3 tarafı:
 *   - MPU-6050'yi (I2C, SDA=8, SCL=9) zamanlayıcıyla 50 Hz okur, $IMU satırı gönderir
 *   - Pi'den $LED ve $HIZ komutlarını alır, $ACK veya $ERR ile yanıtlar
 *   - Kart üzerindeki BOOT tuşuna (GPIO0) her basışta $BTN,<sayaç> gönderir
 *   - LED: GPIO4 (330 ohm dirençle)
 *   - UART1: TX=17 -> Pi RXD (pin 10), RX=18 <- Pi TXD (pin 8), 115200 8N1
 *
 * Satır biçimi: $GOVDE*HH\r\n   (HH = '$' ile '*' arasındaki karakterlerin XOR'u)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "driver/uart.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_timer.h"
#include "esp_log.h"

static const char *TAG = "vize";

/* ---- pinler ---- */
#define PI_UART        UART_NUM_1
#define PI_TX_PIN      17
#define PI_RX_PIN      18
#define PI_BAUD        115200
#define LED_PIN        GPIO_NUM_4
#define DUGME_PIN      GPIO_NUM_0      /* BOOT tuşu: basılınca 0 okunur */
#define SDA_PIN        8
#define SCL_PIN        9

/* ---- MPU-6050 kayıtları ---- */
#define MPU_ADRES      0x68
#define MPU_SMPLRT_DIV 0x19
#define MPU_CONFIG     0x1A
#define MPU_GYRO_CFG   0x1B
#define MPU_ACCEL_CFG  0x1C
#define MPU_VERI       0x3B            /* ACCEL_XOUT_H'den başlayan 14 bayt */
#define MPU_PWR_MGMT_1 0x6B
#define MPU_WHO_AM_I   0x75

#define IVME_OLCEK     16384.0f        /* ±2 g    -> 16384 LSB/g     */
#define DONU_OLCEK     131.0f          /* ±250 °/s -> 131 LSB/(°/s)  */

#define SATIR_BOYU     112             /* gönderilecek bir satırın en uzun hali */
#define ALMA_SINIRI    95              /* gelen bir satırın en uzun hali        */
#define SICRAMA_MS     30              /* tuş sıçramasını beklemek için süre    */

/* Gönderilecek satırlar bu kuyrukta bekler; UART'a yalnızca gonderici_gorevi yazar.
 * Böylece üç görev aynı anda yazmaya çalışsa da satırlar birbirine karışmaz. */
typedef struct { char metin[SATIR_BOYU]; } satir_t;
static QueueHandle_t gonderim_kuyrugu;

static i2c_master_dev_handle_t mpu;
static esp_timer_handle_t olcum_zamanlayici;
static TaskHandle_t sensor_gorev_tutamaci;
static SemaphoreHandle_t dugme_isareti;
static volatile uint32_t ham_kenar_sayisi;   /* kesmede sayılır: sıçramayı görmek için */
static int olcum_hizi_hz = 50;
static uint32_t kayip_satir;                 /* kuyruk dolu olduğu için atılan satır */
static uint32_t gonderilen_satir, alinan_bayt; /* teşhis sayaçları */
static int64_t en_uzun_yazma_us;
static uint32_t yanki_satir;                 /* geri gelen kendi satırlarımız */

/* ================================================================ protokol */
static uint8_t xor_toplami(const char *s, size_t n)
{
    uint8_t x = 0;
    for (size_t i = 0; i < n; i++) x ^= (uint8_t)s[i];
    return x;
}

/* govde: "IMU,123,..." gibi; başına '$', sonuna '*HH\r\n' eklenip kuyruğa konur */
static void gonder(const char *govde)
{
    satir_t s;
    size_t n = strlen(govde);
    if (n > SATIR_BOYU - 8) n = SATIR_BOYU - 8;
    snprintf(s.metin, sizeof s.metin, "$%.*s*%02X\r\n", (int)n, govde, xor_toplami(govde, n));
    if (xQueueSend(gonderim_kuyrugu, &s, 0) != pdTRUE) kayip_satir++;
}

static void gonderici_gorevi(void *arg)
{
    satir_t s;
    for (;;) {
        if (xQueueReceive(gonderim_kuyrugu, &s, portMAX_DELAY) == pdTRUE) {
            int64_t t0 = esp_timer_get_time();
            uart_write_bytes(PI_UART, s.metin, strlen(s.metin));
            int64_t sure = esp_timer_get_time() - t0;
            if (sure > en_uzun_yazma_us) en_uzun_yazma_us = sure;
            gonderilen_satir++;
        }
    }
}

/* ================================================================ MPU-6050 */
static esp_err_t mpu_yaz(uint8_t kayit, uint8_t deger)
{
    uint8_t b[2] = { kayit, deger };
    return i2c_master_transmit(mpu, b, 2, 50);
}

static esp_err_t mpu_oku(uint8_t kayit, uint8_t *veri, size_t n)
{
    return i2c_master_transmit_receive(mpu, &kayit, 1, veri, n, 50);
}

static void mpu_baslat(void)
{
    i2c_master_bus_config_t hat = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = SDA_PIN,
        .scl_io_num = SCL_PIN,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t hat_tutamaci;
    ESP_ERROR_CHECK(i2c_new_master_bus(&hat, &hat_tutamaci));

    i2c_device_config_t cihaz = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = MPU_ADRES,
        .scl_speed_hz = 400000,
    };
    ESP_ERROR_CHECK(i2c_master_bus_add_device(hat_tutamaci, &cihaz, &mpu));

    uint8_t kim = 0;
    if (mpu_oku(MPU_WHO_AM_I, &kim, 1) != ESP_OK) {
        ESP_LOGE(TAG, "MPU-6050 yanit vermedi: kablolari (3V3, G, 8=SDA, 9=SCL) kontrol et");
        return;
    }
    ESP_LOGI(TAG, "MPU bulundu, WHO_AM_I = 0x%02X", kim);
    mpu_yaz(MPU_PWR_MGMT_1, 0x01);   /* uykudan çık, saat: X ekseni jiroskobu  */
    vTaskDelay(pdMS_TO_TICKS(100));
    mpu_yaz(MPU_SMPLRT_DIV, 0x00);   /* iç örnekleme 1 kHz                       */
    mpu_yaz(MPU_CONFIG, 0x03);       /* sayısal alçak geçiren süzgeç ~44 Hz      */
    mpu_yaz(MPU_GYRO_CFG, 0x00);     /* ±250 °/s                                  */
    mpu_yaz(MPU_ACCEL_CFG, 0x00);    /* ±2 g                                      */
}

/* ================================================================ ölçüm */
/* esp_timer her periyotta bunu çağırır; işi sensör görevine bırakır */
static void zamanlayici_cagrisi(void *arg)
{
    xTaskNotifyGive(sensor_gorev_tutamaci);
}

static void olcum_hizini_kur(int hz)
{
    esp_timer_stop(olcum_zamanlayici);            /* çalışmıyorsa hata döner, önemsiz */
    olcum_hizi_hz = hz;
    ESP_ERROR_CHECK(esp_timer_start_periodic(olcum_zamanlayici, 1000000ULL / hz));
}

static int16_t ikili(const uint8_t *b) { return (int16_t)((b[0] << 8) | b[1]); }

static void sensor_gorevi(void *arg)
{
    uint8_t h[14];
    char govde[96];
    int64_t son_hata_us = 0;

    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);     /* zamanlayıcıyı bekle */
        uint32_t t_ms = (uint32_t)(esp_timer_get_time() / 1000);

        if (mpu_oku(MPU_VERI, h, sizeof h) != ESP_OK) {
            int64_t simdi = esp_timer_get_time();
            if (simdi - son_hata_us > 1000000) {     /* en fazla saniyede bir bildir */
                gonder("ERR,I2C");
                son_hata_us = simdi;
            }
            continue;
        }
        /* h[6..7] sıcaklık; kullanılmıyor */
        snprintf(govde, sizeof govde, "IMU,%lu,%.3f,%.3f,%.3f,%.2f,%.2f,%.2f",
                 (unsigned long)t_ms,
                 ikili(&h[0]) / IVME_OLCEK, ikili(&h[2]) / IVME_OLCEK, ikili(&h[4]) / IVME_OLCEK,
                 ikili(&h[8]) / DONU_OLCEK, ikili(&h[10]) / DONU_OLCEK, ikili(&h[12]) / DONU_OLCEK);
        gonder(govde);
    }
}

/* ================================================================ BOOT tuşu */
static void IRAM_ATTR dugme_kesmesi(void *arg)
{
    ham_kenar_sayisi++;
    BaseType_t uyandir = pdFALSE;
    xSemaphoreGiveFromISR(dugme_isareti, &uyandir);
    if (uyandir) portYIELD_FROM_ISR();
}

static void dugme_gorevi(void *arg)
{
    uint32_t basis = 0;
    char govde[24];

    for (;;) {
        xSemaphoreTake(dugme_isareti, portMAX_DELAY);
        uint32_t kenar_baslangic = ham_kenar_sayisi - 1;

        /* sıçrama bitsin, tuş hâlâ basılıysa gerçek basıştır */
        vTaskDelay(pdMS_TO_TICKS(SICRAMA_MS));
        if (gpio_get_level(DUGME_PIN) != 0) {
            xSemaphoreTake(dugme_isareti, 0);        /* kısa parazit: yok say */
            continue;
        }
        basis++;
        snprintf(govde, sizeof govde, "BTN,%lu", (unsigned long)basis);
        gonder(govde);

        /* tuş bırakılana kadar bekle, bırakırken oluşan sıçramaları da yut */
        while (gpio_get_level(DUGME_PIN) == 0) vTaskDelay(pdMS_TO_TICKS(10));
        vTaskDelay(pdMS_TO_TICKS(SICRAMA_MS));
        xSemaphoreTake(dugme_isareti, 0);

        ESP_LOGI(TAG, "Basis %lu: bu basista %lu ham kenar sayildi, 1 adet $BTN gonderildi",
                 (unsigned long)basis, (unsigned long)(ham_kenar_sayisi - kenar_baslangic));
    }
}

static void dugme_baslat(void)
{
    gpio_config_t g = {
        .pin_bit_mask = 1ULL << DUGME_PIN,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_NEGEDGE,              /* 1 -> 0: basma anı */
    };
    ESP_ERROR_CHECK(gpio_config(&g));
    ESP_ERROR_CHECK(gpio_install_isr_service(0));
    ESP_ERROR_CHECK(gpio_isr_handler_add(DUGME_PIN, dugme_kesmesi, NULL));
}

/* ================================================================ komutlar */
static bool tamsayi_mi(const char *s, int *deger)
{
    if (*s == '\0') return false;
    for (const char *p = s; *p; p++)
        if (*p < '0' || *p > '9') return false;
    if (strlen(s) > 4) return false;
    *deger = atoi(s);
    return true;
}

/* satir: '$' ile başlar, sonunda '*HH' vardır, \r\n atılmıştır */
static void satir_isle(char *satir)
{
    char *yildiz = strrchr(satir, '*');
    if (satir[0] != '$' || yildiz == NULL || strlen(yildiz) != 3) {
        gonder("ERR,BICIM");
        return;
    }
    char *govde = satir + 1;
    size_t n = (size_t)(yildiz - govde);
    char *son;
    long beklenen = strtol(yildiz + 1, &son, 16);
    if (*son != '\0') { gonder("ERR,BICIM"); return; }
    if (xor_toplami(govde, n) != (uint8_t)beklenen) { gonder("ERR,CHECKSUM"); return; }
    *yildiz = '\0';

    char *virgul = strchr(govde, ',');
    if (virgul == NULL) { gonder("ERR,BICIM"); return; }
    *virgul = '\0';
    const char *komut = govde, *arguman = virgul + 1;
    int d;
    char yanit[32];

    if (strcmp(komut, "LED") == 0) {
        if (!tamsayi_mi(arguman, &d) || d > 1) { gonder("ERR,BICIM"); return; }
        gpio_set_level(LED_PIN, d);
        snprintf(yanit, sizeof yanit, "ACK,LED,%d", d);
        gonder(yanit);
    } else if (strcmp(komut, "HIZ") == 0) {
        if (!tamsayi_mi(arguman, &d) || d < 1 || d > 100) { gonder("ERR,BICIM"); return; }
        olcum_hizini_kur(d);
        snprintf(yanit, sizeof yanit, "ACK,HIZ,%d", d);
        gonder(yanit);
    } else if (strcmp(komut, "IMU") == 0 || strcmp(komut, "ACK") == 0 ||
               strcmp(komut, "ERR") == 0 || strcmp(komut, "BTN") == 0) {
        /* ESP32'nin kendi gönderdiği satır geri gelmiş (yankı: hat birbirine
         * değiyor ya da Pi'de seri konsol açık). Yanıt verilmez; verilirse
         * yanıt da geri gelir ve hat dolana kadar büyüyen bir döngü oluşur. */
        yanki_satir++;
    } else {
        gonder("ERR,KOMUT");
    }
}

static void komut_gorevi(void *arg)
{
    uint8_t parca[64];
    char satir[ALMA_SINIRI + 1];
    size_t uzunluk = 0;
    bool satirda = false;            /* bir '$' görüldü, satır toplanıyor */

    for (;;) {
        /* ilk baytı bekle, sonra tamponda ne varsa beklemeden al:
         * böylece komut gelir gelmez işlenir (ACK gecikmesi kısa kalır) */
        int okunan = uart_read_bytes(PI_UART, parca, 1, portMAX_DELAY);
        if (okunan == 1) {
            size_t bekleyen = 0;
            uart_get_buffered_data_len(PI_UART, &bekleyen);
            if (bekleyen > sizeof parca - 1) bekleyen = sizeof parca - 1;
            if (bekleyen > 0) {
                int ek = uart_read_bytes(PI_UART, parca + 1, bekleyen, 0);
                if (ek > 0) okunan += ek;
            }
        }
        if (okunan > 0) alinan_bayt += okunan;
        for (int i = 0; i < okunan; i++) {
            char c = (char)parca[i];
            if (c == '$') {          /* her '$' yeni satır: yarım kalan önceki veri atılır */
                if (satirda && uzunluk > 1)
                    ESP_LOGW(TAG, "Yarim satir atildi (%u bayt)", (unsigned)uzunluk);
                uzunluk = 0;
                satirda = true;
            }
            if (!satirda || c == '\r') continue;
            if (c == '\n') {
                satir[uzunluk] = '\0';
                satir_isle(satir);
                satirda = false;
                uzunluk = 0;
                continue;
            }
            if (uzunluk >= ALMA_SINIRI) {     /* çok uzun satır */
                gonder("ERR,BICIM");
                satirda = false;
                uzunluk = 0;
                continue;
            }
            satir[uzunluk++] = c;
        }
    }
}

/* ================================================================ başlangıç */
void app_main(void)
{
    gonderim_kuyrugu = xQueueCreate(16, sizeof(satir_t));
    dugme_isareti = xSemaphoreCreateBinary();

    uart_config_t u = {
        .baud_rate = PI_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(PI_UART, 1024, 2048, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(PI_UART, &u));
    ESP_ERROR_CHECK(uart_set_pin(PI_UART, PI_TX_PIN, PI_RX_PIN, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));

    gpio_reset_pin(LED_PIN);
    gpio_set_direction(LED_PIN, GPIO_MODE_OUTPUT);
    gpio_set_level(LED_PIN, 0);

    mpu_baslat();
    dugme_baslat();

    xTaskCreate(gonderici_gorevi, "gonderici", 3072, NULL, 7, NULL);
    xTaskCreate(komut_gorevi, "komut", 4096, NULL, 6, NULL);
    xTaskCreate(sensor_gorevi, "sensor", 4096, NULL, 5, &sensor_gorev_tutamaci);
    xTaskCreate(dugme_gorevi, "dugme", 3072, NULL, 4, NULL);

    esp_timer_create_args_t z = { .callback = zamanlayici_cagrisi, .name = "olcum" };
    ESP_ERROR_CHECK(esp_timer_create(&z, &olcum_zamanlayici));
    olcum_hizini_kur(olcum_hizi_hz);

    ESP_LOGI(TAG, "Hazir: %d Hz olcum, UART1 TX=%d RX=%d, LED=GPIO%d, dugme=BOOT(GPIO%d)",
             olcum_hizi_hz, PI_TX_PIN, PI_RX_PIN, LED_PIN, DUGME_PIN);

    /* her 10 saniyede bir durum yazdır (USB konsoluna, Pi'ye değil) */
    uint32_t onceki_gonderilen = 0, onceki_kayip = 0, onceki_kenar = 0, onceki_bayt = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(10000));
        ESP_LOGI(TAG, "10 s: gonderilen %lu satir, atilan %lu, Pi'den gelen %lu bayt, tus kenari %lu, en uzun yazma %lld us",
                 (unsigned long)(gonderilen_satir - onceki_gonderilen), (unsigned long)(kayip_satir - onceki_kayip),
                 (unsigned long)(alinan_bayt - onceki_bayt), (unsigned long)(ham_kenar_sayisi - onceki_kenar),
                 (long long)en_uzun_yazma_us);
        if (yanki_satir) ESP_LOGW(TAG, "Uyari: kendi satirimiz geri geldi (toplam %lu). TX/RX kablolarini kontrol et.",
                                  (unsigned long)yanki_satir);
        onceki_gonderilen = gonderilen_satir; onceki_kayip = kayip_satir;
        onceki_bayt = alinan_bayt; onceki_kenar = ham_kenar_sayisi; en_uzun_yazma_us = 0;
    }
}
