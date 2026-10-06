# Parts list

[← Back to the front page](../README.md) · Next: [Wiring →](wiring.md)

Expect roughly **$350–450** for everything. Prices change, so check each link.

> **Size the power parts to your kiln.** Read the metal nameplate on the kiln's switch box for **volts** and **amps**. The parts below are for a **single-zone manual kiln under 40 A**: one with a kiln sitter, dial switches, or both.
> - **240 V kiln:** 2 SSRs (one per leg), a 2-pole contactor with a **240 V coil**.
> - **120 V kiln** (many small low-fire kilns): **1 SSR** on the hot wire, a contactor with a **120 V coil** ([Auber CN-PBC402-120V](https://www.auberins.com/index.php?main_page=product_info&products_id=130)). You can skip the second SSR and heat sink.
>
> A bigger kiln needs bigger relays, wire and contactor. Ask a kiln tech or electrician.

## Before you buy, check:
- [ ] Kiln brand and model
- [ ] Volts (120 V or 240 V) and amps, from the nameplate
- [ ] The plug on the kiln cord, and the breaker size on its circuit
- [ ] Kiln sitter (cone shutoff and timer), dial switches, or both. Kiln Helper works with either and leaves them in place
- [ ] Elements in good shape: no sagging, breaks or bad spots
- [ ] A spot to drill the thermocouple hole: mid-height, between elements, away from the kiln sitter

## The brain and screen

| Part | What it does | Where to buy | Approx. |
| --- | --- | --- | --- |
| Raspberry Pi 4 (2 GB is plenty), with the official power supply and a 16–32 GB microSD card | Runs Kiln Helper. Use a Pi 4: it's what the software was tested on, and a Zero can't drive the touchscreen | [Raspberry Pi 4](https://www.raspberrypi.com/products/raspberry-pi-4-model-b/) | $45–70 |
| Raspberry Pi Touch Display 2 (7") | The touchscreen on the front of the box. Optional, since your phone works too | [Adafruit](https://www.adafruit.com/product/6079) | $60 |

## Reading the temperature

| Part | What it does | Where to buy | Approx. |
| --- | --- | --- | --- |
| Adafruit MAX31856 thermocouple board | Turns the thermocouple's signal into a temperature for the Pi | [Adafruit 3263](https://www.adafruit.com/product/3263) · [guide](https://learn.adafruit.com/adafruit-max31856-thermocouple-amplifier/overview) | $18 |
| Kiln thermocouple, type K, 8-gauge, ceramic sheath (**× 2**) | One for the Pi, one for the separate high-limit controller | [Skutt SK1515 type K](https://www.amazon.com/Skutt-Thermocouple-8-Gauge-Replacement-SK1515/dp/B07DPCCZ6Q) · [KilnParts](https://kilnparts.com/collections/thermocouples) | $30–45 each |
| Type K extension wire | From the thermocouples to the box. It must be type K wire, not copper | [Auber KX22GA (per foot)](https://www.auberins.com/index.php?main_page=product_info&products_id=179) | $10 |
| Type K panel jack and plug (**× 2**) | The thermocouples unplug cleanly from the bottom of the box | [Auber TCCON](https://www.auberins.com/index.php?main_page=product_info&products_id=119) | $20 each |

## Switching the kiln

| Part | What it does | Where to buy | Approx. |
| --- | --- | --- | --- |
| 40 A zero-crossing solid-state relay (SSR) (**× 2** for 240 V, one per leg; **× 1** for 120 V) | Switches the elements on and off | [Auber SRDA40-LD (UL listed)](https://www.auberins.com/index.php?main_page=product_info&products_id=980) | $17 each |
| External-mount SSR heat sink (one per SSR) | Its fins stick out of the box to shed heat | [Auber HS40ETL](https://www.auberins.com/index.php?amp=&main_page=product_info&products_id=348) | $21 each |
| 2N2222 transistor + 1 kΩ resistor | Gives the SSRs a stronger on/off signal than a Pi pin can (a Pi pin gives about 16 mA) | Any electronics store | $3 |

## Safety parts: never skip these

| Part | What it does | Where to buy | Approx. |
| --- | --- | --- | --- |
| Contactor, 2-pole, 40/50 A, coil voltage = your kiln's voltage | Cuts ALL power. The SSRs can't override it | [240 V coil: Auber CN-PBC402-240V](https://www.auberins.com/index.php?main_page=product_info&products_id=164) · [120 V coil: CN-PBC402-120V](https://www.auberins.com/index.php?main_page=product_info&products_id=130) | $20 |
| High-limit controller, with its own thermocouple | Opens the contactor if the kiln ever gets too hot, whatever the Pi does | [Auber SYL-2342](https://www.auberins.com/index.php?main_page=product_info&products_id=1) (set up as an over-temperature alarm; check its manual) | $43 |
| Emergency stop, 22 mm, latching, normally closed (NC) | Big red button that cuts power by hand | [APIELE XB2 E-stop](https://www.amazon.com/APIELE-Emergency-Push-Button-Switch/dp/B08X6B8GML) | $12 |

## The box and wiring

| Part | What it does | Where to buy | Approx. |
| --- | --- | --- | --- |
| Steel enclosure, about 12 × 10 × 6 in, with a mounting plate | Holds everything. Steel, not plastic. Add a metal divider between the 240 V side and the low-voltage side | [VEVOR 12×10×6 steel box](https://www.vevor.com/electrical-enclosure-c_10749/vevor-steel-electrical-box-electrical-enclosure-box-12x10x6-carbon-steel-ip65-p_010902284840) | $40–60 |
| Kiln outlet, cord and plug, wire, fuses or breaker, terminal blocks, strain reliefs, small fan | The kiln plugs into the box and the box plugs into the wall | A local electrical supply. Match the kiln's plug type and the circuit's wire gauge | $50–80 |

## Optional extras

| Part | What it does | Where to buy | Approx. |
| --- | --- | --- | --- |
| 2-channel 5 V relay board, opto-isolated | Channel 1: **safety relay** in the contactor coil circuit, which cuts all power on a stuck relay (E4) and drops out if the Pi loses power. Channel 2: switches a **vent fan** | Any electronics store | $8–12 |
| Kiln vent | Pulls fumes out during firings and cooling | A vent made for your kiln | $200+ |
| SCT-013-030 clamp-on current sensor (30 A = 1 V) | Clips around one kiln wire. Gives the element test, E8 (dead element) and instant stuck-relay detection | Electronics store or Amazon | $10 |
| ADS1115 board | Lets the Pi read the current sensor | [Adafruit 1085](https://www.adafruit.com/product/1085) | $15 |
| ZMPT101B voltage sensor | Adds voltage to the element test. **Connects to mains, so have an electrician fit it** | Electronics store or Amazon | $5 |

## Software

Free. Kiln Helper installs [kiln-controller](https://github.com/jbruce12000/kiln-controller) for you. See [Install](install.md).

---
[← Back to the front page](../README.md) · Next: [Wiring →](wiring.md)
