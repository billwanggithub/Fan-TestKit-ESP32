idf_component_register(
    SRCS         "ip_announcer.c"
                 "ip_announcer_push.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES     log
                 nvs_flash
                 esp_event
                 esp_netif
                 esp_timer
                 esp_http_client
                 esp-tls
                 app_api
)
