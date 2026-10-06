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
- Installs [kiln-controller](https://github.com/jbruce12000/kiln-controller) (the version Kiln Helper was tested with) and its Python parts
- Turns on the Pi's SPI (thermocouple board) and I2C (optional power sensor)
- Sets kiln-controller up for the MAX31856 board
- Puts the Kiln Helper screen and service in place (the original kiln-controller screen stays at `/picoreflow/old.html`)
- Makes a private phone-alert name only you know
- Starts everything at power-on
- Names the Pi **kiln**, so phones can reach it at **http://kiln.local:8081**

**It starts in practice mode:** the kiln is **not** switched yet. That's safe while you build and test.

### Options

| Command | What it does |
| --- | --- |
| `./install.sh --real` | **Really switch the kiln.** Only when the box is built, checked by an electrician, and bench-tested |
| `./install.sh --celsius` | Show temperatures in °C |
| `./install.sh --kiosk` | Open Kiln Helper full-screen on the Pi's touchscreen at power-on |
| `./install.sh --keep-hostname` | Don't rename the Pi to "kiln" |
| `./install.sh --dry-run` | Only show what would happen |

You can run the installer again any time, for example to switch to `--real` or to update Kiln Helper after a `git pull`. It keeps your firings and settings.

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

Alerts work anywhere your phone has internet, even away from home.

## Updating

```bash
cd ~/kiln-helper
git pull
./install.sh          # add --real again if you were in real mode
```

## Uninstalling Kiln Helper (keeps kiln-controller)

```bash
sudo systemctl disable --now kiln-helper
sudo rm /etc/systemd/system/kiln-helper.service /etc/sudoers.d/kiln-helper
mv ~/kiln-controller/public/old.html ~/kiln-controller/public/index.html
```

---
[← Build guide](build-guide.md) · Next: [Using Kiln Helper →](using-it.md)
