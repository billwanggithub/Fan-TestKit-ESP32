#pragma once

#include "ip_announcer.h"

#ifdef __cplusplus
extern "C" {
#endif

// Worker-side API used by ip_announcer.c to drive ip_announcer_push.c.

esp_err_t ip_announcer_push_init(void);

// Called from ip_announcer.c. Snapshots settings + IP, enqueues push job.
// Updates the telemetry block on completion via the helper below.
esp_err_t ip_announcer_priv_enqueue_push(const char *ip);

// Updaters used by push worker — defined in ip_announcer.c.
void ip_announcer_priv_set_telemetry(const ip_announcer_telemetry_t *t);
void ip_announcer_priv_get_settings(ip_announcer_settings_t *out);

#ifdef __cplusplus
}
#endif
