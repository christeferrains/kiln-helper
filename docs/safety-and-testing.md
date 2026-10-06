# Safety and testing

[← Back to the front page](../README.md)

This page explains how Kiln Helper protects the kiln in software, how that was tested, what is still not handled, and which checks only a qualified person with the real hardware can do. **Kiln Helper is not certified safety equipment.** The contactor, high-limit controller, E-stop and the kiln's own Kiln Sitter (if it has one) are the protections that must work even when software fails.

## How it's built

```
 phone / touchscreen ──► Kiln Helper  (port 8081, the only thing on the network)
                           │  checks PIN, temperature lock, emergency limit,
                           │  "is something else heating?", fresh readings
                           ▼
                         kiln-controller  (127.0.0.1:8091, only reachable on the Pi itself)
                           │
                           ▼
                         GPIO 23 → SSRs → kiln          safety relay (GPIO 24) → contactor coil
```

- **Every start goes through Kiln Helper.** Starting, delayed starts, Add time / Skip, the heat test, the element test, autotune, saving firings and changing settings all check the **PIN** and the **temperature limits** on the Pi. The screen can't skip the checks, and kiln-controller can't be reached from other devices.
- **STOP never needs a PIN.** Neither does canceling a delayed start or autotune.
- **Every stop is confirmed.** Kiln Helper waits up to 10 seconds for kiln-controller to report that it isn't heating. If it doesn't, the safety relay opens the contactor. If no safety relay is fitted, the screen and the phone alert say so and tell you to use the E-stop or breaker.
- **Phone alerts never delay a shutdown.** They are sent from a background queue.
- **One heating job at a time.** A firing, a waiting delayed start, autotune, the element test, a kiln-controller restart or a cut safety relay all block new starts.
- **Delayed starts are checked again when they start.** If the firing was edited, the temperature lock lowered, or the kiln is busy, it doesn't start and you get an alert.
- **°F/°C changes convert everything:** the emergency shutoff and other temperatures (°C = (°F − 32) × 5/9), the thermocouple offset and control window (differences: × 5/9, no −32), the PID numbers (so the kiln heats the same), saved firings and a set alarm.
- **Practice mode is only on when asked** (`?practice=1` or the file opened on its own). A real screen that loses the Pi shows **Not connected**, and a Pi that stops getting readings shows **No fresh reading**. Start is turned off in both.
- **Settings are private.** The alert name and settings live in `~/kiln-controller/kiln-helper.json`, which isn't served to the network. Commands must come from the Kiln Helper screen itself (a special header and a same-site check), so another web page can't press buttons.
- **Restarts.** A cut safety relay stays cut across restarts until a grown-up resets it. The firing record is saved every minute, so if Kiln Helper restarts during a firing it carries on with the same record.
- **History is honest.** A firing is recorded as **done** only if kiln-controller ran it to the end. A STOP, an automatic stop or kiln-controller ending it early (for example its own emergency shutoff) is recorded as **stopped**.

## Running the tests

On any Linux computer (no Raspberry Pi or kiln needed):

```bash
pip install pytest playwright && python -m playwright install chromium
python -m pytest tests
```

| Test file | What it covers |
| --- | --- |
| `tests/test_safety.py` | Confirmed STOP; STOP when kiln-controller can't be reached or ignores it → safety relay; no relay → clear "no hardware cutoff" report; slow alerts don't delay STOP; automatic stops with failed stop; E3 bad readings; E4 heating while off; E7 lost contact; stale readings block starts; cut relay stays cut after restart |
| `tests/test_rules.py` | PIN on every heating path; STOP without PIN; temperature lock and emergency shutoff; unsafe firing names; Add time copies; delayed starts re-checked after the firing or lock changed; competing operations, including five starts at once |
| `tests/test_units_history.py` | °F/°C conversion of absolute temperatures, differences and PID; no drift on repeated runs; old °F firing files; alarm conversion; limits in °C; done vs stopped; restart recovery |
| `tests/test_tune_http.py` | Autotune cancel lets kiln-tuner turn the heater off; a tuner that won't quit is killed with its whole process group and the power is cut; tuner always gets °F; the network gateway (403 without PIN, STOP without PIN, other websites blocked, settings not public) |
| `tests/test_ui.py` | The real screen in a headless browser: a late connection never becomes practice mode and its STOP reaches the engine; failed STOP is shown; lost Pi shows Not connected; PIN asked by the Pi; practice mode never reaches the kiln; no script errors |
| `tests/test_real_engine.py` | The **real pinned kiln-controller** in simulation mode: late start, run and confirmed stop; engine killed mid-firing → relay cut; engine not reachable from the network; °F → °C switch keeps saved firings right. Set `KC_SOURCE` to a kiln-controller checkout with its `venv` |
| `tests/test_installer.py` | The installer as a normal user with sudo stubbed: first install, re-runs keep °F/°C and real/practice, conversion happens once, services are restarted, old settings migrated, refuses during a firing. Needs root to switch users and `KC_SOURCE` |

## Known limits

- **kiln-controller itself is unchanged** apart from listening only on the Pi. Anything running *on the Pi* (for example the original screen opened on the Pi's own browser at `http://127.0.0.1:8091`) can still talk to it directly without the PIN.
- After STOP, kiln-controller can leave the elements on for up to one control step (about 2 seconds) before switching off.
- A firing that kiln-controller ends in its last 2 minutes (for example its own emergency shutoff right at the top) can be recorded as done.
- The alert name is the only thing protecting phone alerts. Anyone who learns it can read your alerts, and anyone on your Wi-Fi who opens the Kiln Helper screen can see it.
- The screen asks for the PIN, but anyone on your Wi-Fi who knows it can start a firing. Use a PIN and keep the Pi off networks you don't trust. Don't port-forward it.
- The stuck-reading check (E3) only catches a reading frozen at exactly the same value for 10 minutes while heating hard.
- Automatic stops depend on the Pi running. The contactor, high-limit and E-stop must not.

## Checks that need a qualified person and the real hardware

The automatic tests can't check any of these. Do them before the first real firing, and again after any repair.

**Electrician (power off and locked out unless a step says otherwise):**
1. Breaker, wire gauge, plug, outlet and cord match the kiln's nameplate amps, with the right continuous-load margin.
2. SSRs, heat sinks and contactor are rated well above the kiln's amps; the heat sinks are outside the box and the box stays cool.
3. Ground runs straight through and is bonded to the steel box; mains and low-voltage sides are separated.
4. 240 V: both legs go through the contactor. 120 V: only the hot goes through the SSR; neutral never does.
5. The contactor coil circuit runs through the E-stop, the high-limit's output and the safety relay's **normally-open** contact.

**With a meter and the kiln empty (a qualified person present):**
6. **E-stop:** pressing it opens the contactor at once, during a firing.
7. **High-limit:** with its set point temporarily lowered, it opens the contactor by itself, with the Pi unplugged. Set it back below the kiln's rated maximum.
8. **Safety relay fail-safe:** stopping Kiln Helper (`sudo systemctl stop kiln-helper`) or pulling the Pi's power opens the contactor. It must not close again until Kiln Helper is running.
9. **Safety relay cut:** with the heat test running, stop kiln-controller (`sudo systemctl stop kiln-controller`), then press STOP on the screen. The screen must say the stop wasn't confirmed and the relay must open the contactor. Reset it afterwards.
10. **SSR failure:** an SSR stuck ON must not be able to heat the kiln once the contactor opens, and E4 must open the contactor (through the safety relay) when the kiln heats with no firing running. The electrician decides how to simulate a stuck SSR safely, for example on the bench with a low-voltage test load.
11. **Kiln Sitter and limit timer:** with the sitter in the power circuit, tripping the sitter (by hand) and letting the timer run out each cut the elements.
12. **Thermocouple:** it reads room temperature correctly, matches the high-limit's thermocouple within a few degrees when warm, and unplugging it stops a heat test (E3) within a minute.
13. **Polarity of the SSR signal:** with the kiln in real mode but nothing on the power side, the SSR LED is off when idle and blinks during the heat test.
14. **Dial switches:** all on High; the heat test reports the kiln is heating.
15. **First firings:** watch them in person. Compare witness cones with the screen and set the thermocouple offset.

---
[← Back to the front page](../README.md)
