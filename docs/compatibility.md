# Will my kiln work?

[← Back to the front page](../README.md) · Next: [Parts list →](parts-list.md)

Kiln Helper is made for **manual electric kilns**: the kind with dial switches, a cone-operated **Kiln Sitter** and a limit timer, or some of those. Manual kilns are not all alike, so check yours against this page **before you buy parts**. If anything here doesn't match your kiln, stop and ask a kiln technician or an electrician.

## 1. Read the nameplate

Every kiln has a metal nameplate, usually on the switch box. Write down:

| On the nameplate | Why it matters |
| --- | --- |
| **Volts** (120, 208 or 240) | Picks the contactor coil and how many SSRs you need |
| **Amps** | Every power part and wire must handle it **continuously** for many hours |
| **Watts** (or kW) | Goes into ⚙ Settings → Kiln setup for the firing cost and element test |
| **Phase** (1 or 3) | Kiln Helper's wiring is for **single-phase** only |
| **Maximum temperature or cone** | Never set Kiln Helper's emergency shutoff or temperature lock above it |

## 2. Does it fit?

| Your kiln | Kiln Helper |
| --- | --- |
| Single-phase **240 V**, up to **30 A** | ✅ Designed for. 2 SSRs (one per leg), 2-pole 240 V-coil contactor |
| Single-phase **120 V**, up to **15 A** (small low-fire kilns that plug into a normal outlet) | ✅ Designed for. 1 SSR on the hot wire, 120 V-coil contactor |
| **208 V** single-phase | ⚠ Should work like 240 V, but the contactor coil must suit 208 V and the element test needs `"supply_volts": 208` in `kiln-helper.json`. Check with an electrician |
| Over **30 A** | ⚠ Needs bigger SSRs, heat sinks, contactor and wire than the parts list. Have an electrician size them |
| **Three-phase** | ❌ Not supported |
| **One control zone**: all elements switched together from the one cord | ✅ Designed for |
| Separate **zones** that a digital controller runs on their own | ❌ Not supported. Kiln Helper has one thermocouple and one output |
| Already has a **digital controller** | ❌ Not for this. Use the controller it has |
| Max cone 6 or higher | ✅ Fine for low-fire and mid-fire. Kiln Helper refuses any firing above 2400°F, above your emergency shutoff, or above your temperature lock |
| Max cone below what you want to fire | ❌ Never fire past the kiln's rating |

## 3. Switches and dials

The controller box switches the **whole kiln at the plug**, so it sits in front of all the kiln's own switches.

| Switch setup | What to do |
| --- | --- |
| **One dial** (infinite switch, numbers 1 to 10 or Low to High) | Turn it to **High** for every firing |
| **One dial per ring** (often 2 or 3) | Turn **all** of them to **High**. All rings then heat together. If your witness cones always show one ring hotter, you can turn that ring down a little, but start with all on High |
| **Low / Med / High** rotary switches | **High** |
| **Toggle or push-button switches** | **On** |

Why High doesn't mean full blast: the Pi turns the power on and off many times a minute and decides how much heat the kiln gets. For a slow step, a hold or a low-fire firing it is off most of the time. A dial set below High just takes power away from what the Pi asks for. The kiln may then fall behind (E5) or fail to heat (E1).

## 4. Protections that must stay

| Protection | Required? | Notes |
| --- | --- | --- |
| **Contactor**, with the E-stop and high-limit in its coil circuit | **Yes** | SSRs usually fail **ON**, so something else must be able to cut power |
| **Separate high-limit controller** with its own thermocouple | **Yes** | Set it below the kiln's rated maximum. It works even if the Pi, Kiln Helper and kiln-controller all fail |
| **E-stop** (latching, normally closed) | **Yes** | On the outside of the box where anyone can reach it |
| Correct **breaker and wire** for the kiln's amps | **Yes** | An electrician should check this |
| **Safety relay** (one-channel relay board) | **Strongly recommended** | Without it, Kiln Helper can only *ask* kiln-controller to stop. With it, Kiln Helper cuts the contactor when a stop isn't confirmed, when contact is lost during a firing (E7), or when the kiln heats while it should be off (E4) |
| The kiln's own **Kiln Sitter** and **limit timer** | **Keep them if your kiln has them** | Never remove, wedge or bypass them. See below |
| The kiln's own **fuses**, **lid switch** and **switch box** | **Keep them** | Kiln Helper adds to the kiln's protections; it never replaces them |

### If your kiln has a Kiln Sitter

The sitter stays in the power circuit as a backup shutoff. Before each firing, Kiln Helper's checklist tells you:
- **Which cone to put in the sitter:** about two cones hotter than the firing, so it only trips if the kiln overshoots.
- **How long to set the limit timer:** half an hour longer than the firing. A KilnSitter timer only goes to **20 hours**, so Kiln Helper warns you about longer firings.

The sitter **reduces** some risks. It is not a reason to ignore an error code or a "STOP not confirmed" message, and Kiln Helper treats every problem the same way whether or not a sitter is fitted.

### If your kiln has no Kiln Sitter

Then the high-limit controller and the contactor are the only independent overheat protection. Don't fire without them, and fit the safety relay.

## 5. Stop and ask an electrician if…

- the nameplate is missing or unreadable
- the kiln is three-phase, over 30 A, or on a circuit you aren't sure about
- the cord, plug or outlet gets warm, or is a different type from the kiln's nameplate rating
- the kiln has more than one power cord, or a separate cord for a vent or controller
- you'd have to open the kiln's switch box or change its wiring to make anything fit

## What has been checked, and what is assumed

Be clear about how far this project has been tested:

| Checked | How |
| --- | --- |
| Kiln Helper's software: STOP, automatic stops, the safety-relay fallback, PIN and temperature limits on every heating path, delayed starts, °F/°C conversion, history, installer re-runs | Automatic tests with **simulated** hardware and the real, pinned kiln-controller in its simulation mode. See [Safety and testing](safety-and-testing.md) |
| **Not checked by this project** | No specific kiln make or model has been verified with this version on real hardware. Wiring, part ratings, relay behavior and kiln compatibility are design assumptions until a qualified person checks your build |

Fired a kiln with Kiln Helper? Tell us the make, model, volts, amps and switch setup in an **[Issue](https://github.com/christeferrains/kiln-helper/issues)** so it can be listed here as reported by a builder.

---
[← Back to the front page](../README.md) · Next: [Parts list →](parts-list.md)
