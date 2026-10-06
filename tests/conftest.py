"""Shared test pieces: a fake kiln-controller engine, a fake relay, and a helper built around them.
Nothing here touches real hardware."""
import copy, json, os, shutil, sys, threading, time
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "software"))
import kiln_helper as kh  # noqa: E402

# The pinned kiln-controller's own config.py (copied from upstream a2b3071) so unit tests use the real file layout.
PINNED_CONFIG = os.path.join(ROOT, "tests", "data", "config.py")


class FakeRelay:
    def __init__(self, pin, active_low):
        self.pin, self.active_low, self.value = pin, active_low, False
    def on(self): self.value = True
    def off(self): self.value = False


class RecordingNotifier:
    def __init__(self): self.sent = []
    def send(self, title, message, priority="default", tags=""): self.sent.append((title, message, priority))
    def titles(self): return [t for t, _, _ in self.sent]


class FakeEngine:
    """Behaves like kiln-controller's /api and /storage, and pushes status messages into the helper.
    stop_mode: "ok" | "raise" (can't reach it) | "ignore" (accepts but keeps heating)"""
    def __init__(self):
        self.helper = None
        self.store = {}
        self.calls = []
        self.state, self.profile, self.temp, self.runtime, self.totaltime = "IDLE", None, 70.0, 0, 0
        self.stop_mode, self.run_mode = "ok", "ok"

    def add(self, name, data, **extra):
        self.store[name] = dict(type="profile", name=name, data=[list(x) for x in data], **extra)

    def status(self, **over):
        x = {"state": self.state, "temperature": self.temp, "target": self.temp, "profile": self.profile,
             "runtime": self.runtime, "totaltime": self.totaltime, "pidstats": {"out": 0.5}}
        x.update(over)
        return x

    def emit(self, **over):
        self.helper.on_message(self.status(**over))

    # ---- engine API ----
    def api(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd == "stop":
            if self.stop_mode == "raise": raise ConnectionError("connection refused")
            if self.stop_mode == "ignore": return {"success": True}
            self.state, self.profile = "IDLE", None
            self.emit(); return {"success": True}
        if cmd == "run":
            if self.run_mode == "raise": raise ConnectionError("connection refused")
            name = kw["profile"]
            if name not in self.store: return {"success": False, "error": "not found"}
            if self.run_mode == "ignore": return {"success": True}
            p = self.store[name]
            self.state, self.profile = "RUNNING", name
            self.runtime, self.totaltime = kw.get("startat", 0) * 60, p["data"][-1][0]
            self.emit(); return {"success": True}
        return {"success": True}

    def profiles(self):
        return copy.deepcopy(list(self.store.values()))

    def put_profile(self, p):
        assert "temp_units" not in p, "Kiln Helper must let the engine convert units"
        self.calls.append(("put", p["name"]))
        self.store[p["name"]] = copy.deepcopy(p)

    def delete_profile(self, name):
        self.calls.append(("delete", name))
        self.store.pop(name, None)

    def runs(self):
        return [kw["profile"] for c, kw in self.calls if c == "run"]


def make_helper(tmp_path, settings=None, protect=None, engine=None, relay=True, extra_files=None):
    kc = tmp_path / "kc"
    (kc / "storage" / "profiles").mkdir(parents=True, exist_ok=True)
    shutil.copy(PINNED_CONFIG, kc / "config.py")
    s = {"topic": "", "safety_relay_pin": 24 if relay else None,
         "stop_cmd": ["true"], "start_cmd": ["true"], "restart_cmd": ["true"],
         "box_temp_file": str(tmp_path / "no-such-file")}
    s.update(settings or {})
    (kc / "kiln-helper.json").write_text(json.dumps(s))
    if protect is not None: (kc / "kiln-protect.json").write_text(json.dumps(protect))
    for name, value in (extra_files or {}).items(): (kc / name).write_text(json.dumps(value))
    engine = engine or FakeEngine()
    h = kh.KilnHelper(str(kc / "kiln-helper.json"), str(kc), engine=engine, relay_factory=FakeRelay,
                      notifier=RecordingNotifier(), start_threads=False)
    engine.helper = h
    h.STOP_ACK_S = h.START_ACK_S = 0.5
    return h, engine


@pytest.fixture
def helper(tmp_path):
    h, e = make_helper(tmp_path)
    e.add("glaze-06", [[0, 70], [3600, 1000], [7200, 1830]])
    e.emit()                          # the engine is connected and idle
    return h, e
