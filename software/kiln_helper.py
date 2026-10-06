#!/usr/bin/env python3
"""
Kiln Helper service. Runs on the Raspberry Pi next to kiln-controller (jbruce12000, pinned version).

ARCHITECTURE (why it's built this way)
  * kiln-controller (the engine) listens ONLY on 127.0.0.1:8091. Nothing on the network can reach it.
  * This service is the ONLY thing on the network (port 8081). It serves the Kiln Helper screen and a
    small API. Every request that starts or changes heating is checked HERE (PIN, temperature lock,
    emergency limit, nothing else heating) before it is passed to the engine. STOP never needs a PIN.
  * The engine stays unchanged except one line the installer patches (listen on 127.0.0.1).

SAFETY JOBS (keep running when no screen is open)
  E1 not heating -> stop         E2 far too hot -> warn, then stop      E3 bad/stuck reading -> stop
  E4 heating while off -> cut power with the safety relay (if fitted) and alarm
  E5 behind the plan -> warn     E6 controller box hot -> warn          E7 lost the engine -> stop/cut
  E8 no current to elements (optional sensor) -> stop
  Every stop is CONFIRMED: if the engine doesn't confirm within a few seconds, the optional safety relay
  cuts the contactor coil. If no safety relay is fitted, the alert says so clearly. Alerts never delay
  a shutdown (they are sent from a background queue).

This is a helper, not a certified safety device. The contactor, the separate high-limit controller,
the E-stop, and (if the kiln has one) the Kiln Sitter remain the real independent protections.
"""
import argparse, json, math, os, queue, re, signal, subprocess, sys, threading, time, urllib.parse, urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------------------------
# Temperatures and kiln-controller's config.py
# --------------------------------------------------------------------------------------------
# Settings in config.py that are expressed in the display unit (temp_scale):
ABS_KEYS = ("emergency_shutoff_temp", "throttle_below_temp", "sim_t_env")   # actual temperatures
DIFF_KEYS = ("thermocouple_offset", "pid_control_window")                   # temperature differences
NUM_KEYS = ABS_KEYS + DIFF_KEYS + ("kwh_rate", "kw_elements", "pid_kp", "pid_ki", "pid_kd", "listening_port")
HEATING_STATES = ("RUNNING", "PAUSED")      # PAUSED still holds temperature in kiln-controller
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
RESERVED = ("kh-", "heat-test")
MAX_TEMP_F = 2400                           # no profile may ask for more than this, whatever the settings

def f_to_c(f): return (f - 32) * 5 / 9
def c_to_f(c): return c * 9 / 5 + 32


class KilnConfig:
    """Reads and safely edits kiln-controller's config.py. Unit changes convert every temperature setting."""
    NUM = r"-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?"

    def __init__(self, path):
        self.path = path

    def text(self):
        with open(self.path) as f:
            return f.read()

    def read(self):
        t, out = self.text(), {}
        for key in NUM_KEYS:
            m = re.search(r"^" + key + r"\s*=\s*(" + self.NUM + ")", t, re.M)
            if m: out[key] = float(m.group(1))
        m = re.search(r"^temp_scale\s*=\s*[\"'](\w)[\"']", t, re.M)
        out["temp_scale"] = m.group(1).lower() if m else "f"
        m = re.search(r"^currency_type\s*=\s*[\"']([^\"']*)[\"']", t, re.M)
        if m: out["currency_type"] = m.group(1)
        m = re.search(r"^simulate\s*=\s*(True|False)", t, re.M)
        if m: out["simulate"] = m.group(1) == "True"
        if "thermocouple_offset" in out: out["offset"] = out["thermocouple_offset"]
        return out

    @staticmethod
    def fmt(v):
        v = round(float(v), 4)
        return str(int(v)) if v == int(v) else repr(v)

    def write(self, numbers=None, scale=None):
        t = self.text()
        for key, value in (numbers or {}).items():
            t, n = re.subn(r"^(" + key + r"\s*=\s*)" + self.NUM, lambda m: m.group(1) + self.fmt(value), t, count=1, flags=re.M)
            if not n: raise ValueError(f"couldn't find {key} in config.py")
        if scale is not None:
            t, n = re.subn(r"^(temp_scale\s*=\s*)[\"']\w[\"']", lambda m: m.group(1) + f'"{scale}"', t, count=1, flags=re.M)
            if not n: raise ValueError("couldn't find temp_scale in config.py")
        with open(self.path + ".bak", "w") as f:
            f.write(self.text())
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            f.write(t)
        os.replace(tmp, self.path)

    def converted_for_scale(self, new):
        """The numbers config.py needs so the kiln behaves the same in the other unit."""
        cfg = self.read()
        old = cfg["temp_scale"]
        if new not in ("f", "c"): raise ValueError("scale must be f or c")
        if new == old: return {}
        absf = f_to_c if new == "c" else c_to_f
        diff = (5 / 9) if new == "c" else (9 / 5)
        out = {}
        for k in ABS_KEYS:
            if k in cfg: out[k] = round(absf(cfg[k]), 2)
        for k in DIFF_KEYS:
            if k in cfg: out[k] = round(cfg[k] * diff, 3)
        # PID: output = kp*error + sum(error*dt)/ki + kd*d(error)/dt, and error shrinks by `diff` in the new unit
        if "pid_kp" in cfg: out["pid_kp"] = round(cfg["pid_kp"] / diff, 6)
        if "pid_kd" in cfg: out["pid_kd"] = round(cfg["pid_kd"] / diff, 6)
        if "pid_ki" in cfg: out["pid_ki"] = round(cfg["pid_ki"] * diff, 6)
        return out

    def change_scale(self, new):
        nums = self.converted_for_scale(new)
        if nums or self.read()["temp_scale"] != new:
            self.write(numbers=nums, scale=new)
        return nums


def normalize_profile_files(profile_dir):
    """kiln-controller trusts a saved file's "temp_units". Files saved in °F (e.g. by the original screen)
    are read WRONG after switching to °C (2000°F would become 2000°C). Store every file in °C, which the
    engine converts back for display in either unit. Returns the names it fixed."""
    fixed = []
    try: names = sorted(os.listdir(profile_dir))
    except OSError: return fixed
    for fn in names:
        if not fn.endswith(".json"): continue
        path = os.path.join(profile_dir, fn)
        p = load_json(path, None)
        if not isinstance(p, dict) or str(p.get("temp_units", "c")).lower() != "f" or not isinstance(p.get("data"), list): continue
        p["data"] = [[t, round(f_to_c(v), 3)] for t, v in p["data"]]
        p["temp_units"] = "c"
        save_json(path, p)
        fixed.append(p.get("name", fn))
    return fixed


# --------------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------------
def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)

def nice(name):
    return str(name or "").replace(".json", "").replace("-", " ").replace("_", " ").title()

def hours(sec):
    mins = max(0, round(sec / 60)); h, m = mins // 60, mins % 60
    return (f"{h} h " if h else "") + f"{m} min"

def profile_top(p):
    return max(float(pt[1]) for pt in p["data"])

def check_profile_data(p):
    data = p.get("data")
    if not isinstance(data, list) or len(data) < 2:
        return "the firing has no steps"
    last = -1
    for pt in data:
        if not (isinstance(pt, (list, tuple)) and len(pt) == 2): return "a step is malformed"
        t, temp = pt
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (t, temp)): return "a step has a bad number"
        if t < last: return "the steps go back in time"
        last = t
    return None


class Notifier:
    """Phone alerts through ntfy. Sending happens on a background thread so it can NEVER delay a shutdown."""
    def __init__(self, settings):
        self.settings, self.q, self.sent = settings, queue.Queue(maxsize=200), []
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, title, message, priority="default", tags=""):
        try:
            self.q.put_nowait((title, message, priority, tags))
        except queue.Full:
            pass

    def _run(self):
        while True:
            title, message, priority, tags = self.q.get()
            self.sent.append(title)
            topic = self.settings.get("topic")
            if not topic: continue
            url = self.settings.get("server", "https://ntfy.sh").rstrip("/") + "/" + urllib.parse.quote(topic)
            query = urllib.parse.urlencode({"title": title, "priority": priority, "tags": tags})
            try:
                urllib.request.urlopen(urllib.request.Request(url + "?" + query, data=message.encode(), method="POST"), timeout=10)
            except Exception as e:
                print("could not send alert:", e, flush=True)


class Relay:
    """Optional relay on a Pi pin. Most 2-channel boards are active-low (that's the default)."""
    def __init__(self, pin, active_low=True, factory=None):
        self.dev, self.error = None, None
        if pin is None: return
        try:
            if factory: self.dev = factory(int(pin), active_low)
            else:
                from gpiozero import OutputDevice
                self.dev = OutputDevice(int(pin), active_high=not active_low, initial_value=False)
        except Exception as e:
            self.error = str(e)

    @property
    def fitted(self): return self.dev is not None
    @property
    def on(self): return bool(self.dev and self.dev.value)
    def set(self, on):
        if self.dev: self.dev.on() if on else self.dev.off()


class EngineClient:
    """Talks to kiln-controller on localhost only."""
    def __init__(self, host="127.0.0.1", port=8091, timeout=5):
        self.base, self.ws_base, self.timeout = f"http://{host}:{port}", f"ws://{host}:{port}", timeout

    def api(self, cmd, **extra):
        body = json.dumps(dict(cmd=cmd, **extra)).encode()
        req = urllib.request.Request(self.base + "/api", data=body, method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            out = json.loads(r.read() or b"{}")
        if isinstance(out, dict) and out.get("success") is False:
            raise RuntimeError(out.get("error", "the kiln controller refused"))
        return out

    def _storage(self, message, want_list=True):
        import websocket
        ws = websocket.create_connection(self.ws_base + "/storage", timeout=self.timeout)
        try:
            ws.send(message)
            for _ in range(4):
                m = json.loads(ws.recv())
                if want_list and isinstance(m, list): return m
                if not want_list and isinstance(m, dict): return m
            raise RuntimeError("no answer from kiln-controller storage")
        finally:
            ws.close()

    def profiles(self):
        return self._storage("GET")

    def put_profile(self, p):
        p = {k: v for k, v in p.items() if k != "temp_units"}   # the engine then stores it in °C from the CURRENT unit
        r = self._storage(json.dumps({"cmd": "PUT", "profile": p}), want_list=False)
        if r.get("resp") != "OK": raise RuntimeError("kiln-controller could not save the firing")

    def delete_profile(self, name):
        self._storage(json.dumps({"cmd": "DELETE", "profile": {"type": "profile", "name": name, "data": ""}}), want_list=False)

    def status_socket(self):
        import websocket
        return websocket.create_connection(self.ws_base + "/status", timeout=20)


class PowerSensor:
    """Optional clamp-on current sensor (+ optional voltage sensor) through an ADS1115 board."""
    def __init__(self, settings):
        self.ok, self.error = False, None
        self.amp_cfg, self.volt_cfg, self.fake = settings.get("amp_sensor"), settings.get("volt_sensor"), settings.get("fake_power_file")
        if not (self.amp_cfg or self.volt_cfg): return
        if self.fake:
            self.ok = True; return
        try:
            import board, busio
            import adafruit_ads1x15.ads1115 as ADS
            from adafruit_ads1x15.analog_in import AnalogIn
            self.ADS, self.AnalogIn = ADS, AnalogIn
            self.ads = ADS.ADS1115(busio.I2C(board.SCL, board.SDA), gain=1, data_rate=860)
            self.ok = True
        except Exception as e:
            self.error = str(e)

    def _rms(self, channel, scale):
        chan = self.AnalogIn(self.ads, [self.ADS.P0, self.ADS.P1, self.ADS.P2, self.ADS.P3][channel])
        vals, end = [], time.time() + 0.25
        while time.time() < end: vals.append(chan.voltage)
        mid = sum(vals) / len(vals)
        return round(math.sqrt(sum((v - mid) ** 2 for v in vals) / len(vals)) * scale, 1)

    def read(self):
        if not self.ok: return None
        if self.fake:
            d = load_json(self.fake, {}); return {"amps": d.get("amps"), "volts": d.get("volts")}
        try:
            out = {"amps": None, "volts": None}
            if self.amp_cfg: out["amps"] = self._rms(self.amp_cfg.get("channel", 0), self.amp_cfg.get("amps_per_volt", 30))
            if self.volt_cfg: out["volts"] = self._rms(self.volt_cfg.get("channel", 1), self.volt_cfg.get("volts_per_volt", 250))
            return out
        except Exception as e:
            self.error = str(e); return None


class Refused(Exception):
    """A request that is not allowed. `kind` = 'pin' (needs/wrong PIN), 'busy', 'limit', 'bad'."""
    def __init__(self, kind, message):
        super().__init__(message); self.kind, self.message = kind, message


# --------------------------------------------------------------------------------------------
# The helper
# --------------------------------------------------------------------------------------------
ERRORS = {
    "E1": ("Kiln isn't heating", "The kiln barely warmed up in the last hour, so Kiln Helper stopped the firing. "
           "Check the dial switches are on High, the kiln sitter and its timer are set, the E-stop is out, and the elements aren't broken."),
    "E2": ("Kiln got too hot", "The kiln stayed far hotter than the plan, so Kiln Helper stopped the firing. "
           "The relay may be stuck on. If the temperature keeps rising, turn off the breaker."),
    "E3": ("Bad temperature reading", "The thermocouple stopped giving good readings, so Kiln Helper stopped the firing. "
           "Check the yellow plug and the thermocouple tip."),
    "E4": ("Kiln heating while off", "No firing is running but the kiln is getting hotter. The relay may be stuck on. "
           "Press the E-stop or turn off the breaker NOW."),
    "E7": ("Lost the kiln controller", "Kiln Helper stopped hearing from the kiln controller during a firing."),
    "E8": ("No power to the elements", "The kiln was asking for full heat but no electricity was flowing, so Kiln Helper "
           "stopped the firing. An element may be broken, a wire loose, or the contactor didn't close."),
}

class KilnHelper:
    # timings (seconds); tests shorten some of these
    STOP_ACK_S = 10          # how long to wait for the engine to confirm a stop
    START_ACK_S = 15         # how long to wait for the engine to confirm a start
    STATUS_STALE_S = 15      # no status for this long = the screen shows "no fresh reading"
    LOST_AFTER_S = 60        # no status for this long during a firing = E7: stop, else cut power
    BAD_TEMP_S = 30          # E3: no valid temperature for this long
    STUCK_TEMP_S = 600       # E3: exactly the same reading for this long while heating hard
    HOT_WARN_S, HOT_STOP_S, BEHIND_S = 120, 180, 300
    NOT_HEATING_WINDOW_S = 3600
    IDLE_WINDOW_S = 300
    TUNE_LINE_TIMEOUT_S = 90
    TUNE_MAX_S = 4 * 3600
    TUNE_EXIT_WAIT_S = 15
    ELEMENT_TEST_S = 120
    KEEP_FIRINGS = 10

    def __init__(self, settings_path, kc_dir, engine=None, relay_factory=None, notifier=None, start_threads=True):
        self.settings_path, self.kc_dir = settings_path, kc_dir
        self.S = load_json(settings_path, {})
        self.S.setdefault("server", "https://ntfy.sh")
        self.S.setdefault("gateway_port", 8081)
        self.S.setdefault("engine_port", 8091)
        self.S.setdefault("supply_volts", 240)
        self.S.setdefault("stop_cmd", ["sudo", "-n", "/usr/bin/systemctl", "stop", "kiln-controller"])
        self.S.setdefault("start_cmd", ["sudo", "-n", "/usr/bin/systemctl", "start", "kiln-controller"])
        self.S.setdefault("restart_cmd", ["sudo", "-n", "/usr/bin/systemctl", "restart", "kiln-controller"])
        self.S.setdefault("tuner_cmd", [os.path.join(kc_dir, "venv", "bin", "python"), os.path.join(kc_dir, "kiln-tuner.py")])
        self.S.setdefault("ui_file", os.path.join(kc_dir, "public", "index.html"))
        self.S.setdefault("box_temp_file", "/sys/class/thermal/thermal_zone0/temp")
        self.data = lambda name: os.path.join(kc_dir, name)
        self.config = KilnConfig(self.data("config.py"))
        self.engine = engine or EngineClient(port=int(self.S["engine_port"]))
        self.notify = notifier or Notifier(self.S)
        self.power = PowerSensor(self.S)
        self.lock = threading.RLock()            # protects shared state
        self.heat_lock = threading.Lock()        # only one start/adjust/test/tune decision at a time
        self.cond = threading.Condition(self.lock)

        self.history = load_json(self.data("kiln-history.json"), [])
        self.delay = load_json(self.data("kiln-delay.json"), None)
        self.protect = load_json(self.data("kiln-protect.json"), {})
        self.protect.setdefault("pin", ""); self.protect.setdefault("max_f", None); self.protect.setdefault("safety_cut", None)
        self.alarm = load_json(self.data("kiln-alarm.json"), None)
        self.current = load_json(self.data("kiln-current.json"), None)   # the firing being recorded (survives restarts)

        self.safety = Relay(self.S.get("safety_relay_pin"), self.S.get("relays_active_low", True), relay_factory)
        # Fail-safe: the relay only lets power through while this service runs and no cut is waiting for a reset.
        self.safety.set(not self.protect.get("safety_cut"))

        self.status, self.status_at, self.status_seq, self.backlog = None, 0.0, 0, None
        self.conn_gen = 0                     # +1 every time the engine status stream (re)connects
        self.op = None                        # None | "tune" | "element_test"
        self.tune = {"state": "idle"}
        self.element = {"state": "idle"}
        self.power_now = {"amps": None, "volts": None, "at": 0}
        self.last_error, self.last_stop = None, None
        self.restart_pending = False
        self.adjusting_until = 0.0            # an Add-time/Skip restart is expected until then
        self.stop_requested = False
        self.subscribers = []
        # watcher state
        self.prev_state, self.last_runtime, self.last_total, self.runtime_step = None, 0, 0, 0
        self.waiting_to_cool = False
        self.hot_since = self.stop_hot_since = self.behind_since = self.bad_since = None
        self.hot_alerted = self.behind_alerted = False
        self.last_temp, self.same_temp_since = None, None
        self.run_temps, self.idle_temps = deque(), deque()
        self.idle_alerted_at = self.box_alerted_at = float("-inf")
        self.lost_handled = False
        self.last_point_at = 0.0
        self.heat_out = 0
        self.auto_stopping = False
        self._last_target, self._restart_gen, self._tune_proc = None, 0, None
        normalize_profile_files(self.data(os.path.join("storage", "profiles")))
        if start_threads:
            for target in (self._status_loop, self._tick_loop, self._power_loop):
                threading.Thread(target=target, daemon=True).start()

    # ----- units -----
    def scale(self):
        try: return self.config.read()["temp_scale"]
        except Exception: return "f"
    def unit(self): return "°F" if self.scale() == "f" else "°C"
    def deg(self, f): return f if self.scale() == "f" else f_to_c(f)        # absolute °F -> display unit
    def span(self, f): return f if self.scale() == "f" else f * 5 / 9       # difference in °F -> display unit
    def to_f(self, t): return t if self.scale() == "f" else c_to_f(t)

    # ----- saving -----
    def _save(self, name, value):
        try: save_json(self.data(name), value)
        except Exception as e: print("could not save", name, e, flush=True)

    # ----- status from the engine -----
    def engine_state(self):
        return (self.status or {}).get("state")

    def fresh(self):
        return self.status is not None and time.time() - self.status_at < self.STATUS_STALE_S

    def _status_loop(self):
        while True:
            try:
                ws = self.engine.status_socket()
                with self.lock: self.conn_gen += 1
                while True:
                    self.on_message(json.loads(ws.recv()))
            except Exception:
                time.sleep(2)

    def on_message(self, x):
        if x.get("type") == "backlog":
            with self.lock: self.backlog = x
            self.publish({"type": "backlog", "backlog": x})
            return
        if "state" not in x: return
        with self.cond:
            self.status, self.status_at = x, time.time()
            self.status_seq += 1
            self.cond.notify_all()
        try:
            self.watch(x)
        except Exception as e:
            print("watcher error:", e, flush=True)
        self.publish({"type": "status", "status": x})

    def wait_for(self, pred, timeout, since=None):
        """Wait for a status NEWER than `since` (a status_seq taken before sending the command) where pred(status) is true."""
        end = time.time() + timeout
        with self.cond:
            seq = self.status_seq if since is None else since
            while time.time() < end:
                if self.status_seq > seq and pred(self.status): return True
                self.cond.wait(timeout=max(0.05, end - time.time()))
        return False

    # ----- screens (Server-Sent Events) -----
    def publish(self, msg):
        data = json.dumps(msg)
        with self.lock: subs = list(self.subscribers)
        for q in subs:
            try: q.put_nowait(data)
            except queue.Full: pass

    # ----- errors, power cut, stop -----
    def raise_error(self, code, extra=""):
        title, text = ERRORS[code]
        with self.lock:
            self.last_error = {"id": int(time.time() * 1000), "code": code, "title": title, "text": text + extra, "at": int(time.time())}
        self.notify.send(f"{code}: {title}", text + extra, priority="urgent", tags="rotating_light")
        self.publish({"type": "info"})

    def cut_power(self, code):
        """Open the safety relay (drops the contactor). Returns True only if a relay is fitted and was opened."""
        if not self.safety.fitted: return False
        self.safety.set(False)
        with self.lock:
            self.protect["safety_cut"] = {"code": code, "at": int(time.time())}
            self._save("kiln-protect.json", self.protect)
        return True

    def stop(self, by="user", code=None):
        """Stop all heating and CONFIRM it. Never needs a PIN. Falls back to the safety relay."""
        with self.lock:
            self.stop_requested = True
            self.adjusting_until = 0
        sent, err = True, None
        if self.op == "tune":
            # kiln-controller is switched off while kiln-tuner.py drives the heater: stop the tuner itself
            ack = self.tune_cancel(reason="stopped")["clean"]
            if not ack: err = "the autotune program had to be forced to quit"
        else:
            since = self.status_seq
            try:
                self.engine.api("stop")
            except Exception as e:
                sent, err = False, str(e)
            heating_now = self.engine_state() in HEATING_STATES
            ack = sent and ((not heating_now and self.fresh()) or
                            self.wait_for(lambda s: s.get("state") not in HEATING_STATES, self.STOP_ACK_S, since))
        hw = False
        if not ack:
            hw = self.cut_power(code or "STOP")
        result = {"acknowledged": bool(ack), "request_sent": sent, "hardware_cut": hw,
                  "hardware_available": self.safety.fitted, "error": err, "at": int(time.time()), "by": by}
        if not ack:
            msg = ("Kiln Helper could not confirm the kiln stopped" + (f" ({err})" if err else "") + ". " +
                   ("The safety relay cut the power." if hw else
                    "NO hardware cutoff is fitted: press the E-stop or turn off the breaker NOW."))
            self.notify.send("STOP NOT CONFIRMED", msg, priority="urgent", tags="rotating_light")
        with self.lock: self.last_stop = result
        self.publish({"type": "info"})
        return result

    def auto_stop(self, code, extra=""):
        """Called from the watcher; runs on its own thread so it can wait for the engine's confirmation."""
        with self.lock:
            if self.auto_stopping: return
            self.auto_stopping = True
            if self.current is not None: self.current["error"] = code
        def run():
            try:
                r = self.stop(by="auto", code=code)
                if not r["acknowledged"] and self.current is not None: self.finish_record("stopped")
                self.raise_error(code, extra + ("" if r["acknowledged"] else
                                 " The kiln controller didn't confirm the stop: " +
                                 ("the safety relay cut the power." if r["hardware_cut"] else "NO safety relay is fitted, turn off the breaker.")))
            finally:
                with self.lock: self.auto_stopping = False
        threading.Thread(target=run, daemon=True).start()

    # ----- rules for anything that heats -----
    def check_pin(self, pin):
        if self.protect.get("pin") and str(pin or "") != self.protect["pin"]:
            time.sleep(1)                     # slow down guessing
            raise Refused("pin", "This needs the grown-up PIN." if not pin else "Wrong PIN.")

    def busy(self, ignore_delay=False):
        if self.op == "tune": return "autotune is running"
        if self.op == "element_test": return "the element test is running"
        if not self.fresh(): return "Kiln Helper can't hear the kiln controller right now"
        if self.engine_state() in HEATING_STATES: return "a firing is already running"
        if self.restart_pending: return "the kiln controller is restarting with new settings"
        if self.protect.get("safety_cut"): return "the safety relay has cut the power; a grown-up must reset it"
        if self.delay and not ignore_delay: return "a delayed start is scheduled; cancel it first"
        return None

    def check_limits(self, p):
        bad = check_profile_data(p)
        if bad: raise Refused("bad", bad)
        top_f = self.to_f(profile_top(p))
        if top_f > MAX_TEMP_F: raise Refused("limit", f"No firing may go above {MAX_TEMP_F}°F.")
        lock = self.protect.get("max_f")
        if lock and top_f > lock + 1:
            raise Refused("limit", f"The grown-up lock only allows {round(self.deg(lock))}{self.unit()}.")
        emerg = self.config.read().get("emergency_shutoff_temp")
        if emerg is not None and profile_top(p) >= emerg:
            raise Refused("limit", f"This firing reaches the emergency shutoff ({round(emerg)}{self.unit()}), so it would be stopped.")

    def find_profile(self, name):
        for p in self.engine.profiles():
            if p.get("name") == name: return p
        raise Refused("bad", f"There's no firing called {nice(name)}.")

    def _run_engine(self, name, startat=0):
        """Ask the engine to run a saved firing and wait for it to confirm."""
        since = self.status_seq
        try:
            self.engine.api("run", profile=name, startat=int(startat))
        except Exception as e:
            raise Refused("bad", f"The kiln controller didn't start: {e}")
        if not self.wait_for(lambda s: s.get("state") in HEATING_STATES and s.get("profile") == name, self.START_ACK_S, since):
            self.stop(by="start-failed")     # make sure nothing is left half-started
            raise Refused("bad", "The kiln controller didn't confirm the start, so Kiln Helper stopped it.")

    def start(self, name, pin=None, startat=0, check_pin=True, ignore_delay=False):
        if check_pin: self.check_pin(pin)
        if not isinstance(name, str) or not name: raise Refused("bad", "Pick a firing.")
        with self.heat_lock:
            why = self.busy(ignore_delay=ignore_delay)
            if why: raise Refused("busy", f"Can't start: {why}.")
            p = self.find_profile(name)
            self.check_limits(p)
            with self.lock:
                self.stop_requested = False
            self._run_engine(name, startat)
        return {"ok": True}

    # ----- Add time / Skip (done here so the limits and the PIN are enforced) -----
    def adjust(self, action, pin=None):
        self.check_pin(pin)
        with self.heat_lock:
            st = self.status or {}
            if st.get("state") != "RUNNING" or not self.fresh(): raise Refused("busy", "No firing is running.")
            if self.op: raise Refused("busy", f"{self.op} is running.")
            raw = st.get("profile")
            p = self.find_profile(raw)
            data, rt = [list(x) for x in p["data"]], float(st.get("runtime", 0))
            i = next((k for k in range(1, len(data)) if rt < data[k][0]), None)
            if i is None: raise Refused("bad", "The firing is at its last moment.")
            hold = round(data[i][1]) == round(data[i - 1][1])
            label = p.get("label") or p.get("name")
            if action == "add_time":
                if not hold: raise Refused("bad", "Time can only be added during a hold.")
                new = {k: p[k] for k in ("clay", "contents") if k in p}
                new.update(type="profile", name="kh-temp", label=label,
                           data=[d if k < i else [d[0] + 1800, d[1]] for k, d in enumerate(data)])
                self.check_limits(new)
                self.engine.put_profile(new)
                target, startat = "kh-temp", rt / 60
            elif action == "skip":
                if i == len(data) - 1: raise Refused("bad", "This is the last step.")
                target, startat = raw, data[i][0] / 60
                self.check_limits(p)
            else:
                raise Refused("bad", "Unknown change.")
            with self.lock: self.adjusting_until = time.time() + 30
            try:
                since = self.status_seq
                self.engine.api("stop")
                if not self.wait_for(lambda s: s.get("state") not in HEATING_STATES, self.STOP_ACK_S, since):
                    raise Refused("bad", "The kiln controller didn't confirm the change.")
                self._run_engine(target, startat)
            except Exception as e:
                # The firing is now half-changed: make sure the kiln is really off (relay if needed) and record it.
                with self.lock:
                    self.adjusting_until = 0
                    if self.current is not None: self.current["error"] = "ADJUST"
                r = self.stop(by="adjust-failed", code="ADJUST")
                if self.current is not None and self.engine_state() not in HEATING_STATES: self.finish_record("stopped")
                msg = e.message if isinstance(e, Refused) else str(e)
                raise Refused("bad", msg + " The firing was stopped" + ("." if r["acknowledged"] else
                              (" and the safety relay cut the power." if r["hardware_cut"] else ", but the stop was NOT confirmed: turn off the breaker.")))
            finally:
                with self.lock: self.adjusting_until = 0
        return {"ok": True}

    # ----- profiles -----
    def save_profile(self, p, pin=None):
        self.check_pin(pin)
        if not isinstance(p, dict): raise Refused("bad", "Bad firing.")
        name = p.get("name", "")
        if not PROFILE_NAME_RE.match(name or "") or name.startswith(RESERVED):
            raise Refused("bad", "Names can use a–z, 0–9 and dashes (up to 40).")
        clean = {"type": "profile", "name": name, "data": p.get("data")}
        for k in ("label", "clay", "contents"):
            if isinstance(p.get(k), str): clean[k] = p[k][:40]
        self.check_limits(clean)
        self.engine.put_profile(clean)
        return {"ok": True}

    def delete_profile(self, name, pin=None):
        self.check_pin(pin)
        if not PROFILE_NAME_RE.match(name or "") or name.startswith(RESERVED): raise Refused("bad", "Bad name.")
        if (self.delay or {}).get("name") == name: raise Refused("busy", "That firing is scheduled. Cancel the delayed start first.")
        self.engine.delete_profile(name)
        return {"ok": True}

    # ----- delay start -----
    def schedule(self, name, at, pin=None):
        self.check_pin(pin)
        at = int(at or 0)
        if not (time.time() < at < time.time() + 48 * 3600): raise Refused("bad", "Pick a time in the next 48 hours.")
        with self.heat_lock:
            why = self.busy()
            if why: raise Refused("busy", f"Can't schedule: {why}.")
            self.check_limits(self.find_profile(name))
            with self.lock:
                self.delay = {"name": name, "at": at}
                self._save("kiln-delay.json", self.delay)
        self.notify.send("Firing scheduled", f"{nice(name)} will start at {time.strftime('%I:%M %p', time.localtime(at)).lstrip('0')}.", tags="alarm_clock")
        return {"ok": True, "delay": self.delay}

    def cancel_delay(self):
        with self.lock:
            had, self.delay = self.delay, None
            self._save("kiln-delay.json", None)
        if had: self.notify.send("Delayed firing canceled", f"{nice(had['name'])} won't start.", tags="x")
        return {"ok": True}

    def run_due_delay(self):
        with self.lock:
            d = self.delay
            if not d or time.time() < d["at"]: return
            self.delay = None
            self._save("kiln-delay.json", None)
        try:   # re-check EVERYTHING now: the firing, the lock or the kiln may have changed since it was scheduled
            self.start(d["name"], check_pin=False, ignore_delay=True)
        except Refused as e:
            self.notify.send("Delayed firing didn't start", f"{nice(d['name'])}: {e.message}", priority="high", tags="warning")
            with self.lock:
                self.last_error = {"id": int(time.time() * 1000), "code": "DELAY", "title": "Delayed firing didn't start",
                                   "text": e.message, "at": int(time.time())}

    # ----- heat test (UI) -----
    def heat_test(self, pin=None):
        self.check_pin(pin)
        p = {"type": "profile", "name": "heat-test", "data": [[0, round(self.deg(70))], [1800, round(self.deg(300))]]}
        with self.heat_lock:
            why = self.busy()
            if why: raise Refused("busy", f"Can't start: {why}.")
            self.check_limits(p)
            self.engine.put_profile(p)
            with self.lock: self.stop_requested = False
            self._run_engine("heat-test")
        return {"ok": True}

    # ----- the watcher: runs on every engine status message -----
    def watch(self, x):
        now = time.time()
        state, temp, target = x["state"], x.get("temperature"), x.get("target")
        raw = x.get("profile")
        bad_temp = temp is None or (isinstance(temp, float) and math.isnan(temp)) or \
                   self.to_f(temp) > 2500 or self.to_f(temp) < -5
        heating = state in HEATING_STATES
        test = raw in ("heat-test", "kh-element-test")
        prev = self.prev_state
        ps = x.get("pidstats") or {}
        self.heat_out = ps.get("out", 0) if heating else 0

        # ---- a firing appeared
        if heating and prev not in HEATING_STATES:
            if now < self.adjusting_until and self.current:
                pass                                                   # Add time / Skip: same firing continues
            elif prev is None and self.current and not test:
                # Kiln Helper (or the whole Pi) restarted while the engine kept firing: keep the same record
                self.notify.send("Kiln Helper restarted", "It picked up the running firing again.", tags="arrows_counterclockwise")
            else:
                self.waiting_to_cool = False
                self.run_temps.clear()
                label = raw
                try: label = next((p.get("label") or p["name"] for p in self.engine.profiles() if p["name"] == raw), raw)
                except Exception: pass
                if not test:
                    self.current = {"id": int(now), "name": label, "raw": raw, "started": int(now), "unit": self.unit(),
                                    "planned": int(x.get("totaltime", 0)), "points": [], "top": 0, "note": ""}
                    self._save("kiln-current.json", self.current)
                self.notify.send("Kiln test started" if test else "Firing started",
                                 "Running a kiln test with the kiln empty." if test else
                                 f"{nice(label)} is running. About {hours(x.get('totaltime', 0))}.", tags="fire")
            if self.current is not None: self.current["raw"] = raw
            self.lost_handled = False

        # ---- a firing ended
        if prev in HEATING_STATES and not heating:
            if now < self.adjusting_until:
                pass                                                   # expected restart (Add time / Skip)
            else:
                step = min(120, max(30, 3 * self.runtime_step))   # the engine ends it within one step of the end
                finished = (not self.stop_requested and self.current is not None and not self.current.get("error")
                            and self.last_total and self.last_runtime >= self.last_total - step)
                if self.current is not None:
                    if finished:
                        self.notify.send("All done!", f"{nice(self.current['name'])} is finished. Keep the lid closed until it cools.", tags="tada")
                        self.waiting_to_cool = True
                    elif not self.current.get("error"):
                        why = "it was stopped" if self.stop_requested else "the kiln controller ended it early"
                        self.notify.send("Firing stopped early", f"{nice(self.current['name'])} stopped before the end "
                                         f"({hours(self.last_runtime)} of {hours(self.last_total)}): {why}.", priority="high", tags="warning")
                    self.finish_record("done" if finished else "stopped")
                self.hot_since = self.stop_hot_since = self.behind_since = self.bad_since = self.same_temp_since = None
                self.hot_alerted = self.behind_alerted = False

        if heating:
            rt = x.get("runtime", 0) or 0
            if rt > self.last_runtime: self.runtime_step = max(self.runtime_step * 0.9, rt - self.last_runtime)
            self.last_runtime, self.last_total = rt, x.get("totaltime", 0) or 0
            if self.current is not None and x.get("cost") is not None:
                self.current["cost"] = round(float(x["cost"]), 2); self.current["currency"] = x.get("currency_type", "")
            # E3: no valid temperature
            if bad_temp:
                self.bad_since = self.bad_since or now
                if now - self.bad_since > self.BAD_TEMP_S: self.auto_stop("E3")
            else:
                self.bad_since = None
                # E3 (stuck): the exact same reading for a long time while the elements are on hard
                if temp == self.last_temp and self.heat_out > 0.5:
                    self.same_temp_since = self.same_temp_since or now
                    if now - self.same_temp_since > self.STUCK_TEMP_S:
                        self.auto_stop("E3", " The reading hasn't changed at all while heating.")
                else:
                    self.same_temp_since = None
                self.last_temp = temp
                if self.current is not None:
                    self.current["top"] = max(self.current["top"], round(temp))
                    if now - self.last_point_at >= 60 and len(self.current["points"]) < 2000:
                        self.current["points"].append([round(rt / 60, 1), round(temp)])
                        self.last_point_at = now
                        self._save("kiln-current.json", self.current)
                if target is not None:
                    diff = temp - target
                    cooling = self._last_target is not None and target < self._last_target - 0.01
                    self._last_target = target
                    self.hot_since = (self.hot_since or now) if diff > self.span(50) and not cooling else None
                    self.stop_hot_since = (self.stop_hot_since or now) if diff > self.span(75) and not cooling else None
                    if self.stop_hot_since and now - self.stop_hot_since > self.HOT_STOP_S:
                        self.auto_stop("E2", f" It was {round(temp)}{self.unit()} but should have been {round(target)}{self.unit()}.")
                    elif self.hot_since and now - self.hot_since > self.HOT_WARN_S and not self.hot_alerted:
                        self.notify.send("E2 warning: kiln is too hot", f"It's {round(temp)}{self.unit()} but should be {round(target)}{self.unit()}.",
                                         priority="high", tags="warning")
                        self.hot_alerted = True
                    self.behind_since = (self.behind_since or now) if -diff > self.span(50) else None
                    if self.behind_since and now - self.behind_since > self.BEHIND_S and not self.behind_alerted:
                        self.notify.send("E5: kiln can't keep up", f"It's {round(temp)}{self.unit()} but should be {round(target)}{self.unit()}.",
                                         priority="high", tags="warning")
                        self.behind_alerted = True
                    self.run_temps.append((now, temp))
                    while self.run_temps and now - self.run_temps[0][0] > self.NOT_HEATING_WINDOW_S: self.run_temps.popleft()
                    if (-diff > self.span(100) and now - self.run_temps[0][0] >= self.NOT_HEATING_WINDOW_S * 0.92
                            and temp - self.run_temps[0][1] < self.span(12)):
                        self.auto_stop("E1", f" It only went up {round(temp - self.run_temps[0][1])}° in an hour.")
                        self.run_temps.clear()
            self.idle_temps.clear()
            self.check_alarm(temp if not bad_temp else None)
        else:
            t = None if bad_temp else temp
            if self.waiting_to_cool and t is not None and t <= self.deg(125):
                self.notify.send("Cool enough to open", f"The kiln is down to {round(t)}{self.unit()}.", tags="snowflake")
                self.waiting_to_cool = False
            if t is not None and self.op is None:
                self.idle_temps.append((now, t))
                while self.idle_temps and now - self.idle_temps[0][0] > self.IDLE_WINDOW_S: self.idle_temps.popleft()
                low = min(v for _, v in self.idle_temps)
                if t > self.deg(150) and t - low > self.span(25) and now - self.idle_alerted_at > 3600:
                    hw = self.cut_power("E4")
                    self.raise_error("E4", f" It went up to {round(t)}{self.unit()}. " +
                                     ("Kiln Helper cut the power with the safety relay." if hw else
                                      "No safety relay is fitted, so Kiln Helper can't cut the power itself."))
                    self.idle_alerted_at = now
            self.check_alarm(t)
        self.prev_state = state

    def finish_record(self, result):
        r = self.current
        if not r: return
        r["ended"], r["result"] = int(time.time()), result
        with self.lock:
            self.history.insert(0, r)
            del self.history[self.KEEP_FIRINGS:]
            self._save("kiln-history.json", self.history)
            self.current = None
            self._save("kiln-current.json", None)

    # ----- temperature alarm -----
    def set_alarm(self, temp):
        with self.lock:
            if temp in (None, "", 0): self.alarm = None
            else:
                t = float(temp)
                now_t = (self.status or {}).get("temperature")
                now_t = t - 1 if now_t is None else now_t
                self.alarm = {"temp": t, "dir": "up" if t > now_t else "down", "set_at": int(time.time()), "unit": self.unit()}
            self._save("kiln-alarm.json", self.alarm)
        return {"ok": True, "alarm": self.alarm}

    def check_alarm(self, temp):
        a = self.alarm
        if not a or temp is None or a.get("rang_at"): return
        if a.get("unit") and a["unit"] != self.unit(): return          # set in the other unit; converted on unit change
        if (a["dir"] == "up" and temp >= a["temp"]) or (a["dir"] == "down" and temp <= a["temp"]):
            self.notify.send(f"Kiln reached {round(a['temp'])}{self.unit()}", f"The kiln is at {round(temp)}{self.unit()} now.", priority="high", tags="bell")
            with self.lock:
                self.alarm = {**a, "rang_at": int(time.time())}
                self._save("kiln-alarm.json", self.alarm)

    # ----- periodic checks -----
    def _tick_loop(self):
        while True:
            time.sleep(2)
            try: self.tick()
            except Exception as e: print("tick error:", e, flush=True)

    def tick(self):
        now = time.time()
        # E7: lost the engine during a firing -> try to stop, and if that can't be confirmed, cut the power
        if self.prev_state in HEATING_STATES and now - self.status_at > self.LOST_AFTER_S and not self.lost_handled and self.op is None:
            self.lost_handled = True
            def handle():
                r = self.stop(by="lost", code="E7")
                if self.current is not None: self.current["error"] = "E7"; self.finish_record("stopped")
                self.prev_state = None
                self.raise_error("E7", " " + ("It confirmed the stop." if r["acknowledged"] else
                                 "The safety relay cut the power." if r["hardware_cut"] else
                                 "No safety relay is fitted: check the kiln and turn off the breaker if it's still heating."))
            threading.Thread(target=handle, daemon=True).start()
        # E6: controller box too hot
        b = self.box_temp_c()
        if b is not None and b > 75 and now - self.box_alerted_at > 3600:
            self.notify.send("E6: controller box is hot", f"The Pi inside the box is {b}°C. Check the SSR heat sinks and the box fan.",
                             priority="high", tags="warning")
            self.box_alerted_at = now
        if self.alarm and self.alarm.get("rang_at") and now - self.alarm["rang_at"] > 120:
            with self.lock: self.alarm = None; self._save("kiln-alarm.json", None)
        self.run_due_delay()
        if self.restart_pending and self.fresh() and self.conn_gen > getattr(self, "_restart_gen", 0):
            self.restart_pending = False

    def box_temp_c(self):
        try:
            with open(self.S["box_temp_file"]) as f: return round(int(f.read().strip()) / 1000, 1)
        except Exception: return None

    # ----- optional power sensor -----
    def _power_loop(self):
        no_amps_since = None
        while True:
            r = self.power.read()
            if r:
                self.power_now.update(r, at=int(time.time()))
                amps = r.get("amps")
                state = self.engine_state()
                if amps is not None:
                    if state not in HEATING_STATES and self.op is None and amps > 2 and time.time() - self.idle_alerted_at > 3600:
                        hw = self.cut_power("E4")
                        self.raise_error("E4", f" The power sensor sees {amps} A flowing with no firing running. " +
                                         ("Kiln Helper cut the power." if hw else "No safety relay is fitted."))
                        self.idle_alerted_at = time.time()
                    if state == "RUNNING" and self.heat_out > 0.95 and amps < 1:
                        no_amps_since = no_amps_since or time.time()
                        if time.time() - no_amps_since > 120:
                            self.auto_stop("E8"); no_amps_since = None
                    else:
                        no_amps_since = None
            time.sleep(2 if self.power.ok else 30)

    def element_test(self, pin=None):
        self.check_pin(pin)
        if not self.power.ok: raise Refused("bad", "No power sensor is fitted.")
        with self.heat_lock:
            why = self.busy()
            if why: raise Refused("busy", f"Can't start: {why}.")
            prof = {"type": "profile", "name": "kh-element-test", "label": "Element test",
                    "data": [[0, round(self.deg(70))], [600, round(self.deg(1000))]]}   # steep: elements stay fully on
            self.engine.put_profile(prof)
            with self.lock: self.stop_requested = False
            self._run_engine("kh-element-test")
            self.op = "element_test"
            self.element = {"state": "running", "started": int(time.time())}
        threading.Thread(target=self._element_test_run, daemon=True).start()
        return {"ok": True}

    def _element_test_run(self):
        amps, volts = [], []
        try:
            end = time.time() + self.ELEMENT_TEST_S
            while time.time() < end and self.engine_state() == "RUNNING":
                time.sleep(2)
                t = (self.status or {}).get("temperature")
                if t is not None and t > self.deg(600): break         # never let a test get hot
                r = self.power.read() or {}
                if self.heat_out > 0.95:
                    if r.get("amps") is not None: amps.append(r["amps"])
                    if r.get("volts") is not None: volts.append(r["volts"])
                self.element.update(amps=r.get("amps"), volts=r.get("volts"))
        finally:
            self.op = None
            self.stop(by="element-test")
        cfg = self.config.read()
        if not amps:
            self.element = {"state": "failed", "error": "no full-power reading. Is the kiln heating? Check the dials, kiln sitter and E-stop"}
            return
        a = round(sum(amps) / len(amps), 1); v = round(sum(volts) / len(volts), 1) if volts else None
        res = {"state": "done", "amps": a, "volts": v, "kw_rated": cfg.get("kw_elements")}
        if cfg.get("kw_elements"):
            expected = cfg["kw_elements"] * 1000 / (v or float(self.S.get("supply_volts", 240)))
            res.update(expected_amps=round(expected, 1), percent=round(a / expected * 100))
        self.element = res

    # ----- PID autotune (kiln-controller's own kiln-tuner.py) -----
    def tune_start(self, target, pin=None):
        self.check_pin(pin)
        with self.heat_lock:
            why = self.busy()
            if why: raise Refused("busy", f"Can't start: {why}.")
            t = (self.status or {}).get("temperature")
            if t is None or t > self.deg(150): raise Refused("busy", "The kiln must be cool (under 150°F) first.")
            target = max(self.deg(250), min(self.deg(600), float(target or self.deg(400))))
            self.op = "tune"
            self.tune = {"state": "running", "stage": "starting", "started": int(time.time()), "target": round(target), "lines": []}
        threading.Thread(target=self._tune_run, args=(round(target),), daemon=True).start()
        return {"ok": True}

    def _tune_run(self, target):
        proc, result = None, {}
        try:
            subprocess.run(self.S["stop_cmd"], check=True, timeout=60)       # kiln-controller must not drive the pin too
            # kiln-tuner.py always takes -t in °F (it converts to °C itself when temp_scale is "c")
            cmd = list(self.S["tuner_cmd"]) + ["-t", str(round(self.to_f(target)))]
            env = dict(os.environ, PYTHONUNBUFFERED="1")                    # otherwise its lines arrive in big late chunks
            proc = subprocess.Popen(cmd, cwd=self.kc_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, start_new_session=True, env=env)   # own process group: we can stop ALL of it
            self.tune["pid"] = proc.pid
            self._tune_proc = proc
            lines = queue.Queue()
            threading.Thread(target=lambda: [lines.put(l) for l in proc.stdout] + [lines.put(None)], daemon=True).start()
            started, last_line = time.time(), time.time()
            while True:
                if self.tune.get("state") == "canceling": break
                try:
                    line = lines.get(timeout=1)
                except queue.Empty:
                    if time.time() - last_line > self.TUNE_LINE_TIMEOUT_S:
                        self.tune["error"] = "the tuner stopped reporting temperatures"; break
                    if time.time() - started > self.TUNE_MAX_S:
                        self.tune["error"] = "autotune took too long"; break
                    continue
                if line is None: break
                last_line = time.time()
                line = line.strip()
                self.tune["lines"] = (self.tune["lines"] + [line])[-6:]
                m = re.search(r"stage = (\w+), actual = (-?[\d.]+)", line)
                if m:
                    self.tune["stage"], self.tune["temp"] = m.group(1), float(m.group(2))
                    if float(m.group(2)) > target + self.span(150):
                        self.tune["error"] = "the kiln got far hotter than the autotune target"; break
                m = re.match(r"pid_(kp|ki|kd) = (-?[\d.eE+-]+)", line)
                if m: result[m.group(1)] = float(m.group(2))
        except Exception as e:
            self.tune["error"] = str(e); finished = False
        finally:
            hard = bool(self.tune.get("forced"))
            if proc is not None and proc.poll() is None:
                hard = not self._stop_tuner(proc) or hard
            if hard:
                # the tuner had to be killed, so its "turn the heater off" cleanup may not have run
                cut = self.cut_power("TUNE")
                self.notify.send("Autotune was forced to stop", "Check the kiln is not heating. " +
                                 ("The safety relay cut the power." if cut else "No safety relay is fitted: turn off the breaker if it's heating."),
                                 priority="urgent", tags="rotating_light")
            canceled = self.tune.get("state") == "canceling"
            if not canceled and not self.tune.get("error") and len(result) == 3:
                try:
                    self.config.write(numbers={"pid_kp": result["kp"], "pid_ki": result["ki"], "pid_kd": result["kd"]})
                    self.tune.update(state="done", result=result)
                    self.notify.send("Autotune finished", "New PID numbers were saved.", tags="white_check_mark")
                except Exception as e:
                    self.tune.update(state="failed", error=str(e))
            elif canceled:
                self.tune.update(state="canceled")
            else:
                self.tune.update(state="failed", error=self.tune.get("error") or "the tuner didn't finish")
            self.tune.pop("pid", None); self.tune.pop("forced", None)
            self._tune_proc = None
            # starting kiln-controller again also sets its output pin to OFF (its Output() starts low)
            with self.lock: self._restart_gen, self.restart_pending = self.conn_gen, True
            try: subprocess.run(self.S["start_cmd"], timeout=60)
            except Exception as e: print("could not start kiln-controller:", e, flush=True)
            self.op = None
            self.publish({"type": "info"})

    def _stop_tuner(self, proc):
        """Ctrl-C first (kiln-tuner's cleanup turns the heater off), then force. Returns True if it exited cleanly."""
        try:
            os.killpg(proc.pid, signal.SIGINT)
            proc.wait(timeout=self.TUNE_EXIT_WAIT_S)
            return True
        except Exception:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except Exception: pass
            try: proc.wait(timeout=5)
            except Exception: pass
            return False

    def tune_cancel(self, reason="canceled"):
        """Returns clean=True when the tuner exited by itself after Ctrl-C (its cleanup turns the heater off)."""
        if self.op != "tune": return {"ok": True, "clean": True}
        self.tune["state"] = "canceling"
        proc = self._tune_proc
        clean = True
        if proc is not None and proc.poll() is None:
            clean = self._stop_tuner(proc)
            if not clean:
                self.tune["forced"] = True
                self.cut_power("TUNE")
        return {"ok": True, "clean": clean}

    # ----- settings -----
    def unlock(self, pin):
        ok = not self.protect.get("pin") or str(pin or "") == self.protect["pin"]
        if not ok: time.sleep(1)
        return {"ok": ok}

    def set_protect(self, data):
        self.check_pin(data.get("pin"))
        new = dict(self.protect)
        if "new_pin" in data:
            p = str(data["new_pin"] or "")
            if p and not (p.isdigit() and len(p) == 4): raise Refused("bad", "The PIN must be 4 numbers.")
            new["pin"] = p
        if "max_f" in data:
            new["max_f"] = int(data["max_f"]) if data["max_f"] else None
        with self.lock:
            self.protect = new; self._save("kiln-protect.json", new)
        return {"ok": True, "locked": bool(new["pin"]), "max_f": new["max_f"]}

    def safety_reset(self, pin=None):
        self.check_pin(pin)
        with self.lock:
            self.protect["safety_cut"] = None; self._save("kiln-protect.json", self.protect)
        self.safety.set(True)
        self.notify.send("Kiln power back on", "A grown-up reset the safety relay.", tags="white_check_mark")
        return {"ok": True}

    def kiln_settings(self, data):
        self.check_pin(data.get("pin"))
        with self.heat_lock:
            if self.engine_state() in HEATING_STATES or self.op:
                raise Refused("busy", "Wait until nothing is heating.")
            cfg = self.config.read()
            old_scale, new_scale = cfg["temp_scale"], data.get("temp_scale") or cfg["temp_scale"]
            if new_scale not in ("f", "c"): raise Refused("bad", "Pick °F or °C.")
            # values the screen sends are in the CURRENT unit; apply them first, then convert everything together
            nums = {}
            if data.get("offset") is not None: nums["thermocouple_offset"] = max(-100, min(100, float(data["offset"])))
            for k, lo, hi in (("kwh_rate", 0, 5), ("kw_elements", 0.1, 50)):
                if data.get(k) is not None: nums[k] = max(lo, min(hi, float(data[k])))
            if data.get("emergency_shutoff_temp") is not None:
                e = float(data["emergency_shutoff_temp"])
                if not (self.deg(500) <= e <= self.deg(MAX_TEMP_F)): raise Refused("bad", "That emergency shutoff is out of range.")
                nums["emergency_shutoff_temp"] = e
            pid = data.get("pid") if isinstance(data.get("pid"), dict) else {}
            for k in ("kp", "ki", "kd"):
                if pid.get(k) is not None:
                    v = float(pid[k])
                    if not (math.isfinite(v) and v > 0): raise Refused("bad", "PID numbers must be above zero.")
                    nums["pid_" + k] = v
            if nums: self.config.write(numbers=nums)
            if new_scale != old_scale:
                normalize_profile_files(self.data(os.path.join("storage", "profiles")))
                self.config.change_scale(new_scale)
                self._convert_helper_state(old_scale, new_scale)
            self._restart_engine()
        return {"ok": True, "config": self.config.read(), "restarting": True}

    def _convert_helper_state(self, old, new):
        conv = f_to_c if new == "c" else c_to_f
        with self.lock:
            if self.alarm and not self.alarm.get("rang_at"):
                self.alarm = {**self.alarm, "temp": round(conv(self.alarm["temp"]), 1), "unit": "°F" if new == "f" else "°C"}
                self._save("kiln-alarm.json", self.alarm)

    def _restart_engine(self):
        with self.lock: self._restart_gen, self.restart_pending = self.conn_gen, True
        subprocess.Popen(self.S["restart_cmd"])

    def restart(self, pin=None):
        self.check_pin(pin)
        with self.heat_lock:
            if self.engine_state() in HEATING_STATES or self.op: raise Refused("busy", "Wait until nothing is heating.")
            self._restart_engine()
        return {"ok": True}

    # ----- what the screen asks for -----
    def info(self):
        with self.lock:
            return {
                "topic": self.S.get("topic"), "delay": self.delay, "now": int(time.time()),
                "locked": bool(self.protect.get("pin")), "max_f": self.protect.get("max_f"),
                "box_c": self.box_temp_c(), "last_error": self.last_error, "last_stop": self.last_stop,
                "safety": {"fitted": self.safety.fitted, "cut": self.protect.get("safety_cut"), "problem": self.safety.error},
                "config": self.config.read(), "kiln_state": self.engine_state(), "connected": self.fresh(),
                "status_age": round(time.time() - self.status_at, 1) if self.status_at else None,
                "alarm": self.alarm, "tune": {k: v for k, v in self.tune.items() if k != "pid"}, "op": self.op,
                "restart_pending": self.restart_pending,
                "power": {"fitted": bool(self.S.get("amp_sensor") or self.S.get("volt_sensor")), "ok": self.power.ok,
                          "problem": self.power.error, **self.power_now},
                "element_test": self.element,
            }


# --------------------------------------------------------------------------------------------
# HTTP gateway (the only thing on the network)
# --------------------------------------------------------------------------------------------
def make_handler(helper):
    POSTS = {
        "/api/run":          lambda d: helper.start(d.get("name"), d.get("pin")),
        "/api/stop":         lambda d: helper.stop(by="user"),                    # never needs a PIN
        "/api/adjust":       lambda d: helper.adjust(d.get("action"), d.get("pin")),
        "/api/heat_test":    lambda d: helper.heat_test(d.get("pin")),
        "/api/profiles/save":   lambda d: helper.save_profile(d.get("profile"), d.get("pin")),
        "/api/profiles/delete": lambda d: helper.delete_profile(d.get("name"), d.get("pin")),
        "/api/delay":        lambda d: helper.schedule(d.get("name"), d.get("at"), d.get("pin")),
        "/api/cancel":       lambda d: helper.cancel_delay(),                     # canceling can only make things safer
        "/api/alarm":        lambda d: helper.set_alarm(d.get("temp")),
        "/api/note":         lambda d: helper_note(helper, d),
        "/api/ack_error":    lambda d: helper_ack(helper, d),
        "/api/unlock":       lambda d: helper.unlock(d.get("pin")),
        "/api/protect":      lambda d: helper.set_protect(d),
        "/api/safety_reset": lambda d: helper.safety_reset(d.get("pin")),
        "/api/kiln_settings": lambda d: helper.kiln_settings(d),
        "/api/restart":      lambda d: helper.restart(d.get("pin")),
        "/api/tune":         lambda d: helper.tune_start(d.get("target"), d.get("pin")),
        "/api/tune_cancel":  lambda d: helper.tune_cancel(),                      # stopping heat needs no PIN
        "/api/element_test": lambda d: helper.element_test(d.get("pin")),
    }

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def reply(self, code, data, ctype="application/json"):
            body = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                self.send_response(302); self.send_header("Location", "/picoreflow/index.html")
                self.send_header("Content-Length", "0"); self.end_headers(); return
            if path in ("/picoreflow/index.html", "/index.html"):
                try:
                    with open(helper.S["ui_file"], "rb") as f: return self.reply(200, f.read(), "text/html; charset=utf-8")
                except OSError:
                    return self.reply(500, {"error": "screen file missing"})
            if path == "/api/events": return self.events()
            try:
                if path == "/api/info": return self.reply(200, helper.info())
                if path == "/api/history":
                    with helper.lock: return self.reply(200, helper.history)
                if path == "/api/profiles":
                    return self.reply(200, helper.engine.profiles())     # the screen hides the kh-/heat-test ones itself
                if path == "/api/config":
                    c = helper.config.read()
                    return self.reply(200, {k: c.get(k) for k in ("temp_scale", "kwh_rate", "currency_type", "kw_elements")})
            except Exception as e:
                return self.reply(502, {"error": f"kiln controller: {e}"})
            self.reply(404, {"error": "not found"})

        def events(self):
            q = queue.Queue(maxsize=100)
            with helper.lock: helper.subscribers.append(q)
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                first = []
                if helper.backlog: first.append(json.dumps({"type": "backlog", "backlog": helper.backlog}))
                if helper.status: first.append(json.dumps({"type": "status", "status": helper.status}))
                for m in first: self.wfile.write(f"data: {m}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        m = q.get(timeout=5)
                        self.wfile.write(f"data: {m}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")            # keeps the connection alive; lets the screen spot stale data
                    self.wfile.flush()
            except Exception:
                pass
            finally:
                with helper.lock:
                    if q in helper.subscribers: helper.subscribers.remove(q)

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            # Block other web pages from sending commands (CSRF): the screen always sends this header,
            # which a page on another site can't add without the browser asking first (and we never allow that).
            if self.headers.get("X-Kiln-Helper") != "1":
                return self.reply(403, {"error": "missing X-Kiln-Helper header"})
            origin, host = self.headers.get("Origin"), self.headers.get("Host")
            if origin and urllib.parse.urlparse(origin).netloc != host:
                return self.reply(403, {"error": "wrong origin"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536: return self.reply(413, {"error": "too big"})
            try: data = json.loads(self.rfile.read(n) or b"{}")
            except Exception: return self.reply(400, {"error": "bad request"})
            if not isinstance(data, dict): return self.reply(400, {"error": "bad request"})
            fn = POSTS.get(path)
            if not fn: return self.reply(404, {"error": "not found"})
            try:
                return self.reply(200, fn(data))
            except Refused as e:
                return self.reply(403 if e.kind == "pin" else 409, {"error": e.message, "kind": e.kind})
            except Exception as e:
                return self.reply(502, {"error": str(e)})

        def log_message(self, *a): pass

    return Handler

def helper_note(helper, d):
    with helper.lock:
        for r in helper.history:
            if r["id"] == d.get("id"):
                r["note"] = str(d.get("note", ""))[:40]; helper._save("kiln-history.json", helper.history); return {"ok": True}
    raise Refused("bad", "Not found.")

def helper_ack(helper, d):
    with helper.lock:
        if helper.last_error and helper.last_error["id"] == d.get("id"): helper.last_error = None
    return {"ok": True}

def serve(helper, host="0.0.0.0", port=None):
    srv = ThreadingHTTPServer((host, int(helper.S["gateway_port"] if port is None else port)), make_handler(helper))
    srv.daemon_threads = True
    return srv


def main():
    ap = argparse.ArgumentParser(description="Kiln Helper service")
    ap.add_argument("--kc-dir", default=HERE, help="kiln-controller folder")
    ap.add_argument("--settings", default=None, help="settings file (default <kc-dir>/kiln-helper.json)")
    ap.add_argument("--test", action="store_true", help="send a test phone alert and exit")
    ap.add_argument("--set-scale", choices=["f", "c"], help="switch config.py between °F and °C, converting every temperature setting")
    ap.add_argument("--show-config", action="store_true")
    a = ap.parse_args()
    settings = a.settings or os.path.join(a.kc_dir, "kiln-helper.json")
    if a.set_scale or a.show_config:
        cfg = KilnConfig(os.path.join(a.kc_dir, "config.py"))
        if a.set_scale:
            normalize_profile_files(os.path.join(a.kc_dir, "storage", "profiles"))
            changed = cfg.change_scale(a.set_scale)
            print("temperature unit:", a.set_scale, "| converted:", changed or "nothing (already set)")
        if a.show_config: print(json.dumps(cfg.read(), indent=1))
        return
    if a.test:
        n = Notifier(load_json(settings, {})); n.send("Kiln Helper test", "Alerts are working!", tags="fire"); time.sleep(5); return
    helper = KilnHelper(settings, a.kc_dir)
    srv = serve(helper)
    print(f"Kiln Helper on port {helper.S['gateway_port']}, kiln-controller at 127.0.0.1:{helper.S['engine_port']}, "
          f"safety relay {'fitted' if helper.safety.fitted else 'NOT fitted'}", flush=True)
    srv.serve_forever()

if __name__ == "__main__":
    main()
