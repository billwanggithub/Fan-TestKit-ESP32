# IP Announcer via ntfy.sh push notification

**Date:** 2026-04-26
**Branch (target):** `feature/ip-announcer` (to be cut from current
`feature/psu-modbus-rtu` head once design is approved)

## Summary

Add an opt-in `ip_announcer` component that, on every successful Wi-Fi
association, push-notifies the device's current IP to the user's phone
through [ntfy.sh](https://ntfy.sh) — a free, account-less HTTP-to-push
relay with an official Android app and an iOS app.

This solves the "I'm tethered to my Android phone's hotspot, the subnet
is randomised, and Chromium-on-Android does not resolve `.local`" use
case: the user installs the ntfy app, subscribes to a per-device random
topic name, and from then on every cold boot delivers a tappable
notification:

```text
Fan-TestKit online
IP: 192.168.49.123
http://192.168.49.123/
RSSI: -52 dBm
```

Tapping the notification opens the dashboard URL in the phone's default
browser. No mDNS, no LAN multicast, no static IP, no app development
required.

## Why this matters

After provisioning, the firmware currently tells the user the device's
IP through three channels — captive-portal `/success` page (one-time),
USB1 serial log (needs a PC), and mDNS hostname `fan-testkit.local`
(broken on Android Chrome). When the upstream router is the user's own
phone hotspot:

- DHCP reservation does not exist as a configurable knob on iOS Personal
  Hotspot or stock Android hotspot UIs (only some OEM ROMs expose it,
  unreliable). So the IP is genuinely dynamic per session.
- mDNS is double-blocked: Chromium on Android does not resolve `.local`
  ([crbug.com/41141555](https://bugs.chromium.org/p/chromium/issues/detail?id=41141555),
  open since 2014), and many Android ROMs in hotspot mode silently drop
  multicast.
- ESP32-as-AP would solve discovery but breaks the "phone keeps mobile
  data" requirement, since most phones can't be both an AP and an STA
  client of cellular Wi-Fi simultaneously.

A small outbound HTTPS push to a free relay sidesteps all of this. The
device has internet (it's online via the hotspot), the phone has the
ntfy app permanently installed, and the IP shows up in the notification
shade — works the same on every Android version, works on iOS, works
through corporate / café / home Wi-Fi too.

## Non-goals

- **Not a replacement for mDNS.** mDNS keeps working on iOS / desktop
  browsers / Linux / macOS. ntfy is the *additional* channel for the
  cases mDNS can't reach.
- **Not a heartbeat / health monitor.** One push per IP change. The
  dashboard remains the live-telemetry surface. We are NOT going to
  push RPM / PWM / PSU values to ntfy at runtime.
- **Not encrypted.** ntfy.sh has end-to-end encryption support but it
  requires a paid tier and adds key-management complexity. Topic-name
  randomness (8+ chars from a 62-char alphabet → 218-bit search space
  for a 32-char topic) is the privacy mechanism. Anyone who guesses
  the topic name can read pushed IPs; that's the accepted trade-off.
- **Not a control channel.** Push is one-way: device → phone. We do
  not subscribe to ntfy for inbound commands.
- **Not multi-recipient.** One topic per device. Multi-user broadcast
  is the user's job (subscribe the same topic from multiple phones).
- **No fallback to a second push provider.** One channel done well.
  If ntfy is down or self-host is unreachable, push fails silently and
  retries on the next IP change.
- **No BLE advertising path.** Earlier brainstorm explored advertising
  IP via BLE — rejected: ESP32-S3 Wi-Fi/BLE coex cost + need to write
  a custom Android app to parse the broadcast, both worse than ntfy.

## Background — ntfy.sh wire format

ntfy is dirt-simple HTTP. To push a notification to topic `mytopic`:

```http
POST /mytopic HTTP/1.1
Host: ntfy.sh
Title: Fan-TestKit online
Tags: green_circle
Priority: 3
Click: http://192.168.49.123/

IP: 192.168.49.123
http://192.168.49.123/
RSSI: -52 dBm
```

Header semantics:

- `Title` (UTF-8) — bold first line in the notification.
- `Tags` (CSV of emoji shortcodes from `github.com/binwiederhier/ntfy/server/util_emoji.go`)
  — small icons next to title. We use `green_circle` (🟢).
- `Priority` 1..5 — 1 = silent, 3 = default, 5 = loud-with-vibration.
- `Click` (URL) — tap target. Critical: this is what makes the IP
  reachable with one tap.

Body is plain text. No JSON, no Authorization (free public tier), no
TLS client cert. The server returns 200 + JSON
`{"id":"...","time":...,"event":"message",...}` on success, or HTTP
400 / 429 on bad topic / rate limit.

Free tier rate limit (as of 2026-04): 5 messages per visitor per minute,
500 per day. We push at most once per Wi-Fi reconnection — well under
the limit.

## Architecture

### Component layout

New `components/ip_announcer/`. Pattern matches existing `ui_settings`
(small NVS-backed feature exposed across all 4 transports):

```text
components/ip_announcer/
├── CMakeLists.txt         # REQUIRES esp_http_client esp_event nvs_flash app_api esp-tls espressif__cjson
├── Kconfig
├── include/
│   └── ip_announcer.h     # public API
├── ip_announcer.c         # NVS get/set, IP_EVENT_STA_GOT_IP hook, dispatch
└── ip_announcer_push.c    # HTTPS POST worker (separate file because cert
                           # bundle init + esp_http_client glue is >100 LoC)
```

### Public API

```c
// Lifecycle (called from app_main after NVS + control_task are up).
esp_err_t ip_announcer_init(void);

// Settings.
typedef struct {
    bool        enable;
    char        topic[65];     // 64-char + NUL
    char        server[97];    // hostname-only, default "ntfy.sh"
    uint8_t     priority;      // 1..5
} ip_announcer_settings_t;

esp_err_t ip_announcer_get_settings(ip_announcer_settings_t *out);
esp_err_t ip_announcer_set_settings(const ip_announcer_settings_t *in);

// Status (for WS telemetry block).
typedef enum {
    IP_ANN_STATUS_NEVER = 0,
    IP_ANN_STATUS_OK,
    IP_ANN_STATUS_FAILED,
    IP_ANN_STATUS_DISABLED,
} ip_announcer_status_t;

typedef struct {
    ip_announcer_status_t status;
    int                   last_http_code;       // 0 if never tried
    char                  last_pushed_ip[16];   // dotted-quad, "" if never
    char                  last_err[48];         // human-readable, "" on success
    int64_t               last_attempt_ms;      // esp_timer_get_time / 1000
} ip_announcer_telemetry_t;

void ip_announcer_get_telemetry(ip_announcer_telemetry_t *out);

// Trigger an immediate push of the current IP (Test button / CLI).
// Async: returns ESP_OK after enqueueing.
esp_err_t ip_announcer_test_push(void);
```

### Trigger flow

```text
                           ┌─────────────────────────────────────┐
                           │ provisioning.c on_wifi_event        │
                           │   IP_EVENT_STA_GOT_IP →             │
                           │   ip_announcer_notify_got_ip(ip)    │
                           └──────────────┬──────────────────────┘
                                          │
                            ┌─────────────▼──────────────┐
                            │ ip_announcer.c             │
                            │  if (!enable) return;      │
                            │  if (ip == last_pushed_ip  │
                            │      && status == OK)      │
                            │     return; // dedupe      │
                            │  enqueue_push_request(ip); │
                            └─────────────┬──────────────┘
                                          │
                            ┌─────────────▼──────────────┐
                            │ ip_announcer_push_task     │  priority 2,
                            │   esp_http_client POST      │  stack 6 KB
                            │   3 retries × 5 s gap       │
                            │   on success: persist       │
                            │     last_pushed_ip + status │
                            └────────────────────────────┘
```

The push task is a single FreeRTOS task drained by a queue (depth = 4).
Reusing `control_task` is rejected because the HTTPS POST holds the task
for up to ~15 s during retries; that would block setpoint commands.

### Boot ordering (in `app_main`)

```c
ESP_ERROR_CHECK(ip_announcer_init());      // before net_dashboard_start()
                                           // so the IP_EVENT handler is
                                           // registered before
                                           // provisioning's IP_EVENT
                                           // handler can fire
ESP_ERROR_CHECK(net_dashboard_start());
```

`ip_announcer_init` registers an `IP_EVENT_STA_GOT_IP` handler with the
default event loop and creates the push task. The default event loop
is already created by `provisioning.c` (`esp_event_loop_create_default`),
which `net_dashboard_start` calls into. To avoid a duplicate-create error
we either (a) move `esp_event_loop_create_default` out of provisioning
into `app_main` proper, or (b) detect `ESP_ERR_INVALID_STATE` and
ignore. (b) is simpler and matches existing patterns elsewhere
(`mdns_init`).

### NVS layout

Namespace: `ip_announcer`

| Key        | Type | Default                  | Notes                              |
|------------|------|--------------------------|------------------------------------|
| `enable`   | u8   | 0                        | 0 = disabled, 1 = enabled          |
| `topic`    | str  | (auto-gen on first boot) | 8..64 chars, `[a-zA-Z0-9_-]+`      |
| `server`   | str  | `"ntfy.sh"`              | hostname only; no scheme, no path  |
| `priority` | u8   | 3                        | clamp to 1..5 on read              |
| `last_ip`  | str  | `""`                     | last successfully-pushed IP        |

### Auto-generated topic on first boot (the "(c)" decision)

If `topic` is missing in NVS at `ip_announcer_init` time, generate one
locally using `esp_random()` and persist immediately:

```c
char tok[33];                                  // 32 chars + NUL
static const char alphabet[] =
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789";                              // 62 chars; deliberately no _ or -
for (int i = 0; i < 32; i++) {
    tok[i] = alphabet[esp_random() % 62];      // bias is acceptable for this use
}
tok[32] = '\0';
snprintf(s.topic, sizeof(s.topic), "fan-testkit-%s", tok);
ip_announcer_save(&s);
```

Result example: `fan-testkit-A7kQp9zT2wXv4LnB6mFhCdUgPyEsNrMo`.

`enable` stays 0 — the user must opt in. This matches the existing
"new feature is off by default" pattern.

The `fan-testkit-` prefix makes it human-recognisable in the ntfy app's
topic list; the 32-char random suffix puts the search space at 62^32 ≈
2^190, well past brute-forceable.

### Captive-portal `/success` integration

After provisioning succeeds and the user lands on the captive-portal
success page, surface the topic name and a one-tap link to subscribe in
the ntfy Android app.

`success.html` template gains two new tokens (alongside existing
`{{IP}}` and `{{MDNS}}`):

- `{{NTFY_TOPIC}}` — the auto-generated topic
- `{{NTFY_DEEPLINK}}` — `ntfy://ntfy.sh/<topic>?subscribe=1`
- `{{NTFY_WEBLINK}}` — `https://ntfy.sh/<topic>` (browser fallback)

`captive_portal.c success_get` extends its `repl[][]` table from 2
entries to 5, pulling the topic via `ip_announcer_get_settings`.

The HTML adds a third section after the existing IP / mDNS section:

```html
<section class="ntfy">
  <h3>📲 Get IP notifications on this phone</h3>
  <p>Install the <strong>ntfy</strong> app
     (<a href="https://play.google.com/store/apps/details?id=io.heckel.ntfy">Play Store</a>
      / <a href="https://apps.apple.com/app/ntfy/id1625396347">App Store</a>),
     then tap below to subscribe to this device's topic:</p>
  <p><a class="btn" href="{{NTFY_DEEPLINK}}">Open in ntfy app</a></p>
  <p><small>Topic: <code>{{NTFY_TOPIC}}</code><br>
     (Subscribe in the app, then enable IP push from the dashboard
      Settings → IP Announcer.)</small></p>
</section>
```

Subscribing in the app is one tap. Enabling push on the device is a
separate step — that's intentional, so a user who reaches the
success page but doesn't want push can still skip it.

### Wire-protocol surfaces (single handler, multiple frontends)

Follows CLAUDE.md's invariant: one handler in `ip_announcer.c`, four
transport frontends.

#### WebSocket (client → device)

```json
{ "type": "set_announcer",
  "enable":   true,
  "topic":    "fan-testkit-...",
  "server":   "ntfy.sh",
  "priority": 3 }

{ "type": "test_announcer" }
```

Device → client: existing 20 Hz status frame gains an `announcer` block:

```json
"announcer": {
  "enable":          true,
  "topic":           "fan-testkit-A7kQp9zT2wXv4LnB6mFhCdUgPyEsNrMo",
  "server":          "ntfy.sh",
  "priority":        3,
  "status":          "ok",
  "last_pushed_ip":  "192.168.49.123",
  "last_http_code":  200,
  "last_err":        "",
  "last_attempt_ms": 1714142345123
}
```

#### USB HID

New report id `0x07` (next free after `0x06` settings save). Single
8-byte report, op-code in byte 0:

| Op   | Meaning                              | Payload bytes 1..7              |
|------|--------------------------------------|---------------------------------|
| 0x01 | Toggle enable                        | `[1] = 0/1`                     |
| 0x02 | Trigger test push                    | (none)                          |

Only enable + test on the HID surface. **Topic / server / priority do
not flow through HID** — those are long-string config values that
belong in the dashboard or CLI. Keeping HID payload to a single 8-byte
report avoids growing the descriptor for rarely-changed strings.

HID descriptor grows from 93 → 103 bytes (one more `0x85,0x07,...`
output report, identical shape to existing 0x06). Update
`HID_REPORT_DESC_SIZE` macro and `_Static_assert(sizeof(...) == 103)`
in lockstep.

#### USB CDC SLIP

Ops `0x60..0x63`:

| Op   | Direction     | Payload                                                          |
|------|---------------|------------------------------------------------------------------|
| 0x60 | host → device | u8 enable, u8 priority, str topic\\0 str server\\0               |
| 0x61 | host → device | (test push)                                                      |
| 0x62 | device → host | (5 Hz status mirror — same as WS announcer block, packed binary) |
| 0x63 | device → host | (push result event — fires on each retry final outcome)          |

#### CLI

```text
announcer_set <topic> [server] [priority]   # priority defaults to 3
announcer_enable <0|1>
announcer_test
announcer_status
```

`announcer_status` prints:

```text
announcer  enable=1  topic=fan-testkit-...  server=ntfy.sh  priority=3
           last_status=ok  last_ip=192.168.49.123  http=200
```

### Dashboard UI

New panel `<section class="card" id="announcer">` in
`components/net_dashboard/web/index.html`, placed after the existing
"Step Sizes" panel in the Settings region.

```text
┌─ IP Announcer (ntfy.sh) ────────────────────────────────┐
│  [✓] Enable IP push notifications                       │
│                                                         │
│  Topic:    [fan-testkit-A7kQp9z...        ] [🎲 Random] │
│  Server:   [ntfy.sh                       ]             │
│  Priority: [3 — Default ▾]                              │
│                                                         │
│  Status: 🟢 Pushed 192.168.49.123 12 s ago              │
│                                                         │
│  [ Send test now ]   [ Save ]                           │
│                                                         │
│  📲 Subscribe on phone:                                 │
│       <a href="ntfy://ntfy.sh/<topic>">Open in ntfy app</a>
└─────────────────────────────────────────────────────────┘
```

(No QR code rendering for v1 — deeplink button is enough when the user
is already on the phone that needs to subscribe. QR adds ~4 KB JS lib
weight for marginal UX gain.)

Save dispatches a `set_announcer` WS frame. Test button dispatches
`test_announcer`. The Status line updates from the 20 Hz status frame
the same way other panels do.

i18n keys added to `app.js` translations (`en` / `zh-tw` / `zh-cn`):

- `announcer_h`, `announcer_enable`, `announcer_topic`,
  `announcer_server`, `announcer_priority`, `announcer_test`,
  `announcer_save`, `announcer_status_*` (never / ok / failed),
  `announcer_random`, `announcer_subscribe_h`, `announcer_help_p`.

### Help section

A new `<details>` block in the Help footer documenting:

- What ntfy is, why this exists (mDNS + Android Chrome story)
- Privacy posture (topic randomness, no encryption, no account)
- Self-host pointer for users who don't want to depend on ntfy.sh

## Error handling

| Failure                                        | Behaviour                                               |
|------------------------------------------------|---------------------------------------------------------|
| `enable=0`                                     | Skip, status = `disabled`                               |
| Topic empty / too short                        | Save rejects with `ESP_ERR_INVALID_ARG`; UI shows error |
| DNS resolution fails                           | Retry 3× with 5 s gap; final = `failed`, log warn       |
| TCP / TLS handshake fails                      | Same as above                                           |
| HTTP 2xx                                       | Status `ok`, persist `last_pushed_ip`                   |
| HTTP 4xx (bad topic, rate limit)               | No retry, status `failed`, log error with body excerpt  |
| HTTP 5xx                                       | Retry 3× with 5 s gap                                   |
| Same IP as last successful push                | Skip, no push; status remains `ok` with previous IP     |
| `last_ip` matches but last status was `failed` | Push (we treat the previous failure as still pending)   |

Push failures NEVER block boot, NEVER block other tasks. The push task
is fire-and-forget after enqueue.

## Testing strategy

### Unit-level (host build, no hardware)

- `ip_announcer` topic-generation: 1000 generations, all in
  `[a-zA-Z0-9]{32}` and all unique under fixed-seed PRNG control.
- NVS round-trip: set settings, read back, verify byte-equal.
- HTTP request building: feed `(topic, server, priority, ip, body)`
  into a string-builder helper, snapshot-test the produced
  request line + headers + body. Detects accidental header injection
  if topic contains a stray `\r\n` (must reject at validation time).

### Integration (device, requires Wi-Fi)

1. **Cold boot, push happy path**: enable + valid topic → reboot →
   ntfy app receives notification within 5 s of `IP_EVENT_STA_GOT_IP`.
2. **Dedupe on DHCP renew**: simulate by triggering a forced
   reconnect, IP unchanged → no second notification fires.
3. **DHCP IP change**: change Wi-Fi network → new IP → notification
   fires once with the new IP.
4. **Test button**: works regardless of dedupe state.
5. **Network outage during push**: pull upstream cable mid-retry →
   final status `failed`, no crash, no leaked socket.
6. **Rate limit**: spam `announcer_test` 6× in 60 s → 6th gets HTTP
   429, status `failed` with code 429.
7. **Captive-portal `/success` page**: fresh provision (NVS-erased)
   → success page renders the ntfy section with topic + deeplink.
   Tap deeplink on Android → ntfy app opens to subscribe screen.
8. **Self-host pointing**: change server to a private hostname →
   verify we connect to that hostname (DNS + Host header).

### Manual verification before merge

- Push notification arrives with tappable URL on Android Chrome via
  Pixel personal hotspot. **This is the failure mode that motivated
  the spec; verifying it is non-negotiable.**
- iOS test (Bonjour-capable, but ntfy still adds value because the
  hotspot subnet is dynamic): one-tap from notification opens Safari
  on the dashboard URL.

## Implementation order

1. `ip_announcer` skeleton: header + NVS + topic auto-gen + dummy
   push fn that just logs. Boot test: topic appears in NVS, log says
   "would push 192.168.x.y to fan-testkit-...".
2. Real HTTPS push via `esp_http_client` + `esp_crt_bundle`. Manual
   test: ntfy app receives notification.
3. CLI commands. Manual test: `announcer_test` triggers push.
4. WS plumbing: handler in `ws_handler.c`, status-frame extension in
   `telemetry_task`. Browser test: dashboard "Settings" tab shows
   panel with auto-gen topic, Save persists, Test button works.
5. HID + CDC plumbing. Host-tool test (out of scope for this repo
   but the descriptor and op-code numbers are frozen here so the host
   tool can be updated in parallel).
6. Captive-portal `/success` integration: extra repl tokens, new HTML
   section. Re-provision flow test: fresh-flashed board → captive
   portal → success page shows topic + ntfy deeplink.
7. Help section + i18n strings. Documentation pass on README +
   CLAUDE.md (add `ip_announcer` to the NVS-tunables section).

## Open questions

None. All decisions resolved in brainstorm:

- Channel: ntfy.sh (vs Telegram, BLE) — chosen.
- Topic strategy: auto-gen on first boot + captive-portal display +
  enable-stays-off — chosen ("c" option).
- Encryption: no.
- HID surface: enable + test only, no string fields.
- Boot order: register IP_EVENT handler before `net_dashboard_start`.

## Files touched

New:

- `components/ip_announcer/CMakeLists.txt`
- `components/ip_announcer/Kconfig`
- `components/ip_announcer/include/ip_announcer.h`
- `components/ip_announcer/ip_announcer.c`
- `components/ip_announcer/ip_announcer_push.c`

Modified:

- `main/app_main.c` — add `ip_announcer_init()` call before `net_dashboard_start()`
- `main/control_task.c` — no changes (push task is independent)
- `main/CMakeLists.txt` — add `ip_announcer` to REQUIRES
- `components/net_dashboard/CMakeLists.txt` — REQUIRES `ip_announcer`
- `components/net_dashboard/captive_portal.c` — extend `repl[][]` to 5 tokens
- `components/net_dashboard/web/success.html` — new ntfy section
- `components/net_dashboard/web/index.html` — new Settings panel
- `components/net_dashboard/web/app.js` — i18n + WS handler + UI bindings
- `components/net_dashboard/ws_handler.c` — `set_announcer` / `test_announcer`
  handlers; `telemetry_task` (same file, builds 20 Hz status frame) appends
  `announcer` block
- `components/usb_composite/usb_descriptors.c` — descriptor +1 report id
- `components/usb_composite/usb_composite.c` — `HID_REPORT_DESC_SIZE` 93→103
- `components/usb_composite/usb_protocol.h` — `USB_HID_REPORT_ANNOUNCER = 0x07`,
  `USB_CDC_OP_ANNOUNCER_*` 0x60..0x63
- `components/usb_composite/usb_hid.c` — handle 0x07 reports
- `components/usb_composite/usb_cdc.c` — handle 0x60/0x61 + emit 0x62/0x63
- `main/app_main.c` — already listed above (also gains the four
  `announcer_*` CLI commands alongside the existing CLI block)
- `CLAUDE.md` — add `ip_announcer` namespace to NVS-tunables section
- `README.md` — feature note + ntfy app links

Estimated LoC: ~600 (component ~250, dashboard ~150, USB transports
~80, captive-portal ~30, glue ~90).
