idf_component_register(
    SRCS        "gpio_io.c"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "."
    REQUIRES    app_api
                esp_driver_gpio
                esp_timer
                nvs_flash
                log
)
