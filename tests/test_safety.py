"""STOP, automatic stops, the safety relay, lost contact and bad readings (simulated hardware only)."""
import socket, threading, time
import kiln_helper as kh
from conftest import make_helper, FakeEngine


def start(h, e, name="glaze-06"):
    h.start(name)
    assert e.state == "RUNNING"


# ---------- STOP ----------
def test_stop_is_confirmed_by_the_engine(helper):
    h, e = helper
    start(h, e)
    r = h.stop()
    assert r["acknowledged"] and not r["hardware_cut"]
    assert h.safety.on, "a confirmed stop must not cut the power"


def test_stop_that_cant_reach_the_engine_cuts_the_relay(helper):
    h, e = helper
    start(h, e)
    e.stop_mode = "raise"
    r = h.stop()
    assert not r["acknowledged"] and r["hardware_cut"]
    assert not h.safety.on
    assert h.protect["safety_cut"]["code"] == "STOP"
    assert "STOP NOT CONFIRMED" in h.notify.titles()


def test_stop_that_the_engine_ignores_cuts_the_relay(helper):
    h, e = helper
    start(h, e)
    e.stop_mode = "ignore"
    t = time.time()
    r = h.stop()
    assert not r["acknowledged"] and r["hardware_cut"] and not h.safety.on
    assert time.time() - t < 3


def test_stop_without_a_relay_says_no_hardware_cutoff(tmp_path):
    h, e = make_helper(tmp_path, relay=False)
    e.add("glaze-06", [[0, 70], [3600, 1000]]); e.emit()
    start(h, e)
    e.stop_mode = "raise"
    r = h.stop()
    assert not r["acknowledged"] and not r["hardware_cut"] and not r["hardware_available"]
    msg = [m for t, m, _ in h.notify.sent if t == "STOP NOT CONFIRMED"][0]
    assert "NO hardware cutoff" in msg and "breaker" in msg


def test_cut_stays_cut_after_a_restart_until_reset(tmp_path):
    h, e = make_helper(tmp_path, protect={"pin": "1234", "safety_cut": {"code": "E4", "at": 1}})
    assert not h.safety.on, "the relay must start OPEN while a cut is waiting for a reset"
    e.add("glaze-06", [[0, 70], [3600, 1000]]); e.emit()
    try:
        h.start("glaze-06", pin="1234"); assert False
    except kh.Refused as x:
        assert x.kind == "busy"
    h.safety_reset(pin="1234")
    assert h.safety.on


def test_relay_starts_closed_normally(tmp_path):
    h, _ = make_helper(tmp_path)
    assert h.safety.on and h.safety.dev.active_low


def test_slow_phone_alerts_never_delay_a_stop(tmp_path):
    # an alert server that accepts the connection and then never answers
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5)
    port = srv.getsockname()[1]
    hold = []
    threading.Thread(target=lambda: [hold.append(srv.accept()) for _ in range(5)], daemon=True).start()
    h, e = make_helper(tmp_path)
    h.notify = kh.Notifier({"topic": "t", "server": f"http://127.0.0.1:{port}"})
    e.add("glaze-06", [[0, 70], [3600, 1000]]); e.emit()
    start(h, e)
    for _ in range(3): h.notify.send("x", "y")       # these hang in the background
    e.stop_mode = "raise"
    t = time.time()
    r = h.stop()
    assert r["hardware_cut"] and time.time() - t < 2


# ---------- automatic stops ----------
def test_auto_stop_falls_back_to_the_relay(helper):
    h, e = helper
    start(h, e)
    e.stop_mode = "raise"
    h.auto_stop("E2")
    for _ in range(50):
        if h.last_error: break
        time.sleep(0.05)
    assert h.last_error["code"] == "E2"
    assert h.last_stop["hardware_cut"] and not h.safety.on


def test_bad_readings_stop_the_firing(helper):
    h, e = helper
    start(h, e)
    h.BAD_TEMP_S = 0
    e.emit(temperature=None)
    time.sleep(0.01)
    e.emit(temperature=None)
    for _ in range(50):
        if h.last_error: break
        time.sleep(0.05)
    assert h.last_error["code"] == "E3" and e.state == "IDLE"


def test_heating_while_off_cuts_the_power(helper):
    h, e = helper
    for t in (100, 140, 170, 200):
        e.temp = t; e.emit()
    assert h.last_error["code"] == "E4" and not h.safety.on


def test_lost_engine_during_a_firing_stops_or_cuts(helper):
    h, e = helper
    start(h, e)
    e.stop_mode = "raise"                  # the engine has gone quiet and can't be reached
    h.status_at -= h.LOST_AFTER_S + 1
    h.tick()
    for _ in range(60):
        if h.last_error: break
        time.sleep(0.05)
    assert h.last_error["code"] == "E7"
    assert h.last_stop["hardware_cut"] and not h.safety.on
    assert h.history[0]["result"] == "stopped"


def test_stale_status_blocks_starting(helper):
    h, e = helper
    h.status_at -= h.STATUS_STALE_S + 1
    try:
        h.start("glaze-06"); assert False
    except kh.Refused as x:
        assert "can't hear" in x.message
    assert e.runs() == []


def test_start_not_confirmed_is_stopped(helper):
    h, e = helper
    e.run_mode = "ignore"
    try:
        h.start("glaze-06"); assert False
    except kh.Refused as x:
        assert "didn't confirm" in x.message
    assert ("stop", {}) in e.calls
