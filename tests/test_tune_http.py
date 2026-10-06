"""Autotune cancel (real processes, fake tuner) and the network gateway (real HTTP)."""
import json, os, signal, sys, textwrap, threading, time, urllib.request, urllib.error
import pytest
import kiln_helper as kh
from conftest import make_helper

CLEAN_TUNER = textwrap.dedent("""
    import sys, time, os
    open(os.environ['OUT'], 'w').write(' '.join(sys.argv[1:]))
    try:
        t = 60.0
        while True:
            print(f"stage = heating, actual = {t:.2f}, target = 400.00"); t += 1; time.sleep(0.1)
    finally:
        open(os.environ['OUT'] + '.off', 'w').write('heater off')   # like kiln-tuner's oven.output.cool(0)
""")
STUBBORN_TUNER = textwrap.dedent("""
    import os, signal, subprocess, sys, time
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    child = subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(600)'])
    open(os.environ['OUT'], 'w').write(str(child.pid))
    while True:
        print("stage = heating, actual = 100.00, target = 400.00", flush=True); time.sleep(0.1)
""")
FINISHING_TUNER = textwrap.dedent("""
    print("stage = heating, actual = 100.00, target = 400.00")
    print("pid_kp = 12.5"); print("pid_ki = 90.1"); print("pid_kd = 200.2")
""")


def tune_helper(tmp_path, script, monkeypatch):
    f = tmp_path / "tuner.py"; f.write_text(script)
    monkeypatch.setenv("OUT", str(tmp_path / "out"))
    h, e = make_helper(tmp_path, settings={"tuner_cmd": [sys.executable, str(f)]})
    h.TUNE_EXIT_WAIT_S = 2
    e.emit()
    return h, e


def wait(cond, s=10):
    end = time.time() + s
    while time.time() < end:
        if cond(): return True
        time.sleep(0.05)
    return False


def test_tune_cancel_lets_the_tuner_turn_the_heater_off(tmp_path, monkeypatch):
    h, e = tune_helper(tmp_path, CLEAN_TUNER, monkeypatch)
    h.tune_start(400)
    assert wait(lambda: h.tune.get("stage") == "heating")
    r = h.tune_cancel()
    assert r["clean"]
    assert wait(lambda: h.op is None)
    assert (tmp_path / "out.off").exists(), "the tuner's own cleanup must run"
    assert h.tune["state"] == "canceled" and h.safety.on


def test_stubborn_tuner_is_killed_with_its_children_and_power_is_cut(tmp_path, monkeypatch):
    h, e = tune_helper(tmp_path, STUBBORN_TUNER, monkeypatch)
    h.tune_start(400)
    assert wait(lambda: (tmp_path / "out").exists() and h.tune.get("stage"))
    child = int((tmp_path / "out").read_text())
    r = h.stop()                                            # the normal STOP button
    assert not r["acknowledged"] and r["hardware_cut"] and not h.safety.on
    assert wait(lambda: h.op is None)
    assert wait(lambda: not os.path.exists(f"/proc/{child}") or open(f"/proc/{child}/stat").read().split()[2] == "Z", 5)


def test_tuner_is_given_fahrenheit_even_in_celsius(tmp_path, monkeypatch):
    h, e = tune_helper(tmp_path, CLEAN_TUNER, monkeypatch)
    h.config.change_scale("c")
    e.emit(temperature=20)
    h.tune_start(204)                                       # ~400°F
    assert wait(lambda: (tmp_path / "out").exists())
    assert (tmp_path / "out").read_text().split()[-1] == "399"
    h.tune_cancel(); wait(lambda: h.op is None)


def test_finished_tune_saves_the_numbers(tmp_path, monkeypatch):
    h, e = tune_helper(tmp_path, FINISHING_TUNER, monkeypatch)
    h.tune_start(400)
    assert wait(lambda: h.op is None)
    cfg = h.config.read()
    assert h.tune["state"] == "done" and cfg["pid_kp"] == 12.5 and cfg["pid_ki"] == 90.1


def test_tune_needs_a_cool_kiln(tmp_path, monkeypatch):
    h, e = tune_helper(tmp_path, CLEAN_TUNER, monkeypatch)
    e.emit(temperature=300)
    with pytest.raises(kh.Refused): h.tune_start(400)


# ---------- the network gateway ----------
@pytest.fixture
def server(tmp_path):
    h, e = make_helper(tmp_path, protect={"pin": "1234"})
    e.add("glaze-06", [[0, 70], [3600, 1000]]); e.emit()
    ui = tmp_path / "index.html"; ui.write_text("<title>Kiln Helper</title>")
    h.S["ui_file"] = str(ui)
    srv = kh.serve(h, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield h, e, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def post(url, data, headers=None):
    hd = {"Content-Type": "application/json", "X-Kiln-Helper": "1"}
    hd.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={k: v for k, v in hd.items() if v is not None}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as x:
        return x.code, json.loads(x.read())


def test_http_start_without_pin_is_403(server):
    h, e, url = server
    code, j = post(url + "/api/run", {"name": "glaze-06"})
    assert code == 403 and j["kind"] == "pin" and e.runs() == []
    code, j = post(url + "/api/run", {"name": "glaze-06", "pin": "1234"})
    assert code == 200 and e.runs() == ["glaze-06"]


def test_http_stop_needs_no_pin_and_reports_the_result(server):
    h, e, url = server
    h.start("glaze-06", pin="1234")
    code, j = post(url + "/api/stop", {})
    assert code == 200 and j["acknowledged"] is True


def test_http_blocks_other_websites(server):
    h, e, url = server
    code, _ = post(url + "/api/stop", {}, {"X-Kiln-Helper": None})
    assert code == 403
    code, _ = post(url + "/api/run", {"name": "glaze-06", "pin": "1234"}, {"Origin": "http://evil.example"})
    assert code == 403 and e.runs() == []


def test_http_settings_file_is_not_public(server):
    h, e, url = server
    for path in ("/kiln-helper.json", "/picoreflow/alerts.json", "/picoreflow/../kiln-helper.json", "/api/control"):
        try:
            urllib.request.urlopen(url + path, timeout=5); assert False, path
        except urllib.error.HTTPError as x:
            assert x.code == 404


def test_http_events_stream_sends_status(server):
    h, e, url = server
    r = urllib.request.urlopen(url + "/api/events", timeout=5)
    line = r.readline().decode()
    assert line.startswith("data: ") and json.loads(line[6:])["type"] == "status"
    r.close()
