"""PIN, temperature limits, delayed starts and competing heating operations."""
import time
import pytest
import kiln_helper as kh
from conftest import make_helper


@pytest.fixture
def locked(tmp_path):
    h, e = make_helper(tmp_path, protect={"pin": "1234", "max_f": 1900})
    e.add("glaze-06", [[0, 70], [3600, 1000], [7200, 1830]])
    e.add("cone-6", [[0, 70], [7200, 2232]])
    e.emit()
    return h, e


def refused(fn, kind=None):
    with pytest.raises(kh.Refused) as x:
        fn()
    if kind: assert x.value.kind == kind, x.value.message
    return x.value


# ---------- PIN ----------
def test_start_needs_the_pin(locked):
    h, e = locked
    refused(lambda: h.start("glaze-06"), "pin")
    refused(lambda: h.start("glaze-06", pin="9999"), "pin")
    assert e.runs() == []
    h.start("glaze-06", pin="1234")
    assert e.runs() == ["glaze-06"]


def test_stop_never_needs_the_pin(locked):
    h, e = locked
    h.start("glaze-06", pin="1234")
    assert h.stop()["acknowledged"]


def test_delay_checks_the_pin_before_anything_else(locked):
    h, e = locked
    refused(lambda: h.schedule("glaze-06", time.time() + 3600), "pin")
    assert h.delay is None


def test_every_heating_path_needs_the_pin(locked):
    h, e = locked
    h.status["temperature"] = 70
    for fn in (lambda: h.heat_test(), lambda: h.tune_start(400), lambda: h.element_test(),
               lambda: h.adjust("skip"), lambda: h.save_profile({"name": "x", "data": [[0, 70], [60, 100]]}),
               lambda: h.kiln_settings({"offset": 5}), lambda: h.restart(), lambda: h.safety_reset()):
        refused(fn, "pin")
    assert e.runs() == [] and h.op is None


# ---------- temperature limits ----------
def test_temperature_lock_is_enforced_on_the_pi(locked):
    h, e = locked
    x = refused(lambda: h.start("cone-6", pin="1234"), "limit")
    assert "1900" in x.message
    assert e.runs() == []


def test_emergency_shutoff_is_enforced(tmp_path):
    h, e = make_helper(tmp_path)
    e.add("too-hot", [[0, 70], [3600, 2300]])     # pinned config: emergency_shutoff_temp = 2264 (°F)
    e.emit()
    refused(lambda: h.start("too-hot"), "limit")


def test_saving_a_firing_over_the_lock_is_refused(locked):
    h, _ = locked
    refused(lambda: h.save_profile({"name": "hot", "data": [[0, 70], [3600, 2000]]}, pin="1234"), "limit")


def test_bad_profile_names_are_refused(locked):
    h, e = locked
    for name in ("../../etc/x", "kh-temp", "heat-test", "A B", ""):
        refused(lambda: h.save_profile({"name": name, "data": [[0, 70], [60, 100]]}, pin="1234"), "bad")
    refused(lambda: h.delete_profile("../config", pin="1234"), "bad")
    assert ("delete", "../config") not in e.calls


def test_add_time_copy_is_checked_and_sent_without_units(locked):
    h, e = locked
    e.add("hold", [[0, 70], [3600, 1000], [5400, 1000], [9000, 1800]])
    h.start("hold", pin="1234")
    e.runtime = 4000; e.emit()
    h.adjust("add_time", pin="1234")
    assert e.runs()[-1] == "kh-temp" and e.state == "RUNNING"
    assert e.store["kh-temp"]["data"][2][0] == 5400 + 1800
    assert len(h.history) == 0 and h.current is not None, "adding time must not end the firing record"


def test_failed_add_time_leaves_the_kiln_off(locked):
    h, e = locked
    e.add("hold", [[0, 70], [3600, 1000], [5400, 1000], [9000, 1800]])
    h.start("hold", pin="1234")
    e.runtime = 4000; e.emit()
    e.run_mode = "raise"
    refused(lambda: h.adjust("add_time", pin="1234"))
    assert e.state == "IDLE" and h.history[0]["result"] == "stopped"


# ---------- delayed starts ----------
def test_delayed_start_rechecks_a_changed_firing(locked):
    h, e = locked
    h.schedule("glaze-06", time.time() + 3600, pin="1234")
    e.add("glaze-06", [[0, 70], [7200, 2100]])            # someone edited it to go hotter than the lock
    h.delay["at"] = time.time() - 1
    h.run_due_delay()
    assert e.runs() == [] and h.delay is None
    assert "Delayed firing didn't start" in h.notify.titles()


def test_delayed_start_rechecks_a_lowered_lock(locked):
    h, e = locked
    h.schedule("glaze-06", time.time() + 3600, pin="1234")
    h.set_protect({"pin": "1234", "max_f": 1500})
    h.delay["at"] = time.time() - 1
    h.run_due_delay()
    assert e.runs() == []


def test_delayed_start_runs_when_still_ok(locked):
    h, e = locked
    h.schedule("glaze-06", time.time() + 3600, pin="1234")
    h.delay["at"] = time.time() - 1
    h.run_due_delay()
    assert e.runs() == ["glaze-06"]


def test_delayed_start_waits_if_the_kiln_is_busy(locked):
    h, e = locked
    h.schedule("glaze-06", time.time() + 3600, pin="1234")
    h.delay["at"] = time.time() - 1
    h.op = "tune"
    h.run_due_delay()
    assert e.runs() == []


def test_a_deleted_scheduled_firing_is_protected(locked):
    h, _ = locked
    h.schedule("glaze-06", time.time() + 3600, pin="1234")
    refused(lambda: h.delete_profile("glaze-06", pin="1234"), "busy")


# ---------- one heating job at a time ----------
def test_no_second_firing(locked):
    h, e = locked
    h.start("glaze-06", pin="1234")
    refused(lambda: h.start("glaze-06", pin="1234"), "busy")
    refused(lambda: h.heat_test(pin="1234"), "busy")
    refused(lambda: h.tune_start(400, pin="1234"), "busy")
    refused(lambda: h.schedule("glaze-06", time.time() + 600, pin="1234"), "busy")
    refused(lambda: h.kiln_settings({"pin": "1234", "offset": 3}), "busy")
    assert e.runs() == ["glaze-06"]


def test_nothing_starts_during_autotune_or_element_test(locked):
    h, e = locked
    for op in ("tune", "element_test"):
        h.op = op
        refused(lambda: h.start("glaze-06", pin="1234"), "busy")
        refused(lambda: h.heat_test(pin="1234"), "busy")
    assert e.runs() == []


def test_nothing_starts_while_a_delay_is_waiting(locked):
    h, e = locked
    h.schedule("glaze-06", time.time() + 3600, pin="1234")
    refused(lambda: h.start("glaze-06", pin="1234"), "busy")
    h.cancel_delay()                                    # canceling needs no PIN
    h.start("glaze-06", pin="1234")


def test_racing_starts_only_start_once(locked):
    import threading
    h, e = locked
    out = []
    def go():
        try: h.start("glaze-06", pin="1234"); out.append("ok")
        except kh.Refused: out.append("no")
    ts = [threading.Thread(target=go) for _ in range(5)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert out.count("ok") == 1 and e.runs() == ["glaze-06"]


def test_nothing_starts_while_the_engine_restarts(locked):
    h, e = locked
    h.restart(pin="1234")
    refused(lambda: h.start("glaze-06", pin="1234"), "busy")
    h.conn_gen += 1; e.emit(); h.tick()               # the engine came back
    h.start("glaze-06", pin="1234")
