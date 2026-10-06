# Using Kiln Helper

[← Install](install.md) · Next: [Troubleshooting →](troubleshooting.md)

## The main screen

![Main screen](images/main-screen.png)

- **The big circle** is the temperature inside the kiln. Blue = cool (OK to open), yellow = warm, orange = hot, red = very hot.
- **Slip:** your clay body (low-fire, mid-fire or high-fire). Kiln Helper only shows firings that suit it. Tap **Change** to switch.
- **Pick a firing**, then **▶ START**. It shows the estimated time and electricity cost. Tap **Try it first** to watch a pretend firing.
- **Before starting**, tick the safety checklist. It includes your manual kiln's parts: **dials all the way up to High**, and **which cone to put in the kiln sitter** and **how long to set its timer** for this firing. Choose **Now** or **Later** (delay start: the kiln starts by itself).
- **🔔 Set alarm:** beep here and buzz your phone at a temperature, going up or cooling down.

## During a firing

![During a firing](images/firing.png)

- Time left, the step it's on (for example "Step 2 of 6: preheating at 180°F"), and electricity cost so far
- **Heating power** shows how hard the elements are working
- **The graph:** grey is the plan, orange is the real kiln
- **See the whole firing** lists every step: done, now, and next with start times
- **＋ Add 30 minutes to this hold** shows during a hold. Use it if the pots are still drying: hold a mirror near the peephole, and if it fogs, add time.
- **⏭ Skip to the next step**
- **■ STOP** always works, even with the PIN lock on. A green **✓ Stopped** means the kiln controller confirmed the elements are off. A red **Stop NOT confirmed** means it didn't: the safety relay cut the power, or, if you don't have one, you must press the E-stop or turn off the breaker

After the firing: **Cooling down…** then **Ready to unload ✓** under 125°F.

## Making firings (⚙ Settings → Make a new firing)

![Make a firing](images/make-a-firing.png)

### The easy way: fire by cone
1. **What's going in?** *Raw greenware* sets Slow plus a 2-hour Preheat for you. *Glazed pots* uses your slip's glaze cone. *Luster/decals* uses cone 018 at Fast.
2. **Cone:** only cones your slip can take are listed.
3. **How fast?** These follow Skutt's Cone Fire speeds:
   - **Medium** (about 7.5 hours to cone 04) uses Skutt's published segments: 200°F/hr to 250, 400°F/hr to 1000, 180°F/hr to 1150, 300°F/hr to 1695, and 120°F/hr to the top.
   - **Slow** takes about 12 hours, for thick pieces.
   - **Fast** takes about 4 hours and is **only for luster and decals**.
4. **Preheat** (dry the pots): climbs 60°F/hr to 180°F and holds for 1, 2 or 4 hours, or overnight.
5. **Hold at the top:** 5–10 minutes is usual. Too long can over-fire.
6. **Slow cool** cools to 1500°F at 150°F/hr after the top. It helps many glazes.

### Or pick from the Library
Ready-made firings: Kiln Helper's own, plus community firings from [kiln-profiles](https://github.com/jbruce12000/kiln-profiles) such as Paragon and Bartlett bisque, cone 04 glazes, drop-and-hold, decals, and a **Preheat only (candling)** firing.

### Then adjust the steps
Each step is **Heat to** (or Cool to) → **Speed** (°/hour) → **Hold** (minutes). The picture shows the firing's shape, how long it takes, and its top temperature.

## Cone guide (low-fire)

| Cone | °F (108°F/hr finish) | Used for |
| --- | --- | --- |
| 022 | 1087 | luster, overglaze |
| 019 | 1252 | luster, decals |
| 018 | 1319 | luster, decals |
| 06 | 1828 | low-fire glaze |
| 05 | 1888 | low-fire glaze |
| 04 | 1945 | bisque, low-fire glaze |

The full chart (022–10) is in ⚙ Settings → Cone chart. **Witness cones** tell you what the pots really got: *just right* = the tip bent until it's level with the base.

## Settings (⚙, needs the PIN if one is set)

- **My slip, My firings, Firing history** (with graphs, cost, cone notes, and a spreadsheet download)
- **Grown-up lock:** a 4-digit PIN and a "never hotter than" temperature
- **Kiln setup:** thermocouple offset, °F/°C, electricity price, kiln kW, emergency shutoff, PID numbers and **Autotune**. Saving restarts the kiln controller (about a minute), so it can't be done during a firing. Switching °F/°C converts every temperature setting and your saved firings
- **Controller box:** box temperature, safety relay, power sensor and **element test**
- **Phone & alerts, Check the kiln (heat test), Cone chart, Error codes, Guided setup, Something wrong?**

---
[← Install](install.md) · Next: [Troubleshooting →](troubleshooting.md)
