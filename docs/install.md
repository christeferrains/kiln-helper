# Install the software

[← Build guide](build-guide.md) · Next: [Using Kiln Helper →](using-it.md)

## 1. Prepare the Raspberry Pi

1. On your computer, download **[Raspberry Pi Imager](https://www.raspberrypi.com/software/)**.
2. Choose **Raspberry Pi 4** and **Raspberry Pi OS (64-bit)**. Kiln Helper was tested with **Bookworm**. A newer version (Trixie) has had reports of trouble with kiln-controller, so pick Bookworm if Imager offers it ("Raspberry Pi OS (Legacy)").
3. In Imager's settings (⚙), set a **username and password**, your **Wi-Fi**, and turn on **SSH**.
4. Write the SD card, put it in the Pi, and power it on.

## 2. Run the installer

Open a terminal on the Pi (or connect with SSH) and type:

```bash
git clone https://github.com/christeferrains/kiln-helper.git
cd kiln-helper
./install.sh
```

It takes about 10–20 minutes. Here's what it does:
- Downloads and installs [kiln-controller](https://github.com/jbruce12000/kiln-controller) for you (the version Kiln Helper was tested with). It's the engine that reads the thermocouple and switches the relay. **You don't download anything else.**
- Turns on the Pi's SPI (thermocouple board) and I2C (optional power sensor)
- Sets kiln-controller up for the MAX31856 board
- Puts the Kiln Helper screen and service in place. Kiln Helper is the **only** thing phones can reach (port 8081). kiln-controller is set to listen only on the Pi itself (port 8091), so every start passes the PIN and temperature checks. The original kiln-controller screen is kept as `public/old.html` but is no longer reachable from other devices.
- Makes a private phone-alert name only you know
- Starts everything at power-on
- Names the Pi **kiln**, so phones can reach it at **http://kiln.local:8081**

**It starts in practice mode:** the kiln is **not** switched yet. That's safe while you build and test.

### Options

| Command | What it does |
| --- | --- |
| `./install.sh --real` | **Really switch the kiln.** Only when the box is built, checked by an electrician, and bench-tested |
| `./install.sh --practice` | Back to practice mode |
| `./install.sh --celsius` / `--fahrenheit` | Show temperatures in °C / °F. The emergency shutoff, thermocouple offset, PID numbers and saved firings are **converted**, not just relabeled |
| `./install.sh --120v` / `--240v` | The kiln's supply (used by the optional element test) |
| `./install.sh --kiosk` | Open Kiln Helper full-screen on the Pi's touchscreen at power-on |
| `./install.sh --keep-hostname` | Don't rename the Pi to "kiln" |
| `./install.sh --dry-run` | Only show what would happen |

You can run the installer again any time, for example to switch to `--real` or to update Kiln Helper after a `git pull`:
- It **keeps** your firings, settings, alert name, °F/°C and real/practice mode. It only changes what you ask for.
- It **restarts** Kiln Helper and kiln-controller at the end so the new version really runs.
- It **refuses to change anything while the kiln is firing**, autotuning or running an element test. Run it again after the firing has finished.

## 3. Open Kiln Helper

On a phone or computer **on the same Wi-Fi**, go to:

**http://kiln.local:8081**

If that doesn't open (some Android phones don't support `.local` names), use the Pi's number address, shown at the end of the installer or in your router's device list: `http://192.168.x.x:8081`.

The first time, **guided setup** walks you through your slip, a grown-up PIN, phone alerts, and a heat test.

## 4. Phone alerts

1. Install the free **ntfy** app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) · [iPhone](https://apps.apple.com/app/ntfy/id1625396347)).
2. In Kiln Helper, go to ⚙ Settings → Phone & alerts and copy the alert name.
3. In ntfy, tap **＋** and subscribe to that name.
4. Tap **Send a test alert**.

Alerts work anywhere your phone has internet, even away from home. Alerts are sent in the background, so a slow or offline internet connection never delays a shutdown.

## Practice mode on any computer

Open `software/index.html` straight from the download folder, or add `?practice=1` to the address (`http://kiln.local:8081/?practice=1`). Practice mode is clearly labeled and **never** talks to the kiln. A real screen never switches itself into practice mode: if it can't reach the Pi it says **Not connected**.

## Updating

```bash
cd ~/kiln-helper
git pull
./install.sh          # keeps real/practice mode and °F/°C
```

## Uninstalling Kiln Helper (keeps kiln-controller)

```bash
sudo systemctl disable --now kiln-helper
sudo rm /etc/systemd/system/kiln-helper.service /etc/sudoers.d/kiln-helper
mv ~/kiln-controller/public/old.html ~/kiln-controller/public/index.html
# let kiln-controller serve its own screen on the network again (port 8081)
sed -i 's/ip = "127.0.0.1"/ip = "0.0.0.0"/' ~/kiln-controller/kiln-controller.py
sed -i 's/^listening_port = 8091/listening_port = 8081/' ~/kiln-controller/config.py
sudo systemctl restart kiln-controller
```
Without Kiln Helper, the PIN, temperature lock and Kiln Helper's automatic stops no longer apply.

---
[← Build guide](build-guide.md) · Next: [Using Kiln Helper →](using-it.md)
