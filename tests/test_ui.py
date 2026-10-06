"""The real Kiln Helper screen in a headless browser, talking to the real gateway with a fake engine."""
import os, threading, time
import pytest
import kiln_helper as kh
from conftest import make_helper, ROOT

pw = pytest.importorskip("playwright.sync_api")

SETUP = "localStorage.setItem('kilnHelperSetupDone','1'); localStorage.setItem('kilnHelperClay','low');"


@pytest.fixture
def gw(tmp_path):
    h, e = make_helper(tmp_path)
    e.add("glaze-06", [[0, 70], [3600, 1000], [7200, 1830]])
    h.S["ui_file"] = os.path.join(ROOT, "software", "index.html")
    srv = kh.serve(h, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield h, e, f"http://127.0.0.1:{srv.server_address[1]}", srv
    try: srv.shutdown()
    except Exception: pass


@pytest.fixture
def page():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 420, "height": 900})
        ctx.add_init_script(SETUP)
        pg = ctx.new_page()
        yield pg
        b.close()


def test_late_engine_never_turns_into_practice_mode(gw, page):
    h, e, url, _ = gw
    page.goto(url)                                     # the engine hasn't sent anything yet
    page.wait_for_timeout(6000)                        # longer than the old 4-second fallback to practice mode
    assert page.inner_text("#connText") != "Practice"
    assert not page.is_visible("#demoNote")
    e.emit()                                           # the engine finally answers
    page.wait_for_function("document.getElementById('connText').textContent === 'Connected'", timeout=10000)
    h.start("glaze-06")                                # started elsewhere (e.g. a phone)
    page.wait_for_function("!document.getElementById('stopBtn').closest('.hidden')", timeout=10000)
    page.click("#stopBtn"); page.click("#confirmStop")
    page.wait_for_selector("#stopResult.green", timeout=10000)
    assert ("stop", {}) in e.calls, "STOP on the screen must reach the real engine"
    assert e.state == "IDLE"


def test_failed_stop_is_shown_clearly(gw, page):
    h, e, url, _ = gw
    e.emit()
    page.goto(url)
    page.wait_for_function("document.getElementById('connText').textContent === 'Connected'", timeout=10000)
    h.start("glaze-06")
    e.stop_mode = "raise"
    page.wait_for_function("!document.getElementById('stopBtn').closest('.hidden')", timeout=10000)
    page.click("#stopBtn"); page.click("#confirmStop")
    page.wait_for_selector("#stopResult.red", timeout=10000)
    assert "NOT confirmed" in page.inner_text("#stopResult")
    assert "safety relay cut the power" in page.inner_text("#stopResult")


def test_lost_pi_shows_not_connected_not_practice(gw, page):
    h, e, url, srv = gw
    e.emit()
    page.goto(url)
    page.wait_for_function("document.getElementById('connText').textContent === 'Connected'", timeout=10000)
    srv.shutdown(); srv.server_close()
    page.wait_for_function("['Not connected','No fresh reading'].includes(document.getElementById('connText').textContent)", timeout=30000)
    assert not page.is_visible("#demoNote")
    assert page.is_disabled("#startBtn")


def test_start_needs_pin_on_the_pi_even_if_the_screen_thinks_its_unlocked(gw, page):
    h, e, url, _ = gw
    e.emit()
    page.goto(url)
    page.wait_for_function("document.getElementById('connText').textContent === 'Connected'", timeout=10000)
    h.set_protect({"new_pin": "4321"})                  # PIN set from another screen a moment ago
    page.evaluate("() => { sendRun({name:'glaze-06'}); }")
    page.wait_for_selector("#pinModal.open", timeout=10000)
    assert e.runs() == []
    for d in "4321": page.click(f"#pinKeys button:text-is('{d}')")
    deadline = time.time() + 10
    while time.time() < deadline and not e.runs(): time.sleep(0.1)
    assert e.runs() == ["glaze-06"]


def test_practice_mode_only_when_asked(gw, page):
    h, e, url, _ = gw
    page.goto(url + "/picoreflow/index.html?practice=1")
    page.wait_for_function("document.getElementById('connText').textContent === 'Practice'", timeout=5000)
    assert page.is_visible("#demoNote")
    page.evaluate("sendRun({name:'x', data:[[0,70],[60,100]]})")
    page.wait_for_timeout(500)
    assert e.runs() == [], "practice mode must never reach the real kiln"


def test_screens_have_no_script_errors(gw, page):
    h, e, url, _ = gw
    errors = []
    page.on("pageerror", lambda x: errors.append(str(x)))
    e.emit()
    for u in (url, url + "/picoreflow/index.html?practice=1"):
        page.goto(u)
        page.wait_for_function("['Connected','Practice'].includes(document.getElementById('connText').textContent)", timeout=10000)
        page.click("#gearBtn"); page.wait_for_timeout(300)
        page.click("#settingsBack"); page.wait_for_timeout(300)
        page.click(".choice"); page.click("#startBtn")
        page.wait_for_selector("#startModal.open", timeout=5000)
        for c in page.query_selector_all("#checkList .check"): c.click()     # the safety checklist
        page.click("#confirmStart"); page.wait_for_timeout(1500)
        page.click("#stopBtn"); page.click("#confirmStop"); page.wait_for_timeout(1500)
    assert errors == []
    assert e.runs() == ["glaze-06"], "only the live screen reaches the engine"
