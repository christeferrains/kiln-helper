"""install.sh re-runs: keeps settings, converts °F/°C once, applies changes, refuses during a firing.
Runs as an unprivileged user with sudo/systemctl stubbed out. Nothing is installed on the machine."""
import json, os, pwd, shutil, subprocess, sys, time
import pytest
from conftest import ROOT

SRC = os.environ.get("KC_SOURCE", os.path.expanduser("~/kiln-controller"))
PIN = "a2b3071e4e55f47c20326563200da0b49d3c5bb8"
USER = os.environ.get("KH_TEST_USER", "tester")

def have_user():
    try: pwd.getpwnam(USER); return True
    except KeyError: return False

pytestmark = [pytest.mark.skipif(os.getuid() != 0 or not have_user(), reason="needs root to run the installer as a normal test user"),
              pytest.mark.skipif(not os.path.isdir(os.path.join(SRC, ".git")), reason="no kiln-controller checkout")]

SUDO_STUB = """#!/bin/bash
echo "$*" >> "$SUDO_LOG"
case "$1" in tee) cat > /dev/null ;; esac
exit 0
"""


@pytest.fixture
def box(tmp_path):
    home = tmp_path / "home"; kc = home / "kiln-controller"; stubs = tmp_path / "stubs"
    kc.mkdir(parents=True); stubs.mkdir()
    arc = subprocess.run(["git", "-c", "safe.directory=*", "-C", SRC, "archive", PIN], check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(kc)], input=arc, check=True)
    (kc / "venv" / "bin").mkdir(parents=True)
    os.symlink(sys.executable, kc / "venv" / "bin" / "python")
    (stubs / "sudo").write_text(SUDO_STUB); (stubs / "sudo").chmod(0o755)
    repo = tmp_path / "kiln-helper"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "tests"))
    subprocess.run(["chown", "-R", USER, str(tmp_path)], check=True)
    for d in (tmp_path, tmp_path.parent, tmp_path.parent.parent):       # let the test user reach its folder
        os.chmod(d, os.stat(d).st_mode | 0o711)
    runuser = shutil.which("runuser") or "/usr/sbin/runuser"
    def run(*args):
        env = {"HOME": str(home), "PATH": f"{stubs}:/usr/local/bin:/usr/bin:/bin", "SUDO_LOG": str(tmp_path / "sudo.log"),
               "KILN_HELPER_SKIP_PACKAGES": "1", "USER": USER, "KILN_HELPER_KC": str(kc)}
        return subprocess.run([runuser, "-u", USER, "--", "bash", str(repo / "install.sh"), "--keep-hostname", *args],
                              env=env, capture_output=True, text=True, timeout=120)
    def cfg():
        t = (kc / "config.py").read_text()
        g = lambda k: [l for l in t.splitlines() if l.startswith(k)][0]
        return t, g
    return run, kc, tmp_path / "sudo.log", cfg


def test_first_install_and_reruns_keep_settings(box):
    run, kc, log, cfg = box
    r = run()
    assert r.returncode == 0, r.stdout + r.stderr
    t, g = cfg()
    assert '"f"' in g("temp_scale") and "True" in g("simulate") and "8091" in g("listening_port")
    assert 'ip = "127.0.0.1"' in (kc / "kiln-controller.py").read_text()
    s = json.loads((kc / "kiln-helper.json").read_text())
    assert s["topic"].startswith("kiln-helper-") and "temp_scale" not in s
    assert not (kc / "public" / "alerts.json").exists()
    assert "restart kiln-controller" in log.read_text(), "a re-run must actually apply the new files"

    r = run("--celsius", "--real"); assert r.returncode == 0, r.stderr
    t, g = cfg()
    assert '"c"' in g("temp_scale") and "False" in g("simulate")
    assert "1240" in g("emergency_shutoff_temp")

    r = run(); assert r.returncode == 0, r.stderr                    # no options: nothing changes back
    t, g = cfg()
    assert '"c"' in g("temp_scale") and "False" in g("simulate") and "1240" in g("emergency_shutoff_temp")

    r = run("--fahrenheit", "--practice"); assert r.returncode == 0, r.stderr
    t, g = cfg()
    assert '"f"' in g("temp_scale") and "2264" in g("emergency_shutoff_temp") and "True" in g("simulate")
    assert json.loads((kc / "kiln-helper.json").read_text())["topic"] == s["topic"], "the alert name must not change"


def test_old_install_is_migrated(box):
    run, kc, log, cfg = box
    (kc / "public" / "alerts.json").write_text(json.dumps({"topic": "my-old-topic", "temp_scale": "f", "helper_port": 8082, "safety_relay_pin": 24}))
    (kc / "kiln-helper.py").write_text("# old")
    subprocess.run(["chown", "-R", USER, str(kc)], check=True)
    r = run(); assert r.returncode == 0, r.stderr
    s = json.loads((kc / "kiln-helper.json").read_text())
    assert s["topic"] == "my-old-topic" and s["safety_relay_pin"] == 24
    assert not (kc / "public" / "alerts.json").exists() and not (kc / "kiln-helper.py").exists()
    assert oct((kc / "kiln-helper.json").stat().st_mode)[-3:] == "600"


def test_refuses_to_touch_a_firing_kiln(box):
    run, kc, log, cfg = box
    assert run().returncode == 0
    before = (kc / "config.py").read_text()
    log.write_text("")
    (kc / "state.json").write_text(json.dumps({"state": "RUNNING", "profile": "glaze"}))
    r = run("--celsius", "--real")
    assert r.returncode != 0 and "busy" in (r.stdout + r.stderr)
    assert (kc / "config.py").read_text() == before
    assert "restart" not in log.read_text()
