#!/usr/bin/env bash
# Kiln Helper installer
# One command installs EVERYTHING: kiln-controller (the tested engine by jbruce12000, downloaded
# automatically) plus Kiln Helper's screen and service, on a Raspberry Pi running Raspberry Pi OS (Bookworm).
# Run it as your normal user, not root:
#
#   git clone https://github.com/christeferrains/kiln-helper.git
#   cd kiln-helper
#   ./install.sh            # practice mode: the kiln is NOT switched (safe to try)
#   ./install.sh --real     # when the controller box is built and checked: really switch the kiln
#
# Running it again is safe. Anything you don't ask to change stays as it was (°F/°C, real/practice, volts).
# It refuses to change anything while a firing, autotune or element test is running.
#
# Options:
#   --real | --practice        switch the kiln for real / practice mode (first install: practice)
#   --celsius | --fahrenheit   temperature unit; every temperature setting is converted (first install: °F)
#   --120v | --240v            the kiln's supply, used by the optional element test (first install: 240 V)
#   --kiosk                    open Kiln Helper full-screen on the Pi's touchscreen at startup
#   --keep-hostname            don't rename the Pi to "kiln" (the phone address is then http://<its-name>.local:8081)
#   --dry-run                  only print what would happen
#
# Free software under the GNU GPL v3. NO WARRANTY. Kilns run on dangerous mains power:
# read docs/build-guide.md and have an electrician check your wiring.
set -euo pipefail

KILN_CONTROLLER_REPO="https://github.com/jbruce12000/kiln-controller.git"
KILN_CONTROLLER_COMMIT="a2b3071e4e55f47c20326563200da0b49d3c5bb8"   # the version Kiln Helper was tested with
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KC="${KILN_HELPER_KC:-$HOME/kiln-controller}"
GATEWAY_PORT=8081      # Kiln Helper: the only thing on the network
ENGINE_PORT=8091       # kiln-controller: only reachable from the Pi itself (127.0.0.1)
MODE=""; SCALE=""; VOLTS=""; KIOSK=0; KEEP_HOSTNAME=0; DRY=0
for a in "$@"; do
  case "$a" in
    --real) MODE=real ;;
    --practice) MODE=practice ;;
    --celsius) SCALE=c ;;
    --fahrenheit) SCALE=f ;;
    --120v) VOLTS=120 ;;
    --240v) VOLTS=240 ;;
    --kiosk) KIOSK=1 ;;
    --keep-hostname) KEEP_HOSTNAME=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n 2,26p "$0"; exit 0 ;;
    *) echo "Unknown option: $a (try --help)"; exit 1 ;;
  esac
done

say()  { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then echo "   [dry-run] $*"; else eval "$@"; fi; }
die()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

if [ "$(id -u)" = 0 ]; then die "Please run this as your normal user (not with sudo)."; fi
for f in software/index.html software/kiln_helper.py software/kiln-helper.json; do
  [ -f "$HERE/$f" ] || die "Missing $f. Run install.sh from inside the kiln-helper folder."
done

# ---- never touch a kiln that is heating ----
firing_active() {
  python3 - "$KC" "$GATEWAY_PORT" <<'PY'
import json, os, sys, time, urllib.request
kc, port = sys.argv[1], sys.argv[2]
try:   # new Kiln Helper
    j = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=3))
    if isinstance(j, dict) and (j.get("kiln_state") in ("RUNNING", "PAUSED") or j.get("op")):
        print(j.get("op") or "a firing"); sys.exit(0)
except Exception:
    pass
p = os.path.join(kc, "state.json")   # kiln-controller writes this every few seconds while firing
try:
    if time.time() - os.path.getmtime(p) < 120 and json.load(open(p)).get("state") in ("RUNNING", "PAUSED"):
        print("a firing"); sys.exit(0)
except Exception:
    pass
PY
  pgrep -f "kiln-tuner\.py" >/dev/null 2>&1 && echo "autotune" || true
}
BUSY="$(firing_active)"
if [ -n "$BUSY" ]; then
  die "The kiln is busy ($BUSY). Nothing was changed. Run this again when it has finished and cooled."
fi

# ---- what's set now (so a re-run keeps it) ----
CFG="$KC/config.py"; SETTINGS="$KC/kiln-helper.json"
CUR_SCALE="$(sed -nE 's/^temp_scale *= *"([fc])".*/\1/p' "$CFG" 2>/dev/null | head -1)"
CUR_SIM="$(sed -nE 's/^simulate *= *(True|False).*/\1/p' "$CFG" 2>/dev/null | head -1)"
FIRST=0; [ -f "$KC/kiln_helper.py" ] || [ -f "$KC/kiln-helper.py" ] || FIRST=1
[ -n "$MODE" ]  || { if [ "$FIRST" = 0 ] && [ "$CUR_SIM" = "False" ]; then MODE=real; else MODE=practice; fi; }
[ -n "$SCALE" ] || { if [ "$FIRST" = 0 ] && [ -n "$CUR_SCALE" ]; then SCALE="$CUR_SCALE"; else SCALE=f; fi; }

SKIP_PACKAGES="${KILN_HELPER_SKIP_PACKAGES:-0}"   # for the automatic tests / offline re-runs only
say "1/8 Installing system packages"
if [ "$SKIP_PACKAGES" = 1 ]; then echo "   skipped (KILN_HELPER_SKIP_PACKAGES=1)"; else
run "sudo apt-get update -y"
run "sudo apt-get install -y git python3-venv python3-pip"
# ready-made GPIO library for the optional safety relay (Raspberry Pi OS package; nothing to compile)
run "sudo apt-get install -y python3-lgpio || true"
fi

say "2/8 Getting kiln-controller (the engine, downloaded for you)"
if [ -f "$KC/kiln-controller.py" ]; then
  HEAD="$(git -C "$KC" rev-parse HEAD 2>/dev/null || echo "an unknown version")"
  if [ "$HEAD" != "$KILN_CONTROLLER_COMMIT" ]; then
    echo "   ⚠ $KC is at $HEAD, not the tested version $KILN_CONTROLLER_COMMIT."
    echo "     Kiln Helper was only tested with that version. To use it: git -C $KC checkout $KILN_CONTROLLER_COMMIT"
  else
    echo "   kiln-controller (tested version) is already in $KC."
  fi
else
  run "git clone $KILN_CONTROLLER_REPO \"$KC\""
  run "git -C \"$KC\" checkout -q $KILN_CONTROLLER_COMMIT"
fi

say "3/8 Installing Python parts (this can take 10+ minutes on a Pi)"
if [ "$SKIP_PACKAGES" = 1 ]; then echo "   skipped (KILN_HELPER_SKIP_PACKAGES=1)"; else
run "python3 -m venv --system-site-packages \"$KC/venv\""   # can use the system's lgpio
run "\"$KC/venv/bin/pip\" install --upgrade pip"
run "\"$KC/venv/bin/pip\" install -r \"$KC/requirements.txt\""
run "\"$KC/venv/bin/pip\" install websocket-client"
# optional extras (safety relay, power sensor): a problem here must not stop the install
run "\"$KC/venv/bin/pip\" install gpiozero adafruit-circuitpython-ads1x15 || echo \"   (optional relay/sensor parts did not install; Kiln Helper still works without them)\""
fi

say "4/8 Turning on the Pi's SPI (thermocouple board) and I2C (optional power sensor)"
if command -v raspi-config >/dev/null; then
  run "sudo raspi-config nonint do_spi 0"
  run "sudo raspi-config nonint do_i2c 0"
else
  echo "   raspi-config not found (not a Raspberry Pi?). Skipping."
fi

say "5/8 Setting up kiln-controller for Kiln Helper"
if [ "$DRY" = 0 ]; then
  [ -f "$CFG.original" ] || cp "$CFG" "$CFG.original"            # keep the original, just in case
  sed -i -E 's/^max31855 *= *[0-9]+/max31855 = 0/; s/^max31856 *= *[0-9]+/max31856 = 1/' "$CFG"
  sed -i -E "s/^listening_port *= *[0-9]+/listening_port = $ENGINE_PORT/" "$CFG"
  grep -qE "^listening_port *= *$ENGINE_PORT" "$CFG" || die "Couldn't set listening_port in $CFG"
  # The engine must only listen on the Pi itself, so every command passes Kiln Helper's checks (PIN, limits).
  sed -i -E 's/^( *ip *= *)"0\.0\.0\.0"/\1"127.0.0.1"/' "$KC/kiln-controller.py"
  grep -qE '^ *ip *= *"127\.0\.0\.1"' "$KC/kiln-controller.py" || die "Couldn't make kiln-controller listen only on 127.0.0.1. Is it the tested version?"
  if [ "$MODE" = real ]; then
    sed -i -E 's/^simulate *= *True/simulate = False/' "$CFG"
  else
    sed -i -E 's/^simulate *= *False/simulate = True/' "$CFG"
  fi
fi
echo "   thermocouple board: MAX31856 · $([ "$MODE" = real ] && echo 'REAL kiln' || echo 'practice mode (kiln not switched)')"

say "6/8 Installing Kiln Helper's screen and service"
if [ "$DRY" = 0 ]; then
  if [ -f "$KC/public/index.html" ] && ! grep -q "Kiln Helper" "$KC/public/index.html"; then
    mv "$KC/public/index.html" "$KC/public/old.html"             # the original screen, kept for reference
  fi
  install -m 644 "$HERE/software/index.html" "$KC/public/index.html"      # install, not cp: always writable, safe to re-run
  install -m 644 "$HERE/software/kiln_helper.py" "$KC/kiln_helper.py"
  rm -f "$KC/kiln-helper.py"                                     # the old service (replaced)
  mkdir -p "$KC/storage/profiles"
  # Settings live next to kiln-controller, NOT in public/ (anything in public/ could be read by anyone on the Wi-Fi).
  if [ ! -f "$SETTINGS" ]; then
    if [ -f "$KC/public/alerts.json" ]; then
      SRC="$KC/public/alerts.json"                               # moving from an older Kiln Helper
    else
      SRC="$HERE/software/kiln-helper.json"
    fi
    python3 - "$SRC" "$SETTINGS" <<'PY'
import json, secrets, sys
s = json.load(open(sys.argv[1]))
for k in ("temp_scale", "helper_port"): s.pop(k, None)          # the unit now lives only in config.py
if not s.get("topic") or s["topic"].startswith("CHANGE-ME"):
    s["topic"] = "kiln-helper-" + secrets.token_hex(5)           # a private alert name nobody can guess
json.dump(s, open(sys.argv[2], "w"), indent=1)
PY
    chmod 600 "$SETTINGS"
  fi
  rm -f "$KC/public/alerts.json"
  if [ -n "$VOLTS" ]; then
    python3 -c "import json,sys; p=sys.argv[1]; s=json.load(open(p)); s['supply_volts']=int(sys.argv[2]); json.dump(s,open(p,'w'),indent=1)" "$SETTINGS" "$VOLTS"
  fi
  # °F/°C: converts the emergency shutoff, offset, PID numbers and saved firings together (never just the label)
  "$KC/venv/bin/python" "$KC/kiln_helper.py" --kc-dir "$KC" --set-scale "$SCALE"
fi

say "7/8 Starting both at power-on"
SERVICE_KC="[Unit]
Description=kiln-controller (engine, listens on 127.0.0.1:$ENGINE_PORT only)
After=network-online.target

[Service]
ExecStart=$KC/venv/bin/python $KC/kiln-controller.py
WorkingDirectory=$KC
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"
SERVICE_KH="[Unit]
Description=Kiln Helper (screen on port $GATEWAY_PORT, PIN and limits, alerts, auto-shutoff)
After=network-online.target kiln-controller.service
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$KC
ExecStart=$KC/venv/bin/python $KC/kiln_helper.py --kc-dir $KC
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"
# Kiln Helper may stop/start/restart kiln-controller (autotune, settings) without a password, and nothing else.
SUDOERS="$USER ALL=(root) NOPASSWD: /usr/bin/systemctl stop kiln-controller, /usr/bin/systemctl start kiln-controller, /usr/bin/systemctl restart kiln-controller"
if [ "$DRY" = 1 ]; then
  echo "   [dry-run] would write /etc/systemd/system/kiln-controller.service and kiln-helper.service"
  echo "   [dry-run] would write /etc/sudoers.d/kiln-helper: $SUDOERS"
  echo "   [dry-run] would restart kiln-controller and kiln-helper so the changes take effect"
else
  echo "$SERVICE_KC" | sudo tee /etc/systemd/system/kiln-controller.service >/dev/null
  echo "$SERVICE_KH" | sudo tee /etc/systemd/system/kiln-helper.service >/dev/null
  echo "$SUDOERS" | sudo tee /etc/sudoers.d/kiln-helper >/dev/null
  sudo chmod 440 /etc/sudoers.d/kiln-helper
  sudo visudo -cf /etc/sudoers.d/kiln-helper >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable kiln-controller kiln-helper
  # "enable --now" would leave already-running services on the OLD files. Restart them, but only after
  # checking again that nothing started heating while we were installing.
  BUSY="$(firing_active)"
  if [ -n "$BUSY" ]; then
    echo "   ⚠ The kiln started ($BUSY) while installing. The new version starts after it finishes:"
    echo "     run   sudo systemctl restart kiln-controller kiln-helper   when it has cooled."
  else
    sudo systemctl restart kiln-controller
    sudo systemctl restart kiln-helper
  fi
fi

say "8/8 Finishing touches"
if [ "$KEEP_HOSTNAME" = 0 ] && command -v raspi-config >/dev/null && [ "$(hostname)" != "kiln" ]; then
  run "sudo raspi-config nonint do_hostname kiln"
  NAME="kiln"; RENAMED=1
else
  NAME="$(hostname)"; RENAMED=0
fi
if [ "$KIOSK" = 1 ]; then
  BROWSER="$(command -v chromium-browser || command -v chromium || true)"
  [ -n "$BROWSER" ] || run "sudo apt-get install -y chromium-browser"
  BROWSER="$(command -v chromium-browser || command -v chromium || echo chromium-browser)"
  run "mkdir -p \"$HOME/.config/autostart\""
  KIOSK_FILE="[Desktop Entry]
Type=Application
Name=Kiln Helper
Exec=sh -c 'sleep 8; $BROWSER --kiosk --noerrdialogs --disable-infobars --incognito http://localhost:$GATEWAY_PORT'"
  if [ "$DRY" = 1 ]; then echo "   [dry-run] would write ~/.config/autostart/kiln-helper.desktop"; else echo "$KIOSK_FILE" > "$HOME/.config/autostart/kiln-helper.desktop"; fi
  echo "   The touchscreen opens Kiln Helper full-screen after the next restart."
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
ADDR="${IP:-the-Pi-address}"
echo
echo "  ✓ Kiln Helper is installed."
echo
echo "  Open it on a phone or computer on the same Wi-Fi:"
echo "      http://$NAME.local:$GATEWAY_PORT      (or  http://$ADDR:$GATEWAY_PORT)"
[ "$RENAMED" = 1 ] && echo "  The Pi is now called \"kiln\". Restart it once (sudo reboot) so the new name works."
echo "  Temperatures: $([ "$SCALE" = c ] && echo °C || echo °F)"
echo
if [ "$MODE" = real ]; then
  echo "  REAL MODE: the kiln WILL be switched. Watch your first firings."
else
  echo "  PRACTICE MODE: nothing is switched yet. When the box is built and checked, run:  ./install.sh --real"
fi
echo
echo "  Phone alerts: install the free \"ntfy\" app and subscribe to the name shown in"
echo "  Kiln Helper → ⚙ Settings → Phone & alerts."
echo
