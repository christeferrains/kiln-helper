#!/usr/bin/env bash
# Kiln Helper installer
# Sets up kiln-controller (the tested engine by jbruce12000) plus Kiln Helper's screen and service
# on a Raspberry Pi running Raspberry Pi OS (Bookworm). Run it as your normal user, not root:
#
#   git clone https://github.com/christeferrains/kiln-helper.git
#   cd kiln-helper
#   ./install.sh            # practice mode: the kiln is NOT switched (safe to try)
#   ./install.sh --real     # when the controller box is built and tested: really switch the kiln
#
# Other options:
#   --celsius         show temperatures in °C (default °F)
#   --120v            for a 120 V kiln (default 240 V; used by the optional element test)
#   --kiosk           open Kiln Helper full-screen on the Pi's touchscreen at startup
#   --keep-hostname   don't rename the Pi to "kiln" (the phone address is then http://<its-name>.local:8081)
#   --dry-run         only print what would happen
#
# Free software under the GNU GPL v3. NO WARRANTY. Kilns run on dangerous mains power:
# read docs/build-guide.md and have an electrician check your wiring.
set -euo pipefail

KILN_CONTROLLER_REPO="https://github.com/jbruce12000/kiln-controller.git"
KILN_CONTROLLER_COMMIT="a2b3071e4e55f47c20326563200da0b49d3c5bb8"   # the version Kiln Helper was tested with
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KC="$HOME/kiln-controller"
REAL=0; CELSIUS=0; KIOSK=0; KEEP_HOSTNAME=0; DRY=0; VOLTS=240
for a in "$@"; do
  case "$a" in
    --real) REAL=1 ;;
    --celsius) CELSIUS=1 ;;
    --120v) VOLTS=120 ;;
    --kiosk) KIOSK=1 ;;
    --keep-hostname) KEEP_HOSTNAME=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n 2,20p "$0"; exit 0 ;;
    *) echo "Unknown option: $a (try --help)"; exit 1 ;;
  esac
done

say()  { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then echo "   [dry-run] $*"; else eval "$@"; fi; }

if [ "$(id -u)" = 0 ]; then echo "Please run this as your normal user (not with sudo)."; exit 1; fi
for f in software/index.html software/kiln-helper.py software/alerts.json; do
  [ -f "$HERE/$f" ] || { echo "Missing $f. Run install.sh from inside the kiln-helper folder."; exit 1; }
done

say "1/8 Installing system packages"
run "sudo apt-get update -y"
run "sudo apt-get install -y git python3-venv python3-pip"
# ready-made GPIO library for the optional relays (Raspberry Pi OS package; nothing to compile)
run "sudo apt-get install -y python3-lgpio || true"

say "2/8 Getting kiln-controller (the engine)"
if [ -d "$KC/.git" ]; then
  echo "   kiln-controller is already in $KC. Leaving it as it is."
else
  run "git clone $KILN_CONTROLLER_REPO \"$KC\""
  run "git -C \"$KC\" checkout -q $KILN_CONTROLLER_COMMIT"
fi

say "3/8 Installing Python parts (this can take 10+ minutes on a Pi)"
run "python3 -m venv --system-site-packages \"$KC/venv\""   # can use the system's lgpio
run "\"$KC/venv/bin/pip\" install --upgrade pip"
run "\"$KC/venv/bin/pip\" install -r \"$KC/requirements.txt\""
run "\"$KC/venv/bin/pip\" install websocket-client"
# optional extras (relays, power sensor): a problem here must not stop the install
run "\"$KC/venv/bin/pip\" install gpiozero adafruit-circuitpython-ads1x15 || echo \"   (optional relay/sensor parts did not install; Kiln Helper still works without them)\""

say "4/8 Turning on the Pi's SPI (thermocouple board) and I2C (optional power sensor)"
if command -v raspi-config >/dev/null; then
  run "sudo raspi-config nonint do_spi 0"
  run "sudo raspi-config nonint do_i2c 0"
else
  echo "   raspi-config not found (not a Raspberry Pi?). Skipping."
fi

say "5/8 Setting up kiln-controller for Kiln Helper"
CFG="$KC/config.py"
if [ "$DRY" = 0 ]; then
  [ -f "$CFG.original" ] || cp "$CFG" "$CFG.original"            # keep the original, just in case
  sed -i -E 's/^max31855 *= *[0-9]+/max31855 = 0/; s/^max31856 *= *[0-9]+/max31856 = 1/' "$CFG"
  if [ "$CELSIUS" = 1 ]; then sed -i -E 's/^(temp_scale *= *)"[fc]"/\1"c"/' "$CFG"; else sed -i -E 's/^(temp_scale *= *)"[fc]"/\1"f"/' "$CFG"; fi
  if [ "$REAL" = 1 ]; then
    sed -i -E 's/^simulate *= *True/simulate = False/' "$CFG"
  else
    sed -i -E 's/^simulate *= *False/simulate = True/' "$CFG"
  fi
fi
echo "   thermocouple board: MAX31856 · scale: $([ "$CELSIUS" = 1 ] && echo °C || echo °F) · $([ "$REAL" = 1 ] && echo 'REAL kiln' || echo 'practice mode (kiln not switched)')"

say "6/8 Installing Kiln Helper's screen and service"
if [ "$DRY" = 0 ]; then
  if [ -f "$KC/public/index.html" ] && ! grep -q "Kiln Helper" "$KC/public/index.html"; then
    mv "$KC/public/index.html" "$KC/public/old.html"             # the original screen stays at /picoreflow/old.html
  fi
  install -m 644 "$HERE/software/index.html" "$KC/public/index.html"      # install, not cp: always writable, safe to re-run
  install -m 644 "$HERE/software/kiln-helper.py" "$KC/kiln-helper.py"
  if [ ! -f "$KC/public/alerts.json" ]; then
    TOPIC="kiln-helper-$(python3 -c 'import secrets; print(secrets.token_hex(5))')"   # a private alert name nobody can guess
    sed "s/CHANGE-ME-to-something-only-you-know/$TOPIC/" "$HERE/software/alerts.json" > "$KC/public/alerts.json"
  fi
  if [ "$CELSIUS" = 1 ]; then sed -i -E 's/"temp_scale": *"[fc]"/"temp_scale": "c"/' "$KC/public/alerts.json"; fi
  if grep -q '"supply_volts"' "$KC/public/alerts.json"; then
    sed -i -E "s/\"supply_volts\": *[0-9]+/\"supply_volts\": $VOLTS/" "$KC/public/alerts.json"
  fi
  mkdir -p "$KC/storage/profiles"
fi

say "7/8 Starting both at power-on"
SERVICE_KC="[Unit]
Description=kiln-controller
After=network-online.target

[Service]
ExecStart=$KC/venv/bin/python $KC/kiln-controller.py
WorkingDirectory=$KC
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target"
SERVICE_KH="[Unit]
Description=Kiln Helper service (alerts, auto-shutoff, delay start, history)
After=network-online.target kiln-controller.service
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$KC
ExecStart=$KC/venv/bin/python $KC/kiln-helper.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target"
# Kiln Helper may stop/start/restart kiln-controller (autotune, settings) without a password, and nothing else.
SUDOERS="$USER ALL=(root) NOPASSWD: /usr/bin/systemctl stop kiln-controller, /usr/bin/systemctl start kiln-controller, /usr/bin/systemctl restart kiln-controller"
if [ "$DRY" = 1 ]; then
  echo "   [dry-run] would write /etc/systemd/system/kiln-controller.service and kiln-helper.service"
  echo "   [dry-run] would write /etc/sudoers.d/kiln-helper: $SUDOERS"
else
  echo "$SERVICE_KC" | sudo tee /etc/systemd/system/kiln-controller.service >/dev/null
  echo "$SERVICE_KH" | sudo tee /etc/systemd/system/kiln-helper.service >/dev/null
  echo "$SUDOERS" | sudo tee /etc/sudoers.d/kiln-helper >/dev/null
  sudo chmod 440 /etc/sudoers.d/kiln-helper
  sudo visudo -cf /etc/sudoers.d/kiln-helper >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now kiln-controller kiln-helper
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
Exec=sh -c 'sleep 8; $BROWSER --kiosk --noerrdialogs --disable-infobars --incognito http://localhost:8081'"
  if [ "$DRY" = 1 ]; then echo "   [dry-run] would write ~/.config/autostart/kiln-helper.desktop"; else echo "$KIOSK_FILE" > "$HOME/.config/autostart/kiln-helper.desktop"; fi
  echo "   The touchscreen opens Kiln Helper full-screen after the next restart."
fi

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
ADDR="${IP:-the-Pi-address}"
echo
echo "  ✓ Kiln Helper is installed."
echo
echo "  Open it on a phone or computer on the same Wi-Fi:"
echo "      http://$NAME.local:8081      (or  http://$ADDR:8081)"
[ "$RENAMED" = 1 ] && echo "  The Pi is now called \"kiln\". Restart it once (sudo reboot) so the new name works."
echo
if [ "$REAL" = 1 ]; then
  echo "  REAL MODE: the kiln WILL be switched. Watch your first firings."
else
  echo "  PRACTICE MODE: nothing is switched yet. When the box is built and checked, run:  ./install.sh --real"
fi
echo
echo "  Phone alerts: install the free \"ntfy\" app and subscribe to the name shown in"
echo "  Kiln Helper → ⚙ Settings → Phone & alerts."
echo
