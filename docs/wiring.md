# Wiring

[← Parts list](parts-list.md) · Next: [Build guide →](build-guide.md)

There are two separate sides. Keep them apart in the box, ideally with a metal divider between them.

1. **The low-voltage side:** the Raspberry Pi and small boards, 3.3 V and 5 V only. Safe to work on.
2. **The mains side:** 120 V or 240 V to the kiln. **Dangerous. Have a licensed electrician build or check it.**

Always unplug everything before touching any wiring.

## 1. Low-voltage side

![Low-voltage wiring diagram](images/wiring-low-voltage.svg)

### Thermocouple board (MAX31856)

| MAX31856 pin | Raspberry Pi pin | Notes |
| --- | --- | --- |
| VIN | Pin 1 (3.3 V) | |
| GND | Pin 6 (GND) | |
| SCK | Pin 11 (GPIO 17) | clock |
| SDO | Pin 13 (GPIO 27) | data to the Pi |
| CS | Pin 15 (GPIO 22) | chip select |
| SDI | Pin 19 (GPIO 10) | data from the Pi (the MAX31856 needs this one) |
| T+ / T− | thermocouple | In the US, type K **yellow is +** and **red is −** |

These are kiln-controller's default pins in `config.py`, so nothing needs changing. The installer switches kiln-controller from the MAX31855 board to the MAX31856.

### SSR driver

A Pi pin can't give the SSRs enough current on its own (about 16 mA), so a small transistor does the switching:

| From | To |
| --- | --- |
| Pin 16 (GPIO 23) | 1 kΩ resistor → 2N2222 **base** (middle leg) |
| 2N2222 **emitter** | GND (pin 20) |
| 2N2222 **collector** | SSR input **(−)** on both SSRs |
| Pin 2 (5 V) | SSR input **(+)** on both SSRs |

The two SSR inputs are wired side by side (in parallel). Check your transistor's pin order, because it varies by maker.

### Strongly recommended: safety relay

| Relay board | Raspberry Pi |
| --- | --- |
| VCC | Pin 4 (5 V) |
| GND | any GND |
| IN1: **safety relay** | Pin 18 (GPIO 24) |

Wire the relay's **normally-open** contact in series with the contactor coil (with the E-stop and the high-limit). Then add it to the settings file `~/kiln-controller/kiln-helper.json` and restart Kiln Helper (`sudo systemctl restart kiln-helper`):
```json
"safety_relay_pin": 24
```
Most of these boards switch on when the pin goes LOW ("active-low"), and that's what Kiln Helper expects. If yours clicks **on** when it should be off, add `"relays_active_low": false`.

**Check it before trusting it** (kiln unplugged from the wall, or the contactor's power side disconnected): with Kiln Helper running, the relay clicks **on**. Stop Kiln Helper (`sudo systemctl stop kiln-helper`) or pull the Pi's power: it must click **off** and the contactor must open. If it doesn't, the relay is wired to the wrong contact or the active-low setting is wrong.

### Optional: power sensor

| ADS1115 | Raspberry Pi |
| --- | --- |
| VDD | Pin 17 (3.3 V) |
| GND | any GND |
| SDA | Pin 3 (GPIO 2) |
| SCL | Pin 5 (GPIO 3) |
| A0 | the clamp sensor's signal |

The clamp's output swings above and below zero, so **bias** its other lead to the middle of 3.3 V with two 10 kΩ resistors (3.3 V → 10 kΩ → midpoint → 10 kΩ → GND) and a 10 µF capacitor from the midpoint to GND. Clip the clamp around **one** kiln supply wire, never around the whole cord. Then add to `~/kiln-controller/kiln-helper.json`:
```json
"amp_sensor": {"channel": 0, "amps_per_volt": 30}
```

## 2. Mains side: electrician

![Mains wiring diagram](images/wiring-mains.svg)

**Power path (240 V):** wall plug → fuses or breaker → contactor (both poles) → one SSR per leg → kiln outlet. Ground goes straight through and is bonded to the steel box.

**120 V kiln:** the same, but with **one SSR on the hot wire only**. Neutral goes through the contactor (or straight through) to the outlet, never through an SSR. Use a contactor with a **120 V coil**, and wire the coil circuit from hot to **neutral** instead of L1 to L2.

**The kiln itself isn't rewired.** It plugs into the box's outlet like it plugs into the wall now. If your kiln is hard-wired with no plug, have the electrician add a matching plug or wire the box in.

**Contactor coil circuit:** L1 → E-stop (normally closed) → high-limit relay (opens when too hot) → safety relay, strongly recommended (closed only while Kiln Helper runs and says it's OK) → contactor coil → L2. If **anything** in that chain opens, the contactor drops and the kiln loses all power.

Rules:
- Size the wire, plug, outlet, fuses, contactor and SSRs to the kiln's nameplate amps
- Mount the SSRs on their heat sinks with the fins outside the box, pointing up
- The high-limit controller uses its **own** thermocouple, separate from the Pi's
- Leave the kiln's **dial switches** and **kiln sitter** in place. Dials go all the way up to High, and the sitter gets a cone about two cones hotter than the firing, with its timer set longer than the firing. Kiln Helper's start checklist tells you both
- The Pi never touches 240 V. It only drives the SSRs' low-voltage inputs and the relay board

---
[← Parts list](parts-list.md) · Next: [Build guide →](build-guide.md)
