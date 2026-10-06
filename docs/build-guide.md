# Build guide

[← Wiring](wiring.md) · Next: [Install the software →](install.md)

Build in four phases. **Don't connect 240 V until the low-voltage parts work on the bench.**

## Phase 1: Bench test (no kiln power)

1. **Install the software** on the Pi in practice mode. See [Install](install.md).
2. **Wire the MAX31856 board** to the Pi (see [Wiring](wiring.md)) and plug in a thermocouple.
3. Open Kiln Helper (`http://kiln.local:8081`). The big circle should show **room temperature**. Warm the thermocouple tip in your hand and watch it rise.
4. **Wire the SSR driver** to one SSR's input side only, with **nothing** connected to its power side. Practice mode doesn't drive the SSR pin, so for this test run `./install.sh --real`, start the **Heat test**, and watch the SSR's little LED blink on and off. Then press STOP. Leave it in real mode or run `./install.sh` again to go back to practice mode. Either is fine while nothing is wired to 240 V.
5. Optional: wire the relay board and power sensor, and check them in ⚙ Settings → Controller box.

## Phase 2: Build the power box (electrician)

1. Mount the parts on the box's plate. Put the 240 V parts (contactor, SSRs, fuses, outlet) on one side of a **metal divider**, and the Pi and small boards on the other.
2. Mount the SSR heat sinks so their fins are **outside** the box, pointing up.
3. Front panel: the touchscreen, the **red E-stop**, and a power light.
4. Bottom: the wall cord and kiln outlet with strain reliefs, plus the two yellow type K jacks.
5. Wire the mains side as shown in [Wiring](wiring.md): the power path, and the contactor coil circuit through the E-stop, the high-limit, and the optional safety relay.
6. **Have an electrician check everything before the first power-up.**

## Phase 3: Fit the kiln

1. Drill the thermocouple hole: mid-height, between elements, away from the kiln sitter. Seat the Pi's thermocouple about **1 inch** into the kiln.
2. Fit the high-limit's thermocouple next to it.
3. Set the high-limit controller's alarm to a little above your hottest firing. For low-fire, about 2000°F.
4. **Dial switches:** turn them all the way up to **High** and leave them there. Kiln Helper now does the controlling by switching the power on and off.
5. **Kiln sitter:** leave it in as a backup. Before each firing, the start checklist tells you which cone to put in it (about two cones hotter than the firing, so it never trips early) and how long to set its **timer** (longer than the firing). A KilnSitter timer only goes to **20 hours**, so Kiln Helper warns you about longer firings, for example an overnight preheat plus a slow bisque.
6. Mount the box on the wall **at least 3 ft from the kiln**, never above it.

## Phase 4: First firings, watched the whole time

1. On the Pi, run `./install.sh --real`. Now the kiln really switches.
2. Open Kiln Helper. The **guided setup** asks for your slip, a grown-up PIN, phone alerts, and a heat test.
3. **Heat test** (⚙ Settings → Check the kiln) with the kiln **empty**.
4. **Autotune** (⚙ Settings → Kiln setup → Advanced) with the kiln **empty and cool**, so the controller learns your kiln.
5. **Test the safety parts:** press the E-stop during a low firing and confirm power cuts. Briefly set the high-limit below the kiln temperature and confirm it cuts power, then set it back.
6. Fire with **witness cones** and compare them with the screen. If needed, set a thermocouple offset (⚙ Settings → Kiln setup).

### Before you ever leave a firing unattended
- [ ] Contactor, high-limit and E-stop all tested and cutting power
- [ ] Kiln sitter in place, with the backup cone and timer the start checklist shows
- [ ] SSRs on heat sinks, and the box stays cool through a full firing
- [ ] An electrician has checked the 240 V wiring
- [ ] Three watched firings finished, with cones matching the plan
- [ ] Phone alerts working (⚙ Settings → Phone & alerts → Send a test alert)
- [ ] Smoke detector in the room, and nothing that can burn within 18 inches of the kiln
- [ ] Your home insurance is OK with a homemade controller

---
[← Wiring](wiring.md) · Next: [Install the software →](install.md)
