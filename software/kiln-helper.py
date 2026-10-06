#!/usr/bin/env python3
"""
Kiln Helper service: runs on the Pi next to kiln-controller.

What it does (and keeps doing when no screen is open):
  1. Phone alerts through ntfy (https://ntfy.sh).
  2. Automatic shutoff on serious problems (like a Skutt error code):
       E1  kiln isn't heating                 -> stops the firing
       E2  kiln much hotter than the plan     -> warns, then stops the firing
       E3  can't read the temperature         -> stops the firing
       E4  kiln heating while no firing runs  -> alarm, and cuts power if the safety relay is fitted
       E5  kiln falling behind the plan       -> warning only
       E6  controller box too hot             -> warning
       E7  kiln-controller stopped answering  -> alarm
       E8  no current to the elements         -> stops the firing (needs the optional power sensor)
  3. Delay start, firing history (last 10, with graphs, cost and cone notes).
  4. Grown-up PIN + max temperature lock shared by every screen.
  5. Optional relays on the Pi's pins:
       safety relay: in series with the contactor coil. ON = kiln may get power. Kiln Helper turns it
                     OFF on E4, and it also drops out by itself if the Pi loses power (fail-safe).
       vent relay:   runs a kiln vent fan during firings and while the kiln cools.
  6. Kiln settings from the screen: thermocouple offset, °F/°C, electricity price, kiln kW, PID numbers,
     emergency shutoff temperature (edits kiln-controller's config.py), and PID autotune (runs kiln-tuner.py).
  7. Temperature alarm (like Skutt's ALRM): buzzes your phone when the kiln reaches a temperature you pick.
  8. Optional power sensor (like PIDKiln's power meter): clamp-on current sensor + ADS1115 board, plus an
     optional voltage sensor. Catches a stuck relay instantly, a dead element (E8), and runs an element test.

Kiln Helper (the web page) talks to this service on port 8082.

Setup, on the Pi inside the kiln-controller folder:
  1. Put alerts.json in kiln-controller/public/ and change the topic to something only you know.
     Optional relays: add "safety_relay_pin": 24 and/or "vent_relay_pin": 25 (BCM numbers; kiln-controller
     already uses 17, 27, 22, 10 for the thermocouple board and 23 for the SSR). Most 2-channel relay boards
     are "active-low"; that's the default. If yours clicks ON when it should be OFF, set "relays_active_low": false.
  2. source venv/bin/activate && pip install websocket-client gpiozero lgpio
     (power sensor only: pip install adafruit-circuitpython-ads1x15, and turn on I2C in raspi-config)
  3. Test alerts:  python3 kiln-helper.py --test
  4. Start it at boot with kiln-helper.service.

This is a helper. The contactor, the separate high-limit controller and the E-stop are still the
real safety devices. Never leave them out.
"""
import json, math, os, re, subprocess, sys, threading, time, urllib.parse, urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import websocket   # pip install websocket-client

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(HERE, "public", "alerts.json")
HISTORY_FILE = os.path.join(HERE, "kiln-history.json")
DELAY_FILE = os.path.join(HERE, "kiln-delay.json")
PROTECT_FILE = os.path.join(HERE, "kiln-protect.json")    # PIN, max temp lock, safety-cut state
CONFIG_PY = os.path.join(HERE, "config.py")               # kiln-controller's own settings
PROFILES_DIR = os.path.join(HERE, "storage", "profiles")  # where kiln-controller keeps saved firings
BOX_TEMP_FILE = "/sys/class/thermal/thermal_zone0/temp"   # the Pi's chip temperature (milli-°C)

# ---------------- settings ----------------
with open(SETTINGS_FILE) as f:
    SET = json.load(f)
SET.setdefault("server", "https://ntfy.sh")
SET.setdefault("temp_scale", "f")
SET.setdefault("helper_port", 8082)
SET.setdefault("kiln", "localhost:8081")
# kiln-controller runs as a system service called "kiln-controller" (see its start-on-boot script)
SET.setdefault("restart_cmd", "sudo systemctl restart kiln-controller")
SET.setdefault("stop_cmd", "sudo systemctl stop kiln-controller")
SET.setdefault("start_cmd", "sudo systemctl start kiln-controller")
SET.setdefault("tuner_cmd", os.path.join(HERE, "venv", "bin", "python") + " " + os.path.join(HERE, "kiln-tuner.py"))
STATUS_URL = f"ws://{SET['kiln']}/status"
API_URL = f"http://{SET['kiln']}/api"

def F():    return SET["temp_scale"].lower() == "f"
def UNIT(): return "°F" if F() else "°C"
def deg(f_value):  return f_value if F() else (f_value - 32) * 5 / 9   # a temperature written in °F
def span(f_deg):   return f_deg if F() else f_deg * 5 / 9                # a difference written in °F

COOL_ENOUGH   = lambda: deg(125)
WARN_HOT      = lambda: span(50)    # E2 warning: this much over the plan for 2 minutes
STOP_HOT      = lambda: span(75)    # E2 stop: this much over the plan for 3 minutes
BEHIND        = lambda: span(50)    # E5 warning: this far behind for 5 minutes
NOT_HEATING   = lambda: span(100)   # E1: this far behind AND...
MIN_RISE_HOUR = lambda: span(12)    # ...rose less than this in the last hour (same idea as Skutt E1)
IDLE_RISE     = lambda: span(25)    # E4: rising this much in 5 min with no firing
IDLE_MIN_TEMP = lambda: deg(150)
VENT_OFF_BELOW = lambda: deg(150)   # keep the vent running until the kiln cools below this
BOX_HOT_C     = 75                  # E6: Pi chip temperature, °C
LOST_AFTER    = 60
KEEP_FIRINGS  = 10
LOCK = threading.Lock()

ERRORS = {
    "E1": ("Kiln isn't heating", "The kiln barely warmed up in the last hour, so Kiln Helper stopped the firing. "
           "Check the switches are on High, the kiln sitter is set, the E-stop is out, and the elements aren't broken."),
    "E2": ("Kiln got too hot", "The kiln stayed far hotter than the plan, so Kiln Helper stopped the firing. "
           "The relay may be stuck on. If the temperature keeps rising, turn off the breaker."),
    "E3": ("Can't read the temperature", "The thermocouple stopped giving good readings, so Kiln Helper stopped the firing. "
           "Check the yellow plug and the thermocouple tip."),
    "E8": ("No power to the elements", "The kiln was asking for full heat but no electricity was flowing, so Kiln Helper "
           "stopped the firing. An element may be broken, a wire loose, or the contactor didn't close."),
    "E4": ("Kiln heating while off", "No firing is running but the kiln is getting hotter. The relay may be stuck on. "
           "Press the E-stop or turn off the breaker NOW."),
}

# ---------------- helpers ----------------
def send(title, message, priority="default", tags=""):
    url = SET["server"].rstrip("/") + "/" + urllib.parse.quote(SET["topic"])
    query = urllib.parse.urlencode({"title": title, "priority": priority, "tags": tags})
    req = urllib.request.Request(url + "?" + query, data=message.encode("utf-8"), method="POST")
    try:
        urllib.request.urlopen(req, timeout=15)
        print("sent:", title)
    except Exception as e:
        print("could not send alert:", e)

def nice(name):
    return str(name or "").replace(".json", "").replace("-", " ").replace("_", " ").title()

def hours(sec):
    mins = max(0, round(sec / 60)); h, m = mins // 60, mins % 60
    return (f"{h} h " if h else "") + f"{m} min"

def clock(t):
    return time.strftime("%I:%M %p", time.localtime(t)).lstrip("0")

def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)

def kiln_api(cmd, **extra):
    body = json.dumps(dict(cmd=cmd, **extra)).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15)

def box_temp_c():
    try:
        with open(SET.get("box_temp_file", BOX_TEMP_FILE)) as f:
            return round(int(f.read().strip()) / 1000, 1)
    except Exception:
        return None

HISTORY = load(HISTORY_FILE, [])
DELAY = load(DELAY_FILE, None)
PROTECT = load(PROTECT_FILE, {})
PROTECT.setdefault("pin", ""); PROTECT.setdefault("max_f", None); PROTECT.setdefault("safety_cut", None)
LAST_ERROR = None    # the newest error a screen should show: {id, code, title, text, at}
ALARM = load(os.path.join(HERE, "kiln-alarm.json"), None)   # {"temp", "dir": "up"|"down", "set_at"} like Skutt's ALRM
ALARM_FILE = os.path.join(HERE, "kiln-alarm.json")
TUNE = {"state": "idle"}    # PID autotune progress: idle | running | done | failed | canceled

def check_alarm(temp):
    """Skutt-style temperature alarm: buzz the phone once when the kiln passes the set temperature."""
    global ALARM
    a = ALARM
    if not a or temp is None or a.get("rang_at"):     # rings once only
        return
    if (a["dir"] == "up" and temp >= a["temp"]) or (a["dir"] == "down" and temp <= a["temp"]):
        send(f"Kiln reached {round(a['temp'])}{UNIT()}", f"The temperature alarm you set went off. "
             f"The kiln is at {round(temp)}{UNIT()} now.", priority="high", tags="bell")
        with LOCK:
            ALARM = {**a, "rang_at": int(time.time())}      # screens see it rang, then it clears
            save(ALARM_FILE, ALARM)

# ---------------- optional current / voltage sensor (like PIDKiln's power meter) ----------------
# A clamp-on current sensor (SCT-013-030: 30 A gives 1 V) around one kiln supply wire, read through an
# ADS1115 board on the Pi's I2C pins. Optional second channel: a ZMPT101B voltage sensor.
# alerts.json: "amp_sensor": {"channel": 0, "amps_per_volt": 30}, "volt_sensor": {"channel": 1, "volts_per_volt": 250}
class PowerSensor:
    def __init__(self):
        self.ok, self.error, self.ads = False, None, None
        self.amp_cfg, self.volt_cfg = SET.get("amp_sensor"), SET.get("volt_sensor")
        self.fake = SET.get("fake_power_file")          # for testing without hardware
        if not (self.amp_cfg or self.volt_cfg):
            return
        if self.fake:
            self.ok = True
            return
        try:
            import board, busio
            import adafruit_ads1x15.ads1115 as ADS
            from adafruit_ads1x15.analog_in import AnalogIn
            self.ADS, self.AnalogIn = ADS, AnalogIn
            self.ads = ADS.ADS1115(busio.I2C(board.SCL, board.SDA), gain=1, data_rate=860)
            self.ok = True
        except Exception as e:
            self.error = str(e)
            print("power sensor problem:", e)

    def _rms(self, channel, scale):
        chan = self.AnalogIn(self.ads, [self.ADS.P0, self.ADS.P1, self.ADS.P2, self.ADS.P3][channel])
        vals = []
        end = time.time() + 0.25                       # about 15 mains cycles
        while time.time() < end:
            vals.append(chan.voltage)
        mid = sum(vals) / len(vals)
        return round(math.sqrt(sum((v - mid) ** 2 for v in vals) / len(vals)) * scale, 1)

    def read(self):
        if not self.ok:
            return None
        if self.fake:
            d = load(self.fake, {})
            return {"amps": d.get("amps"), "volts": d.get("volts")}
        try:
            out = {"amps": None, "volts": None}
            if self.amp_cfg:  out["amps"] = self._rms(self.amp_cfg.get("channel", 0), self.amp_cfg.get("amps_per_volt", 30))
            if self.volt_cfg: out["volts"] = self._rms(self.volt_cfg.get("channel", 1), self.volt_cfg.get("volts_per_volt", 250))
            return out
        except Exception as e:
            self.error = str(e)
            return None

POWER = PowerSensor()
POWER_NOW = {"amps": None, "volts": None, "at": 0}
ELEMENT_TEST = {"state": "idle"}   # Skutt-style full power test: idle | running | done | failed

def pin_ok(data):
    return not PROTECT.get("pin") or str(data.get("pin", "")) == PROTECT["pin"]

def saved_profile(name):
    """kiln-controller only reports a firing's NAME, so read the rest (label, slip) from its saved file."""
    try:
        with open(os.path.join(PROFILES_DIR, f"{name}.json")) as f:
            return json.load(f)
    except Exception:
        return {}

def label_of(profile, name):
    """'Add time' saves a hidden copy named kh-temp; its label is the real firing name."""
    if isinstance(profile, dict) and profile.get("label"):
        return profile["label"]
    if name:
        return saved_profile(name).get("label") or name
    return name

# ---------------- optional relays ----------------
class Relay:
    def __init__(self, key):
        self.dev, self.error = None, None
        pin = SET.get(key)
        if pin is None:
            return
        try:
            from gpiozero import OutputDevice
            # most cheap relay boards switch on when the pin goes LOW ("active-low")
            self.dev = OutputDevice(int(pin), active_high=not SET.get("relays_active_low", True), initial_value=False)
        except Exception as e:
            self.error = str(e)
            print(f"{key}: could not use pin {pin}: {e}")
    @property
    def fitted(self): return self.dev is not None
    @property
    def on(self):     return bool(self.dev and self.dev.value)
    def set(self, on):
        if self.dev:
            self.dev.on() if on else self.dev.off()

SAFETY = Relay("safety_relay_pin")
VENT = Relay("vent_relay_pin")
SAFETY.set(not PROTECT.get("safety_cut"))     # power allowed unless a cut is still waiting for a reset

def raise_error(code, extra=""):
    global LAST_ERROR
    title, text = ERRORS[code]
    LAST_ERROR = {"id": int(time.time() * 1000), "code": code, "title": title, "text": text + extra, "at": int(time.time())}
    send(f"{code}: {title}", text + extra, priority="urgent", tags="rotating_light")

def cut_power(code):
    if SAFETY.fitted:
        SAFETY.set(False)
        with LOCK:
            PROTECT["safety_cut"] = {"code": code, "at": int(time.time())}
            save(PROTECT_FILE, PROTECT)

# ---------------- watching the kiln ----------------
class Watcher:
    def __init__(self):
        self.state = None
        self.firing = None
        self.last_runtime = 0
        self.last_total = 0
        self.waiting_to_cool = False
        self.hot_since = self.stop_hot_since = self.behind_since = self.bad_since = None
        self.hot_alerted = self.behind_alerted = False
        self.run_temps = deque()     # (time, temp) over the last hour of the firing, for E1
        self.idle_temps = deque()
        self.idle_alerted_at = float("-inf")
        self.box_alerted_at = float("-inf")
        self.last_msg = time.time()
        self.lost_alerted = False
        self.record = None
        self.last_point = 0
        self.pending_end = None
        self.temp = None
        self.last_target = None
        self.stopped_by_error = False
        self.heat_out = None

    def settle_end(self, force=False):
        if self.pending_end and (force or time.time() - self.pending_end > 30):
            if not (LAST_ERROR and time.time() - LAST_ERROR["at"] < 60):   # an auto-stop already said why
                send("Firing stopped early", f"{nice(self.firing)} stopped before the end "
                     f"({hours(self.last_runtime)} of {hours(self.last_total)}).", priority="high", tags="warning")
            self.finish_record("stopped")
            self.pending_end = None

    def auto_stop(self, code, extra=""):
        try:
            kiln_api("stop")
        except Exception as e:
            print("could not stop the kiln:", e)
        if self.record is not None:
            self.record["error"] = code
        self.stopped_by_error = True     # a real stop: don't treat a quick restart as "Add time"
        raise_error(code, extra)
        self.hot_since = self.stop_hot_since = self.behind_since = self.bad_since = None

    def on_status(self, x):
        self.last_msg = time.time()
        if self.lost_alerted:
            send("Kiln is back", "Kiln Helper can see the kiln controller again.", tags="white_check_mark")
            self.lost_alerted = False
        if x.get("type") == "backlog" or "state" not in x:
            return
        state, temp, target = x["state"], x.get("temperature"), x.get("target")
        bad_temp = temp is None or (isinstance(temp, float) and math.isnan(temp)) or temp > deg(2500) or temp < deg(-5)
        self.temp = None if bad_temp else temp
        profile = x.get("profile")
        raw = profile.get("name") if isinstance(profile, dict) else profile
        name = label_of(profile, raw)
        test = raw in ("heat-test", "kh-element-test")
        now = time.time()
        ps = x.get("pidstats") or {}
        self.heat_out = ps.get("out") if state == "RUNNING" else 0

        if state == "RUNNING" and self.record is not None and x.get("cost") is not None:
            self.record["cost"] = round(float(x["cost"]), 2)
            self.record["currency"] = x.get("currency_type", "")

        # an "Add time" / "Skip step" restart of the same firing stays one firing
        if state == "RUNNING" and self.pending_end and name == self.firing:
            self.pending_end = None
            self.state = "RUNNING"

        # ---- started
        if state == "RUNNING" and self.state != "RUNNING":
            self.pending_end and self.settle_end(force=True)
            self.firing, self.waiting_to_cool = name, False
            self.run_temps.clear()
            send("Kiln test started" if test else "Firing started",
                 "Running a kiln test with the kiln empty." if test else
                 f"{nice(name)} is running. About {hours(x.get('totaltime', 0))}.", tags="fire")
            if not test:
                self.record = {"id": int(now), "name": name, "started": int(now),
                               "clay": (profile if isinstance(profile, dict) else saved_profile(name)).get("clay"),
                               "planned": int(x.get("totaltime", 0)), "points": [], "top": 0, "note": ""}
                self.last_point = 0

        # ---- ended
        if self.state == "RUNNING" and state != "RUNNING":
            finished = self.last_total and self.last_runtime >= self.last_total - 600
            if not test:
                if finished:
                    send("All done!", f"{nice(self.firing)} is finished. Keep the lid closed until it cools. "
                         f"I'll tell you when it's under {round(COOL_ENOUGH())}{UNIT()}.", tags="tada")
                    self.waiting_to_cool = True
                    self.finish_record("done")
                elif self.stopped_by_error:
                    self.finish_record("stopped")
                else:
                    self.pending_end = now
            self.stopped_by_error = False
            self.hot_since = self.stop_hot_since = self.behind_since = self.bad_since = None
            self.hot_alerted = self.behind_alerted = False

        if state == "RUNNING":
            self.last_runtime = x.get("runtime", 0)
            self.last_total = x.get("totaltime", 0)
            # E3: no good temperature for 30 seconds
            if bad_temp:
                self.bad_since = self.bad_since or now
                if now - self.bad_since > 30:
                    self.auto_stop("E3")
            else:
                self.bad_since = None
                if self.record is not None:
                    self.record["top"] = max(self.record["top"], round(temp))
                    if now - self.last_point >= 60 and len(self.record["points"]) < 2000:
                        self.record["points"].append([round(self.last_runtime / 60, 1), round(temp)])
                        self.last_point = now
                if target is not None:
                    diff = temp - target
                    # during a cooling step (slow cool) the plan is going down; being above it is harmless
                    cooling = self.last_target is not None and target < self.last_target - 0.01
                    self.last_target = target
                    # E2: too hot. Warn at 50° over for 2 min, stop at 75° over for 3 min.
                    self.hot_since = (self.hot_since or now) if diff > WARN_HOT() and not cooling else None
                    self.stop_hot_since = (self.stop_hot_since or now) if diff > STOP_HOT() and not cooling else None
                    if self.stop_hot_since and now - self.stop_hot_since > 180:
                        self.auto_stop("E2", f" It was {round(temp)}{UNIT()} but should have been {round(target)}{UNIT()}.")
                    elif self.hot_since and now - self.hot_since > 120 and not self.hot_alerted:
                        send("E2 warning: kiln is too hot", f"It's {round(temp)}{UNIT()} but should be {round(target)}{UNIT()}. "
                             "Kiln Helper will stop the firing if it gets worse.", priority="high", tags="warning")
                        self.hot_alerted = True
                    # E5: falling behind (warning only)
                    self.behind_since = (self.behind_since or now) if -diff > BEHIND() else None
                    if self.behind_since and now - self.behind_since > 300 and not self.behind_alerted:
                        send("E5: kiln can't keep up", f"It's {round(temp)}{UNIT()} but should be {round(target)}{UNIT()}. "
                             "The firing will take longer. Elements may be wearing out, or the lid is open.",
                             priority="high", tags="warning")
                        self.behind_alerted = True
                    # E1: far behind and barely rising for an hour
                    self.run_temps.append((now, temp))
                    while self.run_temps and now - self.run_temps[0][0] > 3600:
                        self.run_temps.popleft()
                    span_s = now - self.run_temps[0][0]
                    if (-diff > NOT_HEATING() and span_s >= 3300
                            and temp - self.run_temps[0][1] < MIN_RISE_HOUR()):
                        self.auto_stop("E1", f" It only went up {round(temp - self.run_temps[0][1])}° in an hour.")
            self.idle_temps.clear()
            VENT.set(True)
            check_alarm(self.temp)
        else:
            if self.waiting_to_cool and self.temp is not None and self.temp <= COOL_ENOUGH():
                send("Cool enough to open", f"The kiln is down to {round(self.temp)}{UNIT()}. "
                     "Open it slowly, and use gloves.", tags="snowflake")
                self.waiting_to_cool = False
            if VENT.on and (self.temp is None or self.temp < VENT_OFF_BELOW()):
                VENT.set(False)
            if self.temp is not None:
                self.idle_temps.append((now, self.temp))
                while self.idle_temps and now - self.idle_temps[0][0] > 300:
                    self.idle_temps.popleft()
                low = min(t for _, t in self.idle_temps)
                if self.temp > IDLE_MIN_TEMP() and self.temp - low > IDLE_RISE() and now - self.idle_alerted_at > 3600:
                    cut_power("E4")
                    raise_error("E4", f" It went up to {round(self.temp)}{UNIT()}." +
                                (" Kiln Helper cut the power with the safety relay." if SAFETY.fitted else ""))
                    self.idle_alerted_at = now
            if state != "RUNNING":
                check_alarm(self.temp)      # alarms also work while cooling ("tell me at 200°")
        self.state = state

    def finish_record(self, result):
        r = self.record
        if not r:
            return
        r["ended"], r["result"] = int(time.time()), result
        with LOCK:
            HISTORY.insert(0, r)
            del HISTORY[KEEP_FIRINGS:]
            save(HISTORY_FILE, HISTORY)
        self.record = None

    def check_lost(self):
        self.settle_end()
        if self.state == "RUNNING" and not self.lost_alerted and time.time() - self.last_msg > LOST_AFTER:
            send("E7: can't see the kiln", "Kiln Helper stopped hearing from the kiln controller during a firing. "
                 "Go check the kiln.", priority="urgent", tags="rotating_light")
            self.lost_alerted = True

W = Watcher()

# ---------------- background jobs: delay start, box temperature ----------------
def power_loop():
    """Read the optional current sensor. Current while the kiln should be off = stuck relay (E4) right away.
    No current while firing at full power = broken element or open circuit (E8)."""
    no_amps_since = None
    while True:
        r = POWER.read()
        if r:
            POWER_NOW.update(r, at=int(time.time()))
            amps = r.get("amps")
            if amps is not None:
                if W.state != "RUNNING" and TUNE["state"] != "running" and ELEMENT_TEST["state"] != "running" \
                        and amps > 2 and time.time() - W.idle_alerted_at > 3600:
                    cut_power("E4")
                    raise_error("E4", f" The power sensor sees {amps} A flowing with no firing running." +
                                (" Kiln Helper cut the power with the safety relay." if SAFETY.fitted else ""))
                    W.idle_alerted_at = time.time()
                heat = W.heat_out
                if W.state == "RUNNING" and heat is not None and heat > 0.95 and amps < 1:
                    no_amps_since = no_amps_since or time.time()
                    if time.time() - no_amps_since > 120:
                        W.auto_stop("E8", " The power sensor saw no current while the elements should have been on.")
                        no_amps_since = None
                else:
                    no_amps_since = None
        time.sleep(2 if POWER.ok else 30)

def element_test():
    """Skutt-style 'Full Power Test': with the kiln empty, run full power for 2 minutes and measure amps/volts."""
    ELEMENT_TEST.clear(); ELEMENT_TEST.update(state="running", started=int(time.time()))
    try:
        # a tiny firing that asks for a big rise, so the controller runs the elements at full power
        # asks for a very steep climb, so the controller keeps the elements fully on; stopped after 2 minutes
        prof = {"type": "profile", "name": "kh-element-test", "label": "Element test", "temp_units": "f" if F() else "c",
                "data": [[0, round(deg(70))], [600, round(deg(1000))]]}
        with open(os.path.join(PROFILES_DIR, "kh-element-test.json"), "w") as f:
            json.dump(prof, f)
        kiln_api("run", profile="kh-element-test")
        amps, volts = [], []
        end = time.time() + 120
        while time.time() < end:
            time.sleep(3)
            r = POWER.read() or {}
            if r.get("amps") is not None and (W.heat_out or 0) > 0.95: amps.append(r["amps"])
            if r.get("volts") is not None and (W.heat_out or 0) > 0.95: volts.append(r["volts"])
            ELEMENT_TEST["amps"] = r.get("amps"); ELEMENT_TEST["volts"] = r.get("volts")
        kiln_api("stop")
        if not amps:
            raise RuntimeError("no full-power reading. Is the kiln heating? Check the switches, sitter and E-stop")
        cfg = read_config()
        a = round(sum(amps) / len(amps), 1) if amps else None
        v = round(sum(volts) / len(volts), 1) if volts else None
        res = {"state": "done", "amps": a, "volts": v, "kw_rated": cfg.get("kw_elements")}
        if a and cfg.get("kw_elements"):
            volts_for_calc = v or SET.get("supply_volts", 240)
            expected = cfg["kw_elements"] * 1000 / volts_for_calc
            res["expected_amps"] = round(expected, 1)
            res["percent"] = round(a / expected * 100)
        ELEMENT_TEST.clear(); ELEMENT_TEST.update(res)
    except Exception as e:
        ELEMENT_TEST.clear(); ELEMENT_TEST.update(state="failed", error=str(e))
        try: kiln_api("stop")
        except Exception: pass

def autotune(target):
    """Runs kiln-controller's own kiln-tuner.py (Ziegler-Nichols). kiln-controller must be stopped while it runs."""
    TUNE.clear(); TUNE.update(state="running", stage="starting", started=int(time.time()), target=target, lines=[])
    try:
        subprocess.run(SET["stop_cmd"], shell=True, check=True, timeout=60)
        proc = subprocess.Popen(f"{SET['tuner_cmd']} -t {target}", shell=True, cwd=HERE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        TUNE["pid"] = proc.pid
        TUNE["proc"] = proc
        result = {}
        for line in proc.stdout:
            line = line.strip()
            TUNE["lines"] = (TUNE["lines"] + [line])[-6:]
            m = re.search(r"stage = (\w+), actual = ([\d.]+)", line)
            if m: TUNE["stage"], TUNE["temp"] = m.group(1), float(m.group(2))
            m = re.match(r"pid_(kp|ki|kd) = (-?[\d.eE+-]+)", line)
            if m: result[m.group(1)] = float(m.group(2))
        proc.wait()
        if TUNE.get("state") == "canceled":
            return
        if len(result) == 3:
            write_config(pid=result)
            TUNE.update(state="done", result=result)
            send("Autotune finished", "New PID numbers were saved. The kiln controller is starting again.", tags="white_check_mark")
        else:
            TUNE.update(state="failed", error="the tuner didn't finish")
    except Exception as e:
        TUNE.update(state="failed", error=str(e))
    finally:
        TUNE.pop("proc", None)
        subprocess.run(SET["start_cmd"], shell=True)

def background_loop():
    global DELAY, ALARM
    while True:
        time.sleep(5)
        W.check_lost()
        # forget an alarm 2 minutes after it rang (screens have had time to beep)
        if ALARM and ALARM.get("rang_at") and time.time() - ALARM["rang_at"] > 120:
            with LOCK:
                ALARM = None
                save(ALARM_FILE, None)
        # E6: controller box too hot
        b = box_temp_c()
        if b is not None and b > BOX_HOT_C and time.time() - W.box_alerted_at > 3600:
            send("E6: controller box is hot", f"The Pi inside the box is {b}°C. Check the SSR heat sink and the box fan, "
                 "and keep the box away from the kiln.", priority="high", tags="warning")
            W.box_alerted_at = time.time()
        # delay start
        with LOCK:
            d = DELAY
        if not d or time.time() < d["at"]:
            continue
        with LOCK:
            DELAY = None
            save(DELAY_FILE, None)
        if W.state == "RUNNING":
            send("Delayed firing didn't start", f"{nice(d['name'])} was set to start, but another firing "
                 "is already running.", priority="high", tags="warning")
            continue
        if PROTECT.get("safety_cut"):
            send("Delayed firing didn't start", "The safety relay cut the power earlier. A grown-up needs to reset it in Settings.",
                 priority="high", tags="warning")
            continue
        try:
            kiln_api("run", profile=d["name"])
        except Exception as e:
            send("Delayed firing didn't start", f"{nice(d['name'])} could not start: {e}", priority="high", tags="warning")

# ---------------- kiln-controller settings (config.py) ----------------
def read_config():
    try:
        text = open(CONFIG_PY).read()
    except Exception:
        return {}
    out = {}
    m = re.search(r'^thermocouple_offset\s*=\s*(-?[\d.]+)', text, re.M)
    if m: out["offset"] = float(m.group(1))
    m = re.search(r'^temp_scale\s*=\s*["\'](\w)["\']', text, re.M)
    if m: out["temp_scale"] = m.group(1).lower()
    for key in ("kwh_rate", "kw_elements", "pid_kp", "pid_ki", "pid_kd", "emergency_shutoff_temp"):
        m = re.search(r'^' + key + r'\s*=\s*(-?[\d.eE+-]+)', text, re.M)
        if m: out[key] = float(m.group(1))
    m = re.search(r'^currency_type\s*=\s*["\']([^"\']*)["\']', text, re.M)
    if m: out["currency_type"] = m.group(1)
    return out

def write_config(offset=None, scale=None, pid=None, numbers=None):
    text = open(CONFIG_PY).read()
    def set_number(text, key, value):
        text, n = re.subn(r'^(' + key + r'\s*=\s*)-?[\d.eE+-]+', lambda m: m.group(1) + f"{value:g}", text, flags=re.M)
        if not n: raise ValueError(f"couldn't find {key} in config.py")
        return text
    for k, v in (pid or {}).items():
        text = set_number(text, "pid_" + k, v)
    for k, v in (numbers or {}).items():
        text = set_number(text, k, v)
    if offset is not None:
        text, n = re.subn(r'^(thermocouple_offset\s*=\s*)-?[\d.]+', lambda m: m.group(1) + f"{offset:g}", text, flags=re.M)
        if not n: raise ValueError("couldn't find thermocouple_offset in config.py")
    if scale is not None:
        text, n = re.subn(r'^(temp_scale\s*=\s*)["\']\w["\']', lambda m: m.group(1) + f'"{scale}"', text, flags=re.M)
        if not n: raise ValueError("couldn't find temp_scale in config.py")
        SET["temp_scale"] = scale
        s = load(SETTINGS_FILE, {}); s["temp_scale"] = scale; save(SETTINGS_FILE, s)
    with open(CONFIG_PY + ".bak", "w") as f:
        f.write(open(CONFIG_PY).read())         # keep the old one, just in case
    with open(CONFIG_PY, "w") as f:
        f.write(text)

# ---------------- little web API for Kiln Helper ----------------
class API(BaseHTTPRequestHandler):
    def reply(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.reply(204, {})

    def do_GET(self):
        with LOCK:
            if self.path == "/info":
                return self.reply(200, {
                    "topic": SET["topic"], "delay": DELAY, "now": int(time.time()),
                    "locked": bool(PROTECT.get("pin")), "max_f": PROTECT.get("max_f"),
                    "box_c": box_temp_c(), "last_error": LAST_ERROR,
                    "safety": {"fitted": SAFETY.fitted, "cut": PROTECT.get("safety_cut"), "problem": SAFETY.error},
                    "vent": {"fitted": VENT.fitted, "on": VENT.on, "problem": VENT.error},
                    "config": read_config(), "kiln_state": W.state,
                    "alarm": ALARM, "tune": {k: v for k, v in TUNE.items() if k != "proc"},
                    "power": {"fitted": bool(SET.get("amp_sensor") or SET.get("volt_sensor")), "ok": POWER.ok,
                              "problem": POWER.error, **POWER_NOW},
                    "element_test": ELEMENT_TEST})
            if self.path == "/history":
                return self.reply(200, HISTORY)
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        global DELAY, PROTECT, LAST_ERROR, ALARM
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self.reply(400, {"error": "bad request"})
        p = self.path
        if p == "/delay":
            at, name = int(data.get("at", 0)), str(data.get("name", ""))
            if not name or not (time.time() < at < time.time() + 48 * 3600):
                return self.reply(400, {"error": "pick a time in the next 48 hours"})
            with LOCK:
                DELAY = {"name": name, "at": at}
                save(DELAY_FILE, DELAY)
            send("Firing scheduled", f"{nice(name)} will start at {clock(at)}.", tags="alarm_clock")
            return self.reply(200, {"ok": True, "delay": DELAY})
        if p == "/cancel":
            with LOCK:
                had = DELAY
                DELAY = None
                save(DELAY_FILE, None)
            if had:
                send("Delayed firing canceled", f"{nice(had['name'])} won't start.", tags="x")
            return self.reply(200, {"ok": True})
        if p == "/note":
            with LOCK:
                for r in HISTORY:
                    if r["id"] == data.get("id"):
                        r["note"] = str(data.get("note", ""))[:40]
                        save(HISTORY_FILE, HISTORY)
                        return self.reply(200, {"ok": True})
            return self.reply(404, {"error": "not found"})
        if p == "/alarm":

            t = data.get("temp")
            with LOCK:
                if t in (None, "", 0):
                    ALARM = None
                else:
                    t = float(t)
                    now_t = W.temp if W.temp is not None else t - 1
                    ALARM = {"temp": t, "dir": "up" if t > now_t else "down", "set_at": int(time.time())}
                save(ALARM_FILE, ALARM)
            return self.reply(200, {"ok": True, "alarm": ALARM})
        if p == "/ack_error":
            if LAST_ERROR and LAST_ERROR["id"] == data.get("id"):
                LAST_ERROR = None
            return self.reply(200, {"ok": True})
        if p == "/unlock":
            ok = pin_ok(data)
            if not ok: time.sleep(1)
            return self.reply(200, {"ok": ok})
        # ---- everything below needs the grown-up PIN (if one is set)
        if not pin_ok(data):
            time.sleep(1)
            return self.reply(403, {"error": "wrong PIN"})
        if p == "/protect":
            new = dict(PROTECT)
            if "new_pin" in data:
                pin = str(data["new_pin"])
                if pin and not (pin.isdigit() and len(pin) == 4):
                    return self.reply(400, {"error": "the PIN must be 4 numbers"})
                new["pin"] = pin
            if "max_f" in data:
                new["max_f"] = int(data["max_f"]) if data["max_f"] else None
            with LOCK:
                PROTECT = new
                save(PROTECT_FILE, PROTECT)
            return self.reply(200, {"ok": True, "locked": bool(PROTECT["pin"]), "max_f": PROTECT["max_f"]})
        if p == "/safety_reset":
            with LOCK:
                PROTECT["safety_cut"] = None
                save(PROTECT_FILE, PROTECT)
            SAFETY.set(True)
            send("Kiln power back on", "A grown-up reset the safety relay.", tags="white_check_mark")
            return self.reply(200, {"ok": True})
        if p == "/kiln_settings":
            if W.state == "RUNNING":
                return self.reply(409, {"error": "wait until no firing is running"})
            try:
                off = data.get("offset")
                nums = {}
                for k, lo, hi in (("kwh_rate", 0, 5), ("kw_elements", 0.1, 50), ("emergency_shutoff_temp", 500, 2600)):
                    if data.get(k) is not None: nums[k] = max(lo, min(hi, float(data[k])))
                pid = {k: float(data["pid"][k]) for k in ("kp", "ki", "kd") if isinstance(data.get("pid"), dict) and data["pid"].get(k) is not None}
                write_config(offset=None if off is None else max(-100, min(100, float(off))),
                             scale=data.get("temp_scale") if data.get("temp_scale") in ("f", "c") else None,
                             pid=pid or None, numbers=nums or None)
            except Exception as e:
                return self.reply(500, {"error": str(e)})
            return self.reply(200, {"ok": True, "config": read_config(), "restart_needed": True})
        if p == "/tune":
            if W.state == "RUNNING" or TUNE.get("state") == "running":
                return self.reply(409, {"error": "wait until no firing is running"})
            if W.temp is not None and W.temp > deg(150):
                return self.reply(409, {"error": "the kiln must be cool first"})
            target = max(deg(250), min(deg(600), float(data.get("target", deg(400)))))
            threading.Thread(target=autotune, args=(round(target),), daemon=True).start()
            return self.reply(200, {"ok": True})
        if p == "/tune_cancel":
            proc = TUNE.get("proc")
            TUNE["state"] = "canceled"
            if proc: proc.terminate()
            return self.reply(200, {"ok": True})
        if p == "/element_test":
            if not POWER.ok:
                return self.reply(409, {"error": "no power sensor fitted"})
            if W.state == "RUNNING" or ELEMENT_TEST.get("state") == "running":
                return self.reply(409, {"error": "wait until no firing is running"})
            if PROTECT.get("safety_cut"):
                return self.reply(409, {"error": "the safety relay has cut the power. Reset it first"})
            threading.Thread(target=element_test, daemon=True).start()
            return self.reply(200, {"ok": True})
        if p == "/restart":
            if W.state == "RUNNING":
                return self.reply(409, {"error": "wait until no firing is running"})
            subprocess.Popen(SET["restart_cmd"], shell=True)
            return self.reply(200, {"ok": True})
        self.reply(404, {"error": "not found"})

    def log_message(self, *args):
        pass

def serve():
    ThreadingHTTPServer(("0.0.0.0", int(SET["helper_port"])), API).serve_forever()

# ---------------- main ----------------
def main():
    if "--test" in sys.argv:
        send("Kiln Helper test", "Alerts are working!", tags="fire")
        return
    threading.Thread(target=serve, daemon=True).start()
    threading.Thread(target=background_loop, daemon=True).start()
    threading.Thread(target=power_loop, daemon=True).start()
    print(f"watching {STATUS_URL}, API on port {SET['helper_port']}, alerts to topic {SET['topic']}, "
          f"safety relay {'on pin ' + str(SET['safety_relay_pin']) if SAFETY.fitted else 'not fitted'}, "
          f"vent relay {'on pin ' + str(SET['vent_relay_pin']) if VENT.fitted else 'not fitted'}")
    while True:
        try:
            ws = websocket.create_connection(STATUS_URL, timeout=20)
            while True:
                try:
                    W.on_status(json.loads(ws.recv()))
                except websocket.WebSocketTimeoutException:
                    pass
        except Exception as e:
            print("connection problem:", e)
            time.sleep(10)

if __name__ == "__main__":
    main()
