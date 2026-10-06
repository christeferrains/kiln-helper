# Troubleshooting and error codes

[← Using Kiln Helper](using-it.md) · Next: [Watching from outside the house →](remote-access.md)

## Error codes

Like a store-bought controller, Kiln Helper shows a code in a big banner and sends a phone alert. For the serious ones it **stops the firing by itself**, even when nobody is watching.

Every stop (yours or automatic) is **checked**: Kiln Helper waits for kiln-controller to confirm the elements are off. If it doesn't confirm within about 10 seconds, the **safety relay** cuts the power. If no safety relay is fitted, the screen and your phone say so plainly: **press the E-stop or turn off the breaker.**

| Code | What it means | What Kiln Helper does | What you do |
| --- | --- | --- | --- |
| **E1** | Kiln isn't heating: far behind the plan and barely warmer after an hour | **Stops the firing** | Dials on High? Kiln sitter cone and timer set? E-stop popped out? Elements broken? |
| **E2** | Kiln too hot: well above the plan (slow cool doesn't count) | Warns at 50°F over, **stops** at 75°F over | If it keeps rising, turn off the breaker. The relay may be stuck on |
| **E3** | Can't read the temperature, or the reading is stuck at exactly the same number while heating hard | **Stops the firing** (30 seconds of bad readings, or 10 minutes stuck) | Check the yellow plug and the thermocouple tip |
| **E4** | Kiln heating while it should be off | Alarm, and **cuts all power** if the safety relay is fitted | E-stop or breaker **now**. Replace the stuck SSR |
| **E5** | Falling behind the plan | Warning only | Lid closed? Elements may be wearing out |
| **E6** | Controller box too hot (over 75°C) | Warning | Check the SSR heat sinks and the fan. Move the box away from the kiln |
| **E7** | Kiln Helper stopped hearing from the kiln controller for a minute during a firing | **Tries to stop it; if that isn't confirmed, cuts the power** with the safety relay | Check the kiln. Then `journalctl -u kiln-controller -n 50` |
| **E8** | No current to the elements (needs the power sensor) | **Stops the firing** | Broken element, loose wire, or the contactor didn't close |
| **STOP not confirmed** | kiln-controller didn't confirm a stop | Safety relay cuts the power, or (no relay) tells you to | E-stop or breaker. Then check `journalctl -u kiln-controller` |
| **Kiln power is cut** | The safety relay opened (after E4, E7, an unconfirmed stop or a forced autotune stop) | Stays cut, even after a restart | Find the cause, then a grown-up taps **Reset** in ⚙ Settings → Controller box |

kiln-controller also has its own **emergency shutoff temperature** (set in ⚙ Settings → Kiln setup) and stops if the thermocouple gives too many errors.

## Common problems

**The kiln turned off partway through a firing**
- The **kiln sitter** tripped because its cone was too cool. Use the cone the start checklist shows (about two cones hotter than the firing)
- The kiln sitter's **timer** ran out. Set it longer than the firing. It only goes to 20 hours
- The E-stop was pressed, or the high-limit cut the power

**The temperature isn't going up**
- The kiln's **dial switches** are all the way up on **High**
- The kiln sitter has a cone in it, its button is pushed in, and its timer is set
- The kiln is plugged into the controller box, and the E-stop isn't pressed (twist to release)
- Still in **practice mode**? Run `./install.sh --real`
- Run the **Heat test** (⚙ Settings → Check the kiln)

**It heats too slowly or takes much longer than planned**
- Elements wear out. Run the **element test** (power sensor) or have a kiln tech check them
- Lid and peephole plugs closed (after the preheat)
- kiln-controller waits for a slow kiln to catch up. The screen says "Waiting for the kiln to catch up"

**It overshoots the plan**
- Run **Autotune** with the kiln empty and cool (⚙ Settings → Kiln setup → Advanced)

**The temperature shows "--" or a crazy number**
- The thermocouple plug came loose, or the tip is broken or touching an element
- Check the MAX31856 wiring ([Wiring](wiring.md))

**The cones don't match the screen**
- Thermocouples drift with age. Set a **thermocouple offset** (⚙ Settings → Kiln setup): cones too hot → +, not hot enough → −. Change 5–10° at a time.

**Pots cracked or blew up**
- They were still damp. Use **Raw greenware** in Fire by cone, or a longer **Preheat**. During the preheat, use the mirror test.

**"Not connected" or "No fresh reading" at the top**
- **Not connected:** this screen can't reach the Pi. The firing keeps going on the Pi, and Kiln Helper on the Pi keeps watching it. Check the Wi-Fi. Start is turned off until it's back.
- **No fresh reading:** the Pi is reachable but the kiln controller hasn't sent a temperature for 15 seconds. Don't trust the number on the screen. If it lasts a minute during a firing, Kiln Helper stops the firing (E7).
- The screen **never** switches itself into practice mode. Practice mode only appears when you ask for it.

**"Can't start: …"**
- Only one thing may heat at a time. A firing, a delayed start, autotune, the element test, a kiln-controller restart or a cut safety relay all block a new start. The message says which one.

**kiln.local doesn't open on my phone**
- Use the Pi's number address instead (`http://192.168.x.x:8081`), from your router's device list

**Something else?** Check the logs on the Pi:
```bash
journalctl -u kiln-controller -n 50
journalctl -u kiln-helper -n 50
```
Then open an [Issue](https://github.com/christeferrains/kiln-helper/issues) with what you see.

---
[← Using Kiln Helper](using-it.md) · Next: [Watching from outside the house →](remote-access.md)
