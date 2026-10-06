"""End-to-end with the REAL pinned kiln-controller in its simulate mode (no hardware).
Needs a kiln-controller checkout with its venv: set KC_SOURCE (default ~/kiln-controller). Skipped otherwise."""
import json, os, shutil, signal, socket, subprocess, sys, threading, time, urllib.request, urllib.error
import pytest
import kiln_helper as kh
from conftest import FakeRelay, RecordingNotifier

SRC = os.environ.get("KC_SOURCE", os.path.expanduser("~/kiln-controller"))
PIN = "a2b3071e4e55f47c20326563200da0b49d3c5bb8"
pytestmark = pytest.mark.skipif(not os.path.exists(os.path.join(SRC, "venv", "bin", "python")), reason="no kiln-controller checkout with venv")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def rig(tmp_path):
    kc = tmp_path / "kc"
    kc.mkdir()
    # the exact pinned version, untouched by anything else in the checkout
    arc = subprocess.run(["git", "-c", "safe.directory=*", "-C", SRC, "archive", PIN], check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(kc)], input=arc, check=True)
    os.symlink(os.path.join(SRC, "venv"), kc / "venv")
    eport, gport = free_port(), free_port()
    # what install.sh does to the engine
    cfg = (kc / "config.py").read_text()
    cfg = cfg.replace("listening_port = 8081", f"listening_port = {eport}")
    cfg = cfg.replace("automatic_restarts = True", "automatic_restarts = False")
    (kc / "config.py").write_text(cfg)
    src = (kc / "kiln-controller.py").read_text()
    assert 'ip = "0.0.0.0"' in src
    (kc / "kiln-controller.py").write_text(src.replace('ip = "0.0.0.0"', 'ip = "127.0.0.1"'))
    (kc / "storage" / "profiles").mkdir(parents=True, exist_ok=True)
    (kc / "kiln-helper.json").write_text(json.dumps({"engine_port": eport, "safety_relay_pin": 24, "topic": "",
        "stop_cmd": ["true"], "start_cmd": ["true"], "restart_cmd": ["true"], "box_temp_file": "/nonexistent"}))
    procs = []
    def start_engine():
        p = subprocess.Popen([str(kc / "venv" / "bin" / "python"), str(kc / "kiln-controller.py")], cwd=kc,
                             stdout=open(tmp_path / "engine.log", "a"), stderr=subprocess.STDOUT)
        procs.append(p); return p
    h = kh.KilnHelper(str(kc / "kiln-helper.json"), str(kc), relay_factory=FakeRelay, notifier=RecordingNotifier())
    srv = kh.serve(h, "127.0.0.1", gport)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield h, start_engine, f"http://127.0.0.1:{gport}", eport, kc
    srv.shutdown()
    for p in procs:
        if p.poll() is None: p.kill()


def wait(cond, s=30):
    end = time.time() + s
    while time.time() < end:
        try:
            if cond(): return True
        except Exception: pass
        time.sleep(0.2)
    return False


def post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Kiln-Helper": "1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as x:
        return x.code, json.loads(x.read())


def test_late_engine_then_run_and_confirmed_stop(rig):
    h, start_engine, url, eport, kc = rig
    # the screen comes up before the engine: nothing may start
    code, j = post(url + "/api/run", {"name": "x"})
    assert code == 409
    eng = start_engine()
    assert wait(lambda: h.fresh())
    code, j = post(url + "/api/profiles/save", {"profile": {"name": "test-fire", "data": [[0, 65], [3600, 900]]}})
    assert code == 200, j
    code, j = post(url + "/api/run", {"name": "test-fire"})
    assert code == 200, j
    assert h.engine_state() == "RUNNING"
    code, j = post(url + "/api/stop", {})
    assert j["acknowledged"] is True and j["hardware_cut"] is False
    assert h.engine_state() == "IDLE"


def test_engine_dies_during_a_firing_stop_cuts_power(rig):
    h, start_engine, url, eport, kc = rig
    eng = start_engine()
    assert wait(lambda: h.fresh())
    post(url + "/api/profiles/save", {"profile": {"name": "test-fire", "data": [[0, 65], [3600, 900]]}})
    assert post(url + "/api/run", {"name": "test-fire"})[0] == 200
    eng.send_signal(signal.SIGKILL); eng.wait()
    code, j = post(url + "/api/stop", {})
    assert j["acknowledged"] is False and j["hardware_cut"] is True and not h.safety.on


def test_engine_only_listens_on_the_pi_itself(rig):
    h, start_engine, url, eport, kc = rig
    start_engine()
    assert wait(lambda: h.fresh())
    ips = [a for a in subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split() if ":" not in a]
    if not ips: pytest.skip("no non-loopback address to test from")
    s = socket.socket(); s.settimeout(2)
    assert s.connect_ex((ips[0], eport)) != 0, "the engine must not be reachable from the network"


def test_celsius_switch_keeps_saved_firings_right(rig):
    h, start_engine, url, eport, kc = rig
    eng = start_engine()
    assert wait(lambda: h.fresh())
    assert post(url + "/api/profiles/save", {"profile": {"name": "bisque", "data": [[0, 65], [3600, 1832]]}})[0] == 200
    # an old °F-labelled file, as the original screen saved them
    (kc / "storage" / "profiles" / "old.json").write_text(json.dumps({"type": "profile", "name": "old", "temp_units": "f", "data": [[0, 70], [60, 1832]]}))
    code, j = post(url + "/api/kiln_settings", {"temp_scale": "c"})
    assert code == 200, j
    eng.kill(); eng.wait(); eng = start_engine()                  # what systemctl restart does
    assert h.restart_pending                                       # nothing may start until the engine is back
    assert post(url + "/api/run", {"name": "bisque"})[0] == 409
    assert wait(lambda: not h.restart_pending and h.fresh())
    profs = {p["name"]: p for p in h.engine.profiles()}
    assert round(max(t for _, t in profs["bisque"]["data"])) == 1000
    assert round(max(t for _, t in profs["old"]["data"])) == 1000
    assert h.config.read()["emergency_shutoff_temp"] == pytest.approx(1240, abs=0.01)
