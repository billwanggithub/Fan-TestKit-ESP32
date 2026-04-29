# Build & Toolchain

## ESP-IDF v6.0 activation (Windows)

ESP-IDF v6.0 lives at `C:\esp\v6.0\esp-idf`. (Migrated up from v5.5.1
in 2026-04 — see `HANDOFF.md` for the migration notes.) Activate with:

- Desktop shortcut **"ESP-IDF 6.0 PWM Project"** — opens a new PowerShell
  with env active and cwd already at this project. Easiest for daily work.
- `esp6 pwm` PowerShell alias — activates v6.0 in the current PowerShell
  window AND cd's to this project. Defined in
  `D:\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1`.
- `C:\esp\v6.0\esp-idf\export.ps1` (PowerShell) or `export.bat` (cmd) —
  raw activation; no auto-cd. `export.sh` only works in Git Bash/MSYS2.

```bash
idf.py set-target esp32s3     # once (already done; sdkconfig.defaults pins it)
idf.py build
idf.py -p COM24 flash monitor # plain-text flash (current dev build has no Secure Boot)
```

The previous v5.5.1 install at `C:\Espressif\frameworks\esp-idf-v5.5.1`
is still on disk; don't `export` it inside a v6.0 shell — Python venv
collisions. v5.5.1 is reachable via the original installer Start-menu
shortcut **"ESP-IDF 5.5.1 CMD"** if you ever need to fall back.

現階段 `sdkconfig.defaults` 把 `CONFIG_SECURE_BOOT` 跟
`CONFIG_SECURE_FLASH_ENC_ENABLED` 都關掉 (temporary workaround)，所以
**不要** 跑 `encrypted-flash` — 那是 eFuse 已經燒過 flash-enc key 之後
的 re-flash 指令，在全新板子上會直接失敗。Secure Boot 重開的路徑
待做，詳見 `HANDOFF.md`。

## sdkconfig trap (hit repeatedly in this project)

`idf.py fullclean` wipes `build/` but **keeps `sdkconfig`**. Any change to
`sdkconfig.defaults` for a symbol already present in `sdkconfig` is silently
ignored. When modifying partition layout, Secure Boot, Flash Encryption, or
TinyUSB Kconfig:

```
del sdkconfig
idf.py fullclean
idf.py build
```

## Kconfig choice groups must be fully stated

For `choice` groups like `CONFIG_PARTITION_TABLE_TYPE`, setting only the
winning member (`CUSTOM=y`) isn't enough if `sdkconfig` has a stale `=y`
on a sibling (`TWO_OTA=y`). The sdkconfig merge picks "last wins" and
silently uses the built-in default partition table. `sdkconfig.defaults`
explicitly sets all siblings to `=n`; preserve this pattern for any other
choice group you touch.

## Security posture — 目前 disabled

`sdkconfig.defaults` 現階段把 `CONFIG_SECURE_BOOT` 跟
`CONFIG_SECURE_FLASH_ENC_ENABLED` 都設 `n` (temporary workaround)，因為
全新 eFuse 板子第一次 boot 這兩個 feature 都開時會 boot loop (`Saved PC`
指 `process_segment @ esp_image_format.c:622`)，root cause 待定位。

要加回 security 的順序：先單獨啟用 Secure Boot V2（不開 Flash Enc）確認
能 boot；再單獨啟用 Flash Enc（不開 SB）；兩者都能單獨 work 再 combined。
這個 bisect 還沒做，詳情見 `HANDOFF.md` 的 Bug 1 段。

Release-mode 的 irreversible eFuse checklist 仍在 `docs/release-hardening.md`；
Step 0 要改寫成「先確認 non-secure build 全功能驗證過，再單 feature
啟用 security」— 現在的 Step 0 不對。

`secure_boot_signing_key.pem` 已 gitignored；每個 dev 自己用
`espsecure.py generate_signing_key --version 2` 產。

## v6.0 driver split (component REQUIRES 變動)

v5.x 的 `driver` 變成多 per-peripheral components。如果某個 component
include `driver/uart.h` / `driver/gpio.h` / `driver/i2c.h` 之類 header
卻 build error 「no such file」，是 v6.0 抽掉 `driver` umbrella 對應
header 的 transitive include。在 component CMakeLists 加：

| header               | REQUIRES                |
|----------------------|-------------------------|
| `driver/uart.h`      | `esp_driver_uart`       |
| `driver/gpio.h`      | `esp_driver_gpio`       |
| `driver/i2c.h`       | `esp_driver_i2c`        |
| `driver/mcpwm_*.h`   | `esp_driver_mcpwm`      |
| `freertos/ringbuf.h` | `esp_ringbuf`           |

`driver` umbrella 仍存在但只有 i2c/touch_sensor/twai 還掛在底下，其他
都搬走了。

## Component manager pins

`main/idf_component.yml` 上目前 pin 三個 component：

- **`espressif/esp_tinyusb ~1.7.0`** — composite HID + CDC descriptor。
  v6.0 IDF 跟 1.7.x 仍相容（驗證過 build + 枚舉 OK）。
- **`espressif/cjson ^1.7.19`** — v6.0 把 IDF built-in `json` component
  拔掉，cJSON 改 component manager 上 `espressif/cjson`（直接 depend，
  不是 transitive）。`net_dashboard/CMakeLists.txt` 的 REQUIRES 寫
  `espressif__cjson`。
- **`espressif/mdns ^1.8.0`** — mDNS hostname `fan-testkit.local` 廣告
  用。v6.0 把 built-in `mdns` component 拔掉搬到 component manager，
  所以 `net_dashboard/CMakeLists.txt` 的 REQUIRES 要用 namespaced name
  `espressif__mdns`（不是 v5.x 的 `mdns`）。

Wi-Fi provisioning 走 SoftAP + captive portal，不依賴 BLE 或外部
provisioning component。第一次 boot 沒有 creds 時開 `Fan-TestKit-setup`
open AP，phone 接上後 Android captive-portal detector 會自動跳 browser。
成功後 success page 同時秀 `fan-testkit.local` 跟 raw IP。詳見
`components/net_dashboard/provisioning.c` 跟
`docs/superpowers/specs/2026-04-22-softap-captive-portal-design.md`。

### esp_tinyusb 1.7.x HID 限制

1.7.x 的 default config descriptor **不處理 HID**（只 cover
CDC/MSC/NCM/VENDOR）。開 `CFG_TUD_HID > 0` 就必須提供自製
`configuration_descriptor`，否則 `tinyusb_set_descriptors` 會 reject。
`usb_composite.c` 的 `s_configuration_descriptor[]` 就是這個 — IF0 HID,
IF1+IF2 CDC (via IAD)，EP 0x81 HID IN, 0x82 CDC notif IN, 0x03 CDC OUT,
0x83 CDC IN。

TinyUSB 的 `TUD_HID_DESCRIPTOR()` 要 compile-time report desc length，
所以 `HID_REPORT_DESC_SIZE` 寫死實際 byte 數並在 `usb_descriptors.c` 用
`_Static_assert(sizeof(usb_hid_report_descriptor) == N)` 綁住，改 report
descriptor 時 compile error 會立刻提醒同步更新。
