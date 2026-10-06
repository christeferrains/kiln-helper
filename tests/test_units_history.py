"""°F/°C conversion, saved firings, alarms, history and recovery after a restart."""
import json, os, shutil, time
import pytest
import kiln_helper as kh
from conftest import make_helper, PINNED_CONFIG, FakeEngine


def cfg_copy(tmp_path):
    p = tmp_path / "config.py"; shutil.copy(PINNED_CONFIG, p)
    return kh.KilnConfig(str(p))


def test_switching_to_celsius_converts_every_temperature_setting(tmp_path):
    c = cfg_copy(tmp_path)
    before = c.read()
    assert before["temp_scale"] == "f" and before["emergency_shutoff_temp"] == 2264
    c.write(numbers={"thermocouple_offset": 18})
    c.change_scale("c")
    after = c.read()
    assert after["temp_scale"] == "c"
    assert after["emergency_shutoff_temp"] == pytest.approx(1240, abs=0.01)      # an absolute temperature
    assert after["thermocouple_offset"] == pytest.approx(10, abs=0.01)           # a difference: ×5/9, no -32
    assert after["pid_control_window"] == pytest.approx(5 * 5 / 9, abs=0.01)
    assert after["throttle_below_temp"] == pytest.approx((300 - 32) * 5 / 9, abs=0.01)
    assert after["sim_t_env"] == pytest.approx((65 - 32) * 5 / 9, abs=0.01)


def test_pid_numbers_give_the_same_heating_in_both_units(tmp_path):
    c = cfg_copy(tmp_path)
    f = c.read()
    c.change_scale("c")
    cc = c.read()
    def out(cfg, err, rate, dt=2.0):            # kiln-controller's PID: kp*e + sum(e*dt)/ki + kd*de/dt
        return cfg["pid_kp"] * err + err * dt / cfg["pid_ki"] + cfg["pid_kd"] * rate
    err_f, rate_f = 9.0, 0.9
    assert out(f, err_f, rate_f) == pytest.approx(out(cc, err_f * 5 / 9, rate_f * 5 / 9), rel=1e-4)


def test_round_trip_and_rerun_dont_drift(tmp_path):
    c = cfg_copy(tmp_path)
    start = c.read()
    c.change_scale("c"); c.change_scale("c")      # running the installer again with --celsius changes nothing more
    c.change_scale("f"); c.change_scale("f")
    end = c.read()
    for k in ("emergency_shutoff_temp", "thermocouple_offset", "pid_kp", "pid_ki", "pid_kd", "pid_control_window"):
        assert end[k] == pytest.approx(start[k], rel=1e-3), k


def test_old_fahrenheit_profile_files_are_fixed(tmp_path):
    d = tmp_path / "profiles"; d.mkdir()
    (d / "a.json").write_text(json.dumps({"name": "a", "type": "profile", "temp_units": "f", "data": [[0, 212], [60, 1832]]}))
    (d / "b.json").write_text(json.dumps({"name": "b", "type": "profile", "temp_units": "c", "data": [[0, 20], [60, 1000]]}))
    assert kh.normalize_profile_files(str(d)) == ["a"]
    a = json.loads((d / "a.json").read_text())
    assert a["temp_units"] == "c" and a["data"][0][1] == pytest.approx(100) and a["data"][1][1] == pytest.approx(1000)
    assert json.loads((d / "b.json").read_text())["data"][1][1] == 1000


def test_unit_change_from_the_screen_converts_settings_and_alarm(helper):
    h, e = helper
    h.set_alarm(1000)
    h.kiln_settings({"temp_scale": "c", "offset": 9})          # offset typed in the CURRENT unit (°F)
    cfg = h.config.read()
    assert cfg["temp_scale"] == "c"
    assert cfg["thermocouple_offset"] == pytest.approx(5)
    assert cfg["emergency_shutoff_temp"] == pytest.approx(1240, abs=0.01)
    assert h.alarm["temp"] == pytest.approx(537.8, abs=0.1) and h.alarm["unit"] == "°C"
    assert h.restart_pending


def test_limits_use_the_right_unit_in_celsius(tmp_path):
    h, e = make_helper(tmp_path, protect={"max_f": 1900})
    h.config.change_scale("c")
    e.add("c-ok", [[0, 20], [3600, 1000]])       # 1832°F
    e.add("c-hot", [[0, 20], [3600, 1100]])      # 2012°F, over the lock
    e.emit(temperature=20)
    h.start("c-ok"); h.stop()
    with pytest.raises(kh.Refused): h.start("c-hot")


# ---------- history ----------
def run_to(h, e, runtime):
    e.runtime = runtime; e.emit()


def test_a_finished_firing_is_done(helper):
    h, e = helper
    h.start("glaze-06")
    run_to(h, e, 7190)
    e.state, e.profile = "IDLE", None; e.emit()       # the engine ended it at the end of the schedule
    assert h.history[0]["result"] == "done"
    assert "All done!" in h.notify.titles()


def test_a_stopped_firing_is_not_done(helper):
    h, e = helper
    h.start("glaze-06")
    run_to(h, e, 7190)                                # even right at the end
    h.stop()
    assert h.history[0]["result"] == "stopped" and "All done!" not in h.notify.titles()


def test_engine_ending_early_is_not_done(helper):
    h, e = helper
    h.start("glaze-06")
    run_to(h, e, 2000)
    e.state, e.profile = "IDLE", None; e.emit()       # e.g. kiln-controller's own emergency shutoff
    assert h.history[0]["result"] == "stopped"
    assert "Firing stopped early" in h.notify.titles()


def test_an_automatic_stop_is_not_done(helper):
    h, e = helper
    h.start("glaze-06")
    run_to(h, e, 7190)
    h.auto_stop("E2")
    for _ in range(40):
        if h.history: break
        time.sleep(0.05)
    assert h.history[0]["result"] == "stopped" and h.history[0]["error"] == "E2"


def test_kiln_helper_restart_keeps_the_same_firing(tmp_path):
    h, e = make_helper(tmp_path)
    e.add("glaze-06", [[0, 70], [3600, 1000], [7200, 1830]]); e.emit()
    h.start("glaze-06")
    run_to(h, e, 600)
    rec = h.current["id"]
    # Kiln Helper restarts; the engine keeps firing
    h2, _ = make_helper(tmp_path, engine=e)
    assert h2.current["id"] == rec
    run_to(h2, e, 660)
    assert h2.current["id"] == rec and "Firing started" not in h2.notify.titles()
    run_to(h2, e, 7199); e.state = "IDLE"; e.profile = None; e.emit()
    assert h2.history[0]["id"] == rec and h2.history[0]["result"] == "done"
