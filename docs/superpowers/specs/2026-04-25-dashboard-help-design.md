# Dashboard Help Panel + English UI — design

**Date:** 2026-04-25
**Status:** Drafted (awaiting user review)
**Touches:** `components/net_dashboard/web/{index.html,app.js,app.css}`,
`components/net_dashboard/` (new HTTP handler).

## Goal

Add an in-dashboard Help section so a fan-test operator can self-serve the
two questions they hit first when they open the page:

1. **Which physical pins are PWM out and RPM in?** (also: change-trigger
   out, status LED).
2. **What do the controls actually do?** (Duty / Frequency, RPM settings,
   Firmware Update, Factory Reset, Wi-Fi setup fallback).

Pin numbers must be sourced from the device at runtime — the Kconfig
defaults (4 / 5 / 6 / 48) are not contractual; a rebuild can move them.
Hard-coding numbers in the HTML produces a help screen that silently
lies, which is worse than no help.

The same change also flips the dashboard's existing zh-TW UI labels to
English so the page reads consistently.

## Non-goals

- No changes to the WebSocket schema (`status` / `ack` / `ota_progress`).
- No new automated tests — the dashboard has no JS test harness and
  adding one for this is out of scope.
- No changes to the captive-portal / SoftAP provisioning flow.
- No restructuring of `net_dashboard`'s HTTP handler organisation beyond
  adding one URI handler.

## Architecture

```
Dashboard load
  ├─ GET /index.html, /app.css, /app.js     (existing static files)
  └─ GET /api/device_info                   (NEW: one-shot JSON fetch)
        │
        └─ httpd handler in net_dashboard
              reads CONFIG_APP_PWM_OUTPUT_GPIO,
                    CONFIG_APP_PWM_TRIGGER_GPIO,
                    CONFIG_APP_RPM_INPUT_GPIO,
                    CONFIG_APP_STATUS_LED_GPIO,
                    CONFIG_APP_DEFAULT_POLE_COUNT,
                    CONFIG_APP_DEFAULT_MAVG_COUNT,
                    CONFIG_APP_DEFAULT_RPM_TIMEOUT_US
              builds JSON via cJSON
              returns 200 application/json
```

The endpoint serves "static device config" — values that are constant
for the life of a firmware build. It is fetched once on page load, not
polled. WebSocket continues to carry live telemetry and command/ack
traffic.

## Components

### 1. New HTTP endpoint: `GET /api/device_info`

Lives in `components/net_dashboard/`. Implementation goes alongside the
existing httpd handlers (the writing-plans phase will pick the exact
file — likely an existing handler file rather than a new one, since the
endpoint is small).

Response body (200 OK, `application/json`):

```json
{
  "pins": {
    "pwm": 4,
    "trigger": 5,
    "rpm": 6,
    "status_led": 48
  },
  "defaults": {
    "pole_count": 2,
    "mavg_count": 16,
    "rpm_timeout_us": 1000000
  },
  "freq_hz_min": 10,
  "freq_hz_max": 1000000
}
```

Field sources:

| Field | Source |
|---|---|
| `pins.pwm` | `CONFIG_APP_PWM_OUTPUT_GPIO` |
| `pins.trigger` | `CONFIG_APP_PWM_TRIGGER_GPIO` |
| `pins.rpm` | `CONFIG_APP_RPM_INPUT_GPIO` |
| `pins.status_led` | `CONFIG_APP_STATUS_LED_GPIO` |
| `defaults.pole_count` | `CONFIG_APP_DEFAULT_POLE_COUNT` |
| `defaults.mavg_count` | `CONFIG_APP_DEFAULT_MAVG_COUNT` |
| `defaults.rpm_timeout_us` | `CONFIG_APP_DEFAULT_RPM_TIMEOUT_US` |
| `freq_hz_min` | `pwm_gen` public constant if one exists; otherwise hardcoded `10` with a code comment that ties it to `pwm_gen.c`'s LO band floor |
| `freq_hz_max` | same: `pwm_gen` public constant if one exists; otherwise hardcoded `1000000` |

`defaults.*` is fetched but not currently rendered into help copy. It's
included in the JSON so future help additions ("default = 2") don't
need a server-side change.

No new component dependencies. cJSON is already a `REQUIRES` of
`net_dashboard`.

Error path: the handler should not be able to fail in normal operation
(it does not allocate aggressively and reads compile-time constants).
If `cJSON_PrintUnformatted` returns NULL, respond 500 with an empty
body — the JS catch path handles this gracefully.

### 2. HTML — `index.html`

Add a new collapsed `<details class="help-panel" id="help">` block
immediately under the `<h1>` heading, before the RPM panel.

Structure:

```html
<details class="help-panel" id="help">
  <summary>Help</summary>

  <h3>Pin assignments</h3>
  <ul id="help-pins">
    <li>PWM output: GPIO<span data-pin="pwm">?</span></li>
    <li>Change-trigger output: GPIO<span data-pin="trigger">?</span></li>
    <li>RPM capture input: GPIO<span data-pin="rpm">?</span></li>
    <li>Status LED (WS2812): GPIO<span data-pin="status_led">?</span></li>
  </ul>

  <h3>Duty / Frequency</h3>
  <p>Drives the PWM-output pin. Frequency range
     <span data-info="freq_min">?</span>&nbsp;Hz to
     <span data-info="freq_max">?</span>&nbsp;Hz.
     Duty resolution decreases at high frequencies — the live
     "duty resolution at this freq" readout shows the current bit count.</p>

  <h3>RPM</h3>
  <p>Reads tach edges on the RPM-input pin.
     <em>RPM = edges/sec × 60 / pole pairs.</em></p>
  <ul>
    <li><strong>Pole pairs</strong> — divider for edge frequency.</li>
    <li><strong>Avg window</strong> — sliding-average sample count to smooth jitter.</li>
    <li><strong>Timeout (µs)</strong> — if no edge arrives within this window, RPM falls to 0.</li>
    <li><strong>Live</strong> toggle pauses the readout and chart without stopping the device.</li>
  </ul>

  <h3>Firmware Update</h3>
  <p>Pick a <code>.bin</code> and click Upload. The device flashes to the
     inactive OTA slot and reboots into it.</p>

  <h3>Factory Reset</h3>
  <p>Clears stored Wi-Fi credentials and reboots. Same effect as holding
     the BOOT button for ≥ 3 seconds.</p>
  <details>
    <summary>Developer notes</summary>
    <p>The same reset is also reachable via USB HID report
       <code>0x03</code> with magic byte <code>0xA5</code>, or USB CDC op
       <code>0x20</code> with magic byte <code>0xA5</code>. All four
       entry points land on <code>net_dashboard_factory_reset()</code>.</p>
  </details>

  <h3>Wi-Fi setup fallback</h3>
  <p>If credentials are missing or wrong, the device opens an open SoftAP
     named <code>Fan-TestKit-setup</code>. Connect from a phone — the
     captive-portal page lets you enter SSID/password. After success the
     dashboard is reachable at <code>fan-testkit.local</code> or the
     assigned IP.</p>
</details>
```

Placeholder text in `[data-pin]` and `[data-info]` spans is `?` so the
help block is human-readable even when the fetch fails.

### 3. zh-TW → English UI label refactor

Same pass updates these existing labels in `index.html`:

| Existing (zh-TW) | After (English) | Element |
|---|---|---|
| `RPM 設定` | `Settings` | `<summary>` of `#rpm-settings` |
| `RPM 圖表` | `Chart` | `<summary>` of `#rpm-chart-expander` |
| `步進` | `Step` | duty panel row label |
| `Hz`-side `步進` | `Step` | freq panel row label |
| `微調` (duty) | `Fine` | `<summary>` of duty fine-adjust |
| `微調` (freq) | `Fine` | `<summary>` of freq fine-adjust |
| `頻率` | `Frequency` | freq panel row label |
| `Duty 預設值` | `Presets` | `<summary>` of duty presets |
| `頻率預設值` | `Presets` | `<summary>` of freq presets |

`Settings` and `Chart` are unambiguous without the `RPM` prefix because
they sit inside the RPM panel. Both `Presets` summaries are unambiguous
because each is inside its own `id="duty-panel"` / `id="freq-panel"`
section.

No other strings change. `RPM`, `Duty`, `Hz`, `%` etc. are already
English. Button labels (`Apply RPM`, `Upload & reboot`, `Reset Wi-Fi &
restart`) and the factory-reset warning paragraph are already English.

### 4. JS — `app.js`

Add one async function, called once on `DOMContentLoaded` (or once on
script load — whichever the existing file already does for its init):

```js
async function loadDeviceInfo() {
  try {
    const r = await fetch('/api/device_info');
    if (!r.ok) throw new Error(r.status);
    const info = await r.json();
    document.querySelectorAll('[data-pin]').forEach(el => {
      el.textContent = info.pins[el.dataset.pin] ?? '?';
    });
    const map = { freq_min: info.freq_hz_min, freq_max: info.freq_hz_max };
    document.querySelectorAll('[data-info]').forEach(el => {
      el.textContent = map[el.dataset.info] ?? '?';
    });
  } catch (e) {
    // Leave existing '?' placeholders in place. Help block still reads.
  }
}
```

Failure mode is "leave the `?` placeholders". The help text should never
break the rest of the dashboard — RPM live readout, PWM controls, OTA,
and factory reset must all work even if `/api/device_info` returns 500
or the network drops the request.

### 5. CSS — `app.css`

Minimal additions, scoped to `.help-panel`:

- Match the existing `<details>` / `.panel` visual rhythm (padding,
  border, background) so the help block feels like the rest of the page,
  not a foreign element.
- `<h3>` sizing inside the help — slightly smaller than top-level
  headings, larger than body text.
- `<ul>` left-padding so bullets aren't flush with the panel edge.
- Nested `<details>` ("Developer notes") indented and visually
  de-emphasised vs. the parent help sections.

Estimate: ~10–15 lines.

## Data flow

```
Page load
  │
  ├─ index.html parsed
  │     └─ help <details> renders with '?' placeholders
  │           (collapsed — user has to click to see it)
  │
  ├─ app.js loaded → existing init runs (WS connect, etc.)
  │
  └─ loadDeviceInfo()
        │
        ├─ fetch('/api/device_info')
        │     │
        │     ├─ 200 OK → parse JSON → fill [data-pin] and [data-info]
        │     │
        │     └─ failure → silent catch; '?' placeholders remain
        │
        └─ help block now displays correct GPIO numbers
              (or '?' if fetch failed — help is still usable)
```

The fetch is independent of every other dashboard subsystem. The user
never sees a loading spinner because the help block is collapsed by
default; by the time they click the `<summary>` to open it, the fetch
has long since completed.

## Error handling

| Failure | Behaviour |
|---|---|
| `/api/device_info` returns 500 | JS catch path; `?` placeholders stay; rest of dashboard unaffected. |
| Network drops the fetch | Same as above. |
| `info.pins.*` missing a key | The `?? '?'` fallback writes `?` for that pin only. |
| `info.freq_hz_min/max` missing | Same: those two spans show `?`. |
| User clicks Help before fetch completes | They see `?` placeholders briefly. Once the fetch returns, the spans update in place — no reload needed. |
| Handler `cJSON_PrintUnformatted` returns NULL | 500 with empty body. Falls into "fetch error" path on the JS side. |

## Testing

- **Build:** `idf.py build` from the v6.0 PowerShell shell. Verifies the
  new handler compiles, no new component dependency issues.
- **Flash + smoke test:** open the dashboard, click **Help**, confirm pins
  render `4 / 5 / 6 / 48`. Open browser DevTools → Network tab, confirm
  `/api/device_info` returns 200 and the JSON body matches Kconfig values.
- **English-label visual check:** scan the dashboard, confirm no
  remaining zh-TW characters in any visible label.
- **Negative test:** in DevTools → Network, set throttling to "Offline",
  reload page, click **Help**, confirm the help block still renders with
  `?` placeholders and no console errors block the rest of the
  dashboard's JS.
- **Kconfig override test (optional):** rebuild with
  `CONFIG_APP_PWM_OUTPUT_GPIO=10`, flash, reload dashboard, confirm the
  help block shows `GPIO10` for PWM output.

No new automated tests.

## Out of scope / follow-ups

- Surfacing `defaults.*` in the help copy — the JSON already carries
  these, but rendering them is a future iteration if it becomes useful.
- Adding more device-info fields (firmware version, build timestamp, MAC
  address) — not needed for this task; can extend the same JSON shape
  later without breaking the contract.
- Translating the captive-portal HTML (`provisioning.c`'s served pages)
  to English — separate file, separate concern, not requested.
