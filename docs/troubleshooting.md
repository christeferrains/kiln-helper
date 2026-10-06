# Troubleshooting and error codes

[← Using Kiln Helper](using-it.md) · Next: [Watching from outside the house →](remote-access.md)

## Error codes

Like a store-bought controller, Kiln Helper shows a code in a big banner and sends a phone alert. For the serious ones it **stops the firing by itself**, even when nobody is watching.

| Code | What it means | What Kiln Helper does | What you do |
| --- | --- | --- | --- |
| **E1** | Kiln isn't heating: far behind the plan and barely warmer after an hour | **Stops the firing** | Switches on High? Kiln sitter set? E-stop popped out? Elements broken? |
| **E2** | Kiln too hot: well above the plan (slow cool doesn't count) | Warns at 50°F over, **stops** at 75°F over | If it keeps rising, turn off the breaker. The relay may be stuck on |
| **E3** | Can't read the temperature | **Stops the firing** after 30 seconds | Check the yellow plug and the thermocouple tip |
| **E4** | Kiln heating while it should be off | Alarm, and **cuts all power** if the safety relay is fitted | E-stop or breaker **now**. Replace the stuck SSR |
| **E5** | Falling behind the plan | Warning only | Lid closed? Elements may be wearing out |
| **E6** | Controller box too hot (over 75°C) | Warning | Check the SSR heat sinks and the fan. Move the box away from the kiln |
| **E7** | Lost contact with the kiln controller during a firing | Phone alarm | Check the Pi's power and Wi-Fi. The firing may still be running |
| **E8** | No current to the elements (needs the power sensor) | **Stops the firing** | Broken element, loose wire, or the contactor didn't close |

kiln-controller also has its own **emergency shutoff temperature** (set in ⚙ Settings → Kiln setup) and stops if the thermocouple gives too many errors.

## Common problems

**The temperature isn't going up**
- The kiln switches are on **High**
- The kiln sitter has a cone in it and its button is pushed in
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

**"Lost connection" on the screen**
- The firing keeps going on the controller. Only the screen lost touch. Check the Wi-Fi and refresh.

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
