#include <string.h>

#include "esp_log.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"

#include "prov_internal.h"
#include "captive_portal.h"
#include "dns_hijack.h"
#include "mdns_svc.h"

static const char *TAG = "prov";

static EventGroupHandle_t s_ev;
#define EV_GOT_IP   BIT0
#define EV_STA_FAIL BIT1

static char s_last_ip[16] = {0};

static void on_wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        // Only signal failure when captive portal is waiting; for post-
        // provision steady state we want auto-reconnect behaviour.
        xEventGroupSetBits(s_ev, EV_STA_FAIL);
        esp_wifi_connect();
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *evt = (ip_event_got_ip_t *)data;
        snprintf(s_last_ip, sizeof(s_last_ip), IPSTR, IP2STR(&evt->ip_info.ip));
        ESP_LOGI(TAG, "got ip: %s", s_last_ip);
        xEventGroupSetBits(s_ev, EV_GOT_IP);
    }
}

static bool nvs_has_wifi_credentials(void)
{
    wifi_config_t cfg = {0};
    if (esp_wifi_get_config(WIFI_IF_STA, &cfg) != ESP_OK) return false;
    return cfg.sta.ssid[0] != '\0';
}

// Invoked from the captive portal httpd thread. Applies credentials,
// waits up to 20 s for IP, fills result.
static esp_err_t on_credentials(const char *ssid, const char *password,
                                captive_portal_result_t *out)
{
    ESP_LOGI(TAG, "applying creds: ssid=%s", ssid);

    // Switch into APSTA so the phone stays associated while STA dials out.
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));

    wifi_config_t sta = {0};
    strncpy((char *)sta.sta.ssid, ssid, sizeof(sta.sta.ssid) - 1);
    strncpy((char *)sta.sta.password, password, sizeof(sta.sta.password) - 1);
    sta.sta.threshold.authmode = WIFI_AUTH_OPEN;  // accept any authmode that matches the password
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta));

    xEventGroupClearBits(s_ev, EV_GOT_IP | EV_STA_FAIL);
    esp_wifi_connect();

    EventBits_t bits = xEventGroupWaitBits(s_ev, EV_GOT_IP | EV_STA_FAIL,
                                           pdTRUE, pdFALSE, pdMS_TO_TICKS(20000));
    if (bits & EV_GOT_IP) {
        strncpy(out->ip, s_last_ip, sizeof(out->ip) - 1);
        out->mdns = "esp32-pwm.local";
        return ESP_OK;
    }

    // Timeout or explicit disconnect. Roll back to AP-only so user can retry.
    snprintf(out->err_msg, sizeof(out->err_msg),
             (bits & EV_STA_FAIL) ? "auth/connect failed" : "timeout (20 s)");
    esp_wifi_disconnect();
    wifi_config_t blank = {0};
    esp_wifi_set_config(WIFI_IF_STA, &blank);
    esp_wifi_set_mode(WIFI_MODE_AP);
    return ESP_FAIL;
}

static void ap_teardown_task(void *arg)
{
    // Let the phone load /success before we kill the AP.
    vTaskDelay(pdMS_TO_TICKS(30000));
    ESP_LOGI(TAG, "tearing down AP + DNS hijack");
    dns_hijack_stop();
    captive_portal_stop();
    esp_wifi_set_mode(WIFI_MODE_STA);
    mdns_svc_start();
    vTaskDelete(NULL);
}

static esp_err_t run_softap_portal(void)
{
    esp_netif_create_default_wifi_ap();

    wifi_config_t ap = {0};
    strcpy((char *)ap.ap.ssid, "ESP32-PWM-setup");
    ap.ap.ssid_len       = strlen("ESP32-PWM-setup");
    ap.ap.channel        = 1;
    ap.ap.authmode       = WIFI_AUTH_OPEN;
    ap.ap.max_connection = 4;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_ERROR_CHECK(dns_hijack_start());
    ESP_ERROR_CHECK(captive_portal_start(on_credentials));

    ESP_LOGI(TAG, "SoftAP 'ESP32-PWM-setup' up — waiting for credentials");

    // Block until on_credentials succeeds — sets EV_GOT_IP.
    xEventGroupWaitBits(s_ev, EV_GOT_IP, pdFALSE, pdTRUE, portMAX_DELAY);

    // Hand control back to caller; schedule AP teardown in 30 s.
    xTaskCreate(ap_teardown_task, "ap_down", 2048, NULL, 2, NULL);
    return ESP_OK;
}

esp_err_t provisioning_run_and_connect(void)
{
    s_ev = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t wifi_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi_cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,   IP_EVENT_STA_GOT_IP, on_wifi_event, NULL));

    if (nvs_has_wifi_credentials()) {
        ESP_LOGI(TAG, "credentials present → STA");
        ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
        ESP_ERROR_CHECK(esp_wifi_start());
        xEventGroupWaitBits(s_ev, EV_GOT_IP, pdFALSE, pdTRUE, portMAX_DELAY);
        mdns_svc_start();
        return ESP_OK;
    }

    ESP_LOGI(TAG, "no credentials → SoftAP + captive portal");
    return run_softap_portal();
}

esp_err_t prov_clear_credentials(void)
{
    ESP_LOGW(TAG, "clearing wifi credentials");
    return esp_wifi_restore();
}
