# Dashboard Help Panel + English UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-dashboard collapsible Help section that lists physical pin assignments (live-fetched from device) and explains every panel, and refactor remaining zh-TW UI labels to English.

**Architecture:** New `GET /api/device_info` endpoint in `net_dashboard.c` returns a one-shot JSON blob with pin GPIOs, default RPM settings, and frequency range. The dashboard fetches this once on page load and substitutes values into `[data-pin]` and `[data-info]` placeholder spans inside a new `<details>` Help block at the top of the page. zh-TW labels in `index.html`, `app.js`, and `app.css` are translated to English in the same change.

**Tech Stack:** ESP-IDF v6.0 (`esp_http_server`, cJSON via `espressif__cjson`), vanilla JS (no framework), CSS with light/dark scheme variables, Kconfig-sourced GPIO numbers.

**Spec:** [`docs/superpowers/specs/2026-04-25-dashboard-help-design.md`](../specs/2026-04-25-dashboard-help-design.md)

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `components/pwm_gen/include/pwm_gen.h` | modify | Promote `PWM_FREQ_MIN_HZ` / `PWM_FREQ_MAX_HZ` from `pwm_gen.c` (file-local) to public macros so `net_dashboard` can read them without duplicating literals. |
| `components/pwm_gen/pwm_gen.c` | modify | Stop redefining the macros now that they live in the header. |
| `components/net_dashboard/net_dashboard.c` | modify | Add `device_info_get` handler, register `GET /api/device_info`. |
| `components/net_dashboard/web/index.html` | modify | Insert collapsible `<details class="help-panel">` block with placeholder spans, translate remaining zh-TW labels. |
| `components/net_dashboard/web/app.js` | modify | Add `loadDeviceInfo()` IIFE call, translate `'套用'` button text and zh-TW comment. |
| `components/net_dashboard/web/app.css` | modify | Add `.help-panel` styles, translate zh-TW comment. |

No new files. No new component dependencies. cJSON and `pwm_gen` are already in `net_dashboard`'s `REQUIRES`.

The dashboard project has **no JS test harness** and no automated test framework targeting embedded JS/HTML — verification is build + flash + manual smoke test in a browser, as established by both prior plans (`2026-04-22-pwm-1hz-floor.md`, `2026-04-22-softap-captive-portal.md`). This plan follows that convention rather than introducing a JS test runner for one feature. The C handler is small and side-effect-free (reads compile-time constants, allocates and frees a cJSON tree); its correctness is validated by the smoke test against the JSON contract.

---

## Task 1: Promote PWM frequency range to public header

**Files:**
- Modify: `components/pwm_gen/include/pwm_gen.h`
- Modify: `components/pwm_gen/pwm_gen.c:46-47`

The constants `PWM_FREQ_MIN_HZ = 10` and `PWM_FREQ_MAX_HZ = 1_000_000` are file-local in `pwm_gen.c`. The new device_info handler needs to read them. Promote to public macros so we don't duplicate literals.

- [ ] **Step 1: Edit `pwm_gen.h` to add the public macros**

Open `components/pwm_gen/include/pwm_gen.h`. After the `extern "C" {` block opens (after line 9) and before the `pwm_gen_config_t` typedef (line 11), add:

```c
// Frequency range supported by pwm_gen_set(). Below MIN the 16-bit MCPWM
// counter can't span a full period at the LO band's resolution; above MAX
// the HI band's resolution would yield <2 ticks/period.
#define PWM_GEN_FREQ_MIN_HZ 10u
#define PWM_GEN_FREQ_MAX_HZ 1000000u
```

- [ ] **Step 2: Edit `pwm_gen.c` to use the public macros**

Open `components/pwm_gen/pwm_gen.c`. Replace lines 46–47:

```c
#define PWM_FREQ_MIN_HZ 10u
#define PWM_FREQ_MAX_HZ 1000000u
```

with:

```c
// Range constants live in the public header so other components
// (net_dashboard's /api/device_info) can read them without duplicating literals.
#define PWM_FREQ_MIN_HZ PWM_GEN_FREQ_MIN_HZ
#define PWM_FREQ_MAX_HZ PWM_GEN_FREQ_MAX_HZ
```

The `_FREQ_*_HZ` private aliases keep line 256 (`if (freq_hz < PWM_FREQ_MIN_HZ ...`) untouched.

- [ ] **Step 3: Build to verify**

In the ESP-IDF v6.0 PowerShell shell (use the desktop shortcut "ESP-IDF 6.0 PWM Project" or the `esp6 pwm` alias):

```
idf.py build
```

Expected: clean build, no warnings about redefinition of `PWM_FREQ_MIN_HZ` or `PWM_FREQ_MAX_HZ`.

- [ ] **Step 4: Commit**

```bash
git add components/pwm_gen/include/pwm_gen.h components/pwm_gen/pwm_gen.c
git commit -m "feat(pwm_gen): expose PWM_GEN_FREQ_MIN_HZ/MAX_HZ in public header"
```

---

## Task 2: Add `/api/device_info` HTTP handler

**Files:**
- Modify: `components/net_dashboard/net_dashboard.c`

Add a `GET /api/device_info` handler that returns the static device config as JSON. Read GPIO numbers and RPM defaults from Kconfig (`sdkconfig.h` macros), and frequency range from `pwm_gen.h`.

- [ ] **Step 1: Add includes for cJSON and pwm_gen**

Open `components/net_dashboard/net_dashboard.c`. After the existing includes (lines 1–10), the file currently has no cJSON or pwm_gen include. Add after line 10 (`#include "prov_internal.h"`):

```c
#include "cJSON.h"
#include "pwm_gen.h"
#include "sdkconfig.h"
```

`sdkconfig.h` defines `CONFIG_APP_PWM_OUTPUT_GPIO`, `CONFIG_APP_PWM_TRIGGER_GPIO`, `CONFIG_APP_RPM_INPUT_GPIO`, `CONFIG_APP_STATUS_LED_GPIO`, `CONFIG_APP_DEFAULT_POLE_COUNT`, `CONFIG_APP_DEFAULT_MAVG_COUNT`, `CONFIG_APP_DEFAULT_RPM_TIMEOUT_US` from `main/Kconfig.projbuild`.

- [ ] **Step 2: Add the device_info handler**

Insert this function in `net_dashboard.c` between `css_get` (line 47) and `ota_post` (line 49):

```c
// One-shot static device config for the dashboard's Help panel. Returned as
// JSON. Fields are compile-time constants (Kconfig + pwm_gen header), so the
// handler is allocation-bounded and never blocks.
static esp_err_t device_info_get(httpd_req_t *req)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "oom");
        return ESP_OK;
    }

    cJSON *pins = cJSON_AddObjectToObject(root, "pins");
    cJSON_AddNumberToObject(pins, "pwm",        CONFIG_APP_PWM_OUTPUT_GPIO);
    cJSON_AddNumberToObject(pins, "trigger",    CONFIG_APP_PWM_TRIGGER_GPIO);
    cJSON_AddNumberToObject(pins, "rpm",        CONFIG_APP_RPM_INPUT_GPIO);
    cJSON_AddNumberToObject(pins, "status_led", CONFIG_APP_STATUS_LED_GPIO);

    cJSON *defaults = cJSON_AddObjectToObject(root, "defaults");
    cJSON_AddNumberToObject(defaults, "pole_count",     CONFIG_APP_DEFAULT_POLE_COUNT);
    cJSON_AddNumberToObject(defaults, "mavg_count",     CONFIG_APP_DEFAULT_MAVG_COUNT);
    cJSON_AddNumberToObject(defaults, "rpm_timeout_us", CONFIG_APP_DEFAULT_RPM_TIMEOUT_US);

    cJSON_AddNumberToObject(root, "freq_hz_min", PWM_GEN_FREQ_MIN_HZ);
    cJSON_AddNumberToObject(root, "freq_hz_max", PWM_GEN_FREQ_MAX_HZ);

    char *body = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!body) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "render");
        return ESP_OK;
    }

    httpd_resp_set_type(req, "application/json");
    esp_err_t e = httpd_resp_sendstr(req, body);
    cJSON_free(body);
    return e;
}
```

- [ ] **Step 3: Register the URI handler and bump the cap**

Edit `start_http` in `net_dashboard.c`. Currently registers 4 handlers (root, js, css, ota) plus ws. Change:

```c
    cfg.max_uri_handlers = 8;
```

to:

```c
    cfg.max_uri_handlers = 9;  // root, js, css, ota, device_info, ws, +headroom
```

After the `httpd_uri_t ota = ...` line (line 84) add:

```c
    httpd_uri_t info = { .uri = "/api/device_info", .method = HTTP_GET, .handler = device_info_get };
```

After `httpd_register_uri_handler(server, &ota);` (line 88) add:

```c
    httpd_register_uri_handler(server, &info);
```

- [ ] **Step 4: Build to verify**

```
idf.py build
```

Expected: clean build. Compile errors here usually mean a missing `REQUIRES` — but `espressif__cjson` and `pwm_gen` are already in the component's REQUIRES (verified in `components/net_dashboard/CMakeLists.txt`).

- [ ] **Step 5: Flash + smoke test the endpoint**

```
idf.py -p COM24 flash monitor
```

Once the device boots and connects to Wi-Fi (look for `dashboard http server up:` log), open a second terminal:

```
curl -s http://fan-testkit.local/api/device_info
```

Expected output (with default Kconfig — JSON layout may vary, but field values must match):

```json
{"pins":{"pwm":4,"trigger":5,"rpm":6,"status_led":48},"defaults":{"pole_count":2,"mavg_count":16,"rpm_timeout_us":1000000},"freq_hz_min":10,"freq_hz_max":1000000}
```

If `fan-testkit.local` doesn't resolve (Windows mDNS quirks), use the IP from the boot log:

```
curl -s http://<device-ip>/api/device_info
```

- [ ] **Step 6: Commit**

```bash
git add components/net_dashboard/net_dashboard.c
git commit -m "feat(net_dashboard): add GET /api/device_info for live pin/range info"
```

---

## Task 3: Add Help block HTML + translate zh-TW labels in `index.html`

**Files:**
- Modify: `components/net_dashboard/web/index.html`

Insert the Help `<details>` block under `<h1>` and translate every remaining zh-TW label in the file.

- [ ] **Step 1: Add the Help block**

Open `components/net_dashboard/web/index.html`. After line 10 (`<h1>Fan-TestKit Dashboard</h1>`) and before line 12 (`<!-- ============== RPM panel ============== -->`), insert:

```html

  <!-- ============== Help panel ============== -->
  <details class="panel help-panel" id="help">
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
    <details class="dev-notes">
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

The block reuses the existing `.panel` class for visual consistency and adds `.help-panel` for help-specific styling.

- [ ] **Step 2: Translate the 9 remaining zh-TW labels**

Make these exact `<old>` → `<new>` replacements in `index.html`:

| Line(s) | Before | After |
|---|---|---|
| 19 | `<summary>RPM 設定</summary>` | `<summary>Settings</summary>` |
| 39 | `<summary>RPM 圖表</summary>` | `<summary>Chart</summary>` |
| 71 | `<span class="label tight" style="margin-left:0.6em">步進</span>` | `<span class="label tight" style="margin-left:0.6em">Step</span>` |
| 81 | `<summary>微調</summary>` (inside `#duty-panel`) | `<summary>Fine</summary>` |
| 93 | `<summary>Duty 預設值</summary>` | `<summary>Presets</summary>` |
| 101 | `<span class="label">頻率</span>` | `<span class="label">Frequency</span>` |
| 104 | `<span class="label tight" style="margin-left:0.6em">步進</span>` | `<span class="label tight" style="margin-left:0.6em">Step</span>` |
| 117 | `<summary>微調</summary>` (inside `#freq-panel`) | `<summary>Fine</summary>` |
| 129 | `<summary>頻率預設值</summary>` | `<summary>Presets</summary>` |

Note: the line numbers reference the file **before** the Help block is inserted in Step 1. After Step 1 they shift down by ~50; just match on the string content.

`步進` and `微調` each appear twice. `Step` and `Fine` are correct in both contexts. `Presets` is correct in both because each lives inside its own `id="duty-panel"` / `id="freq-panel"` section.

- [ ] **Step 3: Verify no zh-TW remains in the HTML**

Run:

```
grep -nP '[\x{4e00}-\x{9fff}]' components/net_dashboard/web/index.html
```

Expected: no output. (The factory-reset paragraph and SoftAP captive-portal HTML files are separate; this grep targets only `index.html`.)

If any line shows up, translate the remaining string and re-run.

- [ ] **Step 4: Build to verify embedded HTML compiles**

```
idf.py build
```

Expected: clean build. The HTML is embedded via `EMBED_TXTFILES`; build only fails here if the file is missing, not for HTML syntax errors.

- [ ] **Step 5: Commit**

```bash
git add components/net_dashboard/web/index.html
git commit -m "feat(dashboard): add Help block and translate UI labels to English"
```

---

## Task 4: Wire the Help block to `/api/device_info` in `app.js`

**Files:**
- Modify: `components/net_dashboard/web/app.js`

Add `loadDeviceInfo()` and call it once at the bottom of the IIFE. Also translate the `'套用'` preset button text and the zh-TW comment.

- [ ] **Step 1: Add `loadDeviceInfo()` near the top of the IIFE**

Open `components/net_dashboard/web/app.js`. After the `clamp` helper (line 5) and before `const lastSent = ...` (line 7), insert:

```js
  // ---------- Device info (Help block, fetched once) ----------
  async function loadDeviceInfo() {
    try {
      const r = await fetch('/api/device_info');
      if (!r.ok) throw new Error(r.status);
      const info = await r.json();
      document.querySelectorAll('[data-pin]').forEach(el => {
        const v = info.pins ? info.pins[el.dataset.pin] : undefined;
        el.textContent = (v ?? '?').toString();
      });
      const map = { freq_min: info.freq_hz_min, freq_max: info.freq_hz_max };
      document.querySelectorAll('[data-info]').forEach(el => {
        const v = map[el.dataset.info];
        el.textContent = (v ?? '?').toString();
      });
    } catch (e) {
      // Help block stays usable with '?' placeholders. Other features unaffected.
    }
  }
  loadDeviceInfo();
```

The function is called immediately. Because it's `async`, this returns a Promise that's never awaited — the rest of the IIFE keeps running synchronously, and the fetch resolves whenever it resolves. That's the intended behaviour: help fetch must not block any other dashboard subsystem.

- [ ] **Step 2: Translate the preset button text**

Find line 143:

```js
      btn.textContent = '套用';
```

Replace with:

```js
      btn.textContent = 'Apply';
```

This is rendered text on every preset's "apply" button (6 in duty panel, 6 in freq panel).

- [ ] **Step 3: Translate the zh-TW comment**

Find line 339:

```js
  // Close RPM 設定 popover when clicking outside it
```

Replace with:

```js
  // Close RPM Settings popover when clicking outside it
```

- [ ] **Step 4: Verify no zh-TW remains in `app.js`**

```
grep -nP '[\x{4e00}-\x{9fff}]' components/net_dashboard/web/app.js
```

Expected: no output.

- [ ] **Step 5: Build to verify**

```
idf.py build
```

Expected: clean build.

- [ ] **Step 6: Flash + smoke test the live values**

```
idf.py -p COM24 flash monitor
```

Once the device is up:

1. Open `http://fan-testkit.local/` (or device IP) in a browser.
2. Click the **Help** summary at the top of the page.
3. Confirm pin assignments show: PWM output: GPIO**4**, Change-trigger: GPIO**5**, RPM capture: GPIO**6**, Status LED: GPIO**48**.
4. Confirm the Duty/Frequency paragraph shows: "Frequency range **10** Hz to **1000000** Hz."
5. In DevTools → Network, confirm `/api/device_info` returns 200 with the JSON from Task 2 step 5.

- [ ] **Step 7: Smoke test the failure path**

In DevTools → Network panel, set throttling to "Offline". Reload the page. Click **Help**. Expected:

- All `[data-pin]` and `[data-info]` spans show `?`.
- No console errors about uncaught Promise rejections.
- Other panels are unaffected (RPM live readout still shows `—` because WS is also down, but the panels render and controls don't throw).

Reset throttling to "No throttling" before continuing.

- [ ] **Step 8: Verify preset button label**

Open any preset row (Duty or Frequency presets). Confirm the buttons read **Apply**, not 套用.

- [ ] **Step 9: Commit**

```bash
git add components/net_dashboard/web/app.js
git commit -m "feat(dashboard): fetch /api/device_info into Help block; translate preset 'Apply'"
```

---

## Task 5: Add `.help-panel` CSS + translate the zh-TW comment

**Files:**
- Modify: `components/net_dashboard/web/app.css`

The Help block already has `.panel` so it inherits the panel chrome. Add minimal styles to keep `<h3>` headings, `<ul>` indentation, and the nested `<details>` ("Developer notes") visually consistent with the rest of the page.

- [ ] **Step 1: Translate the zh-TW comment**

Open `components/net_dashboard/web/app.css`. Find line 258:

```css
/* RPM 設定 popover-style details */
```

Replace with:

```css
/* RPM Settings popover-style details */
```

- [ ] **Step 2: Append `.help-panel` styles**

Append at the very end of `app.css` (after line 471, the `.status` block):

```css

/* ============== Help panel ============== */

/* .help-panel inherits .panel chrome (border, radius, padding). The rules
   below only add help-specific sizing for summary, headings, lists, code,
   and the nested Developer notes. */

.help-panel > summary {
  /* Match h2 weight inside other panels — Help is a sibling section. */
  font-size: 0.78em;
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.help-panel h3 {
  font-size: 0.92em;
  font-weight: 600;
  margin: 1em 0 0.3em;
  color: inherit;
}

.help-panel h3:first-of-type { margin-top: 0.7em; }

.help-panel p,
.help-panel ul {
  margin: 0.3em 0;
  font-size: 0.92em;
}

.help-panel ul {
  padding-left: 1.4em;
}

.help-panel li + li { margin-top: 0.15em; }

.help-panel code {
  font-size: 0.92em;
  background: var(--bg-soft);
  padding: 0.05em 0.3em;
  border-radius: 3px;
}

.help-panel .dev-notes {
  margin-top: 0.5em;
  font-size: 0.88em;
}

.help-panel .dev-notes > summary {
  font-size: inherit;
  font-weight: 500;
  color: var(--muted);
  text-transform: none;
  letter-spacing: normal;
}
```

- [ ] **Step 3: Verify no zh-TW remains in `app.css`**

```
grep -nP '[\x{4e00}-\x{9fff}]' components/net_dashboard/web/app.css
```

Expected: no output.

- [ ] **Step 4: Build to verify**

```
idf.py build
```

Expected: clean build.

- [ ] **Step 5: Flash + visual smoke test**

```
idf.py -p COM24 flash monitor
```

Open dashboard, click **Help**. Expected:

- `<summary>Help</summary>` matches the visual weight/colour of the `<h2>` headings in the OTA and Factory Reset panels.
- `<h3>` section headings ("Pin assignments", "Duty / Frequency", etc.) are clearly subordinate to the Help summary.
- `<ul>` bullets are indented from the panel edge (not flush left).
- "Developer notes" is a smaller, indented sub-section that opens to reveal the HID/CDC magic-byte note.
- Both light and dark mode look reasonable (toggle OS dark mode to verify).

- [ ] **Step 6: Final language sweep across the dashboard**

Click through the dashboard with the help block open. Confirm every visible label is English:

- Help panel content: English ✓
- RPM panel header: `RPM` (already English), Settings popover summary: `Settings`, chart summary: `Chart`, Live toggle: `Live`, RPM popover field labels: `Pole pairs`, `Avg window`, `Timeout (µs)`, button: `Apply RPM`.
- Duty panel: `Duty`, `%`, `Step`, `%`, slider tick marks `0%/50%/100%`, `Fine`, fine-tune `+0.1` `+1` `+10` `−0.1` `−1` `−10`, `Presets`, preset buttons `Apply`.
- Frequency panel: `Frequency`, `Hz`, `Step`, `Hz`, slider tick marks `10/100/1k/10k/100k/1M`, "duty resolution at this freq:", `Fine`, fine-tune buttons, `Presets`, preset buttons `Apply`.
- Firmware Update: `Firmware Update`, `Upload & reboot`.
- Factory Reset: `Factory Reset`, paragraph (already English), `Reset Wi-Fi & restart`.

If any zh-TW character is still visible, translate it inline and retest.

- [ ] **Step 7: Commit**

```bash
git add components/net_dashboard/web/app.css
git commit -m "feat(dashboard): style Help panel; translate remaining zh-TW comment"
```

---

## Task 6: Final integration smoke test

**Files:** none — verification only.

Confirm the four discrete pieces work together end-to-end on a clean reflash.

- [ ] **Step 1: Clean build to ensure no stale state**

```
idf.py fullclean
idf.py build
```

The CLAUDE.md sdkconfig trap doesn't apply here (we didn't touch `sdkconfig.defaults`), so `del sdkconfig` is not needed. Expected: clean build, no warnings.

- [ ] **Step 2: Flash and run**

```
idf.py -p COM24 flash monitor
```

- [ ] **Step 3: Functional checks**

In a browser at `http://fan-testkit.local/` (or the IP from the boot log):

1. **Default load** — page renders all panels, no console errors.
2. **Help expanded** — click Help summary, all 4 pin GPIOs show `4 / 5 / 6 / 48`, freq range shows `10` to `1000000`.
3. **Other features still work** — drag duty slider, confirm WS sends `set_pwm` and the readout updates. Same for freq slider. Apply an RPM setting from the popover. Click `Reset Wi-Fi & restart`, confirm the JS confirm dialog still fires (cancel — don't actually reset).
4. **No zh-TW visible anywhere** — including all `<details>` blocks expanded.
5. **DevTools Network → `/api/device_info`** — 200, body matches Task 2 Step 5.

- [ ] **Step 4: Reflash sanity (optional)**

If you have the time and a board with non-default pins (e.g. you can edit `sdkconfig` to set `CONFIG_APP_PWM_OUTPUT_GPIO=10`):

```
idf.py menuconfig    # Fan-TestKit App → PWM output GPIO → 10
idf.py build
idf.py -p COM24 flash monitor
```

Reload the dashboard. Confirm Help → Pin assignments → PWM output: GPIO**10**.

Reset back to default after verifying:

```
idf.py menuconfig    # set PWM output GPIO back to 4
```

This step is optional because the JSON-driven plumbing was already validated by Task 2 Step 5 + Task 4 Step 6, but it's the cheapest end-to-end proof that the help screen is genuinely live.

- [ ] **Step 5: No commit needed**

This task is verification-only.

---

## Definition of done

- `GET /api/device_info` returns 200 + JSON matching the spec's contract.
- Help block on the dashboard renders correct GPIO numbers and frequency range.
- Help block degrades gracefully to `?` placeholders when the fetch fails.
- No visible zh-TW characters anywhere on the dashboard.
- All other dashboard features (RPM live readout, PWM controls, OTA, factory reset, captive-portal SoftAP fallback) unchanged.
- Five commits landed (one per task; Task 6 is verification, no commit).
