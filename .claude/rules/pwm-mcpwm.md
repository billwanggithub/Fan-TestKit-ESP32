# PWM / MCPWM Reference

## Glitch-free update mechanism

`pwm_gen_set()` writes new period and compare values; both latch on
`MCPWM_TIMER_EVENT_EMPTY` (TEZ — timer equals zero) via the
`update_cmp_on_tez` flag on the comparator. **Do not** call
`mcpwm_timer_stop` / restart in the update path for same-band changes —
that's where glitches come from.

## Frequency range and 2-band split

Frequency range is **10 Hz ~ 1 MHz**. The 16-bit MCPWM counter
(`MCPWM_LL_MAX_COUNT_VALUE = 0x10000`) cannot span that range with a
single fixed `resolution_hz`, so `pwm_gen.c` defines a 2-band table and
picks a band per call:

| Band | resolution_hz | freq range       | period_ticks   | duty bits |
|------|---------------|------------------|----------------|-----------|
| HI   | 10 MHz        | 153 Hz – 1 MHz   | 10 – 65359     | 3.3 – 16  |
| LO   | 625 kHz       | 10 Hz – 152 Hz   | 4112 – 62500   | 12 – 16   |

## MCPWM group prescaler is committed on first use

Once `mcpwm_new_timer()` runs the first time, `group->prescale` is
locked. Every subsequent timer in the same group must share that
group_prescale; only the per-timer `timer_prescale` (range [1..256])
can vary. That gives a max 256× spread of resolutions within one group.

**ESP-IDF v6.0 changed `MCPWM_GROUP_CLOCK_DEFAULT_PRESCALE` from 2 to
1** (see `esp_driver_mcpwm/src/mcpwm_private.h:55`). Group clock is now
160 MHz (was 80 MHz). At gp=1 the resolution range is 160 MHz down to
160 MHz / 256 = 625 kHz. HI=10 MHz uses timer_prescale=16; LO=625 kHz
uses timer_prescale=256. Both fit within gp=1's range, so cross-band
swaps don't trigger `"group prescale conflict"` errors.

The driver does not expose a public knob to force a different
group_prescale (`mcpwm_timer_config_t` has no such field), and the
auto-resolver in `mcpwm_set_prescale` greedily picks the smallest
group_prescale that satisfies the first call. That locks us at gp=1
forever once HI band's first `new_timer` runs.

1 Hz – 9 Hz cannot be reached at gp=1 + 16-bit counter. Extending
below 10 Hz requires switching the generator to LEDC (separate
peripheral with fractional dividers) or sharing group 1 with a second
operator/generator chain (but only one generator can drive the same
GPIO at a time, so cross-band swaps would need full generator
delete+recreate — slower than the current TEZ-based reconfigure). Both
are bigger refactors.

## v6.0 band-cross shadow-register flush

ESP32-S3 MCPWM `timer_period` and `timer_prescale` live in shadow
registers, with `timer_period_upmethod` selecting when shadow→active
copies. v6.0 `mcpwm_new_timer` sets `upmethod=0` ("immediate"), but
the active flush is **not** actually atomic with the shadow write.
Direct evidence (via `timer_status.timer_value` readback right after
`mcpwm_new_timer` returns): on a band cross, the counter is sometimes
still at the OLD peak (e.g. ~25000) while the shadow has the NEW peak
(e.g. 2000), and counter increment-rate measurement shows the active
prescale is also stale. The on-pin symptom is `old_resolution /
new_shadow_peak`, e.g. a 1 kHz request outputs 62.5 Hz
(= 625 kHz / 10000) or a 100 Hz request outputs 1.6 kHz
(= 10 MHz / 6250).

Fix in `reconfigure_for_band`: software-sync the timer to phase=0
right after `mcpwm_new_timer` returns. The reload-to-zero is itself a
TEZ event, which forces shadow→active flush for both prescale and
period atomically:

```c
MCPWM0.timer[0].timer_sync.timer_phase = 0;
MCPWM0.timer[0].timer_sync.timer_phase_direction = 0;
MCPWM0.timer[0].timer_sync.timer_synci_en = 1;
MCPWM0.timer[0].timer_sync.timer_sync_sw =
    ~MCPWM0.timer[0].timer_sync.timer_sync_sw;   // auto-clear toggle
MCPWM0.timer[0].timer_sync.timer_synci_en = 0;
```

Uses private register access (`hal/mcpwm_ll.h` + `soc/mcpwm_struct.h`
in `pwm_gen` component's `PRIV_REQUIRES`). Keep this — verified on
scope across hundreds of LO↔HI crosses under Wi-Fi load with no
miscounts.

### Earlier "fix" attempts that did NOT work — do not reintroduce

- Forcing `LOG_MAXIMUM_LEVEL_DEBUG=y` + runtime
  `esp_log_level_set("mcpwm", DEBUG)` — narrowed the race via
  LOGD-formatting delay, never closed it under load.
- `STOP_EMPTY → esp_rom_delay_us(N) → START_NO_STOP` "double-tap"
  after `mcpwm_timer_enable` — orthogonal to the shadow-flush issue.
- Halting the OLD counter via `mcpwm_ll_timer_set_count_mode(PAUSE)`
  before `mcpwm_del_timer` — stale-active-register survives
  teardown, so this changes nothing.

## Update path summary

- **Same-band updates** (e.g. 500 Hz → 600 Hz) stay glitch-free via TEZ.
- **Band-crossing updates** (152 Hz ↔ 153 Hz) go through
  `reconfigure_for_band()`: stop → disable → delete timer →
  `mcpwm_new_timer` with the new `resolution_hz` → reconnect operator →
  re-arm comparator → enable → start. This produces a brief (~tens of
  µs) output discontinuity. Operator, comparator, and generator objects
  are retained across the reconfigure so their action config (high on
  TEZ, low on compare) does not need to be re-registered.

The actual bit count at any freq is exposed via
`pwm_gen_duty_resolution_bits()` for the UI.

## Change-trigger output

The "change-trigger output" on a separate GPIO is a software pulse from
`control_task` after the write succeeds — not a hardware sync output.
Pulse width is clamped to [200 µs, 1000 µs] so it's always cleanly
observable regardless of PWM freq. If jitter on that trigger matters,
wire it to an MCPWM ETM event instead.
