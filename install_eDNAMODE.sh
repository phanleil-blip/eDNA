#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/phanleil-blip/eDNA.git"
LED_URL="https://raw.githubusercontent.com/pagniello-lab/EDNA_MODE/main/hardware/led.py"
WITTY_URL="https://www.uugear.com/repo/WittyPi4/install.sh"
APP_DIR="$HOME/eDNA"

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this as your normal user, not with sudo." >&2
    exit 1
fi

ask() {
    read -r -p "$1 [y/N] " reply
    [[ $reply =~ ^[Yy]$ ]]
}

echo "==> Installing system packages"
sudo apt-get update
sudo apt-get install -y git python3-venv i2c-tools
if grep -aq "Raspberry Pi 5" /proc/device-tree/model 2>/dev/null; then
    sudo apt-get install -y python3-rpi-lgpio
else
    sudo apt-get install -y python3-rpi.gpio
fi

echo "==> Enabling I2C"
sudo raspi-config nonint do_i2c 0
sudo usermod -aG i2c,gpio "$USER"

if [ ! -d "$HOME/wittypi" ] && ask "Install the Witty Pi 4 software?"; then
    wget -O /tmp/wittypi_install.sh "$WITTY_URL"
    sudo sh /tmp/wittypi_install.sh
fi

echo "==> Getting the code"
if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" pull --ff-only || echo "Could not update the repo, keeping the existing copy"
else
    git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

# The repo keeps everything in one folder; the code expects these locations
mkdir -p hardware templates
touch hardware/__init__.py
[ -f sample.py ] && mv sample.py sampler.py
[ -f pumps.py ] && mv pumps.py hardware/
[ -f schedule.py ] && mv schedule.py hardware/scheduler.py
[ -f index.html ] && mv index.html templates/
[ -f hardware/led.py ] || wget -q -O hardware/led.py "$LED_URL"

# Point the Witty Pi path at this user's home folder
sed -i "s|/home/ore653|$HOME|" hardware/scheduler.py

echo "==> Installing Python libraries"
python3 -m venv --system-site-packages venv
venv/bin/pip install flask adafruit-circuitpython-mcp230xx

if ask "Start the sampler automatically at boot?"; then
    sudo tee /etc/systemd/system/edna.service >/dev/null <<EOF
[Unit]
Description=eDNA sampler
After=network.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload
    sudo systemctl enable edna.service
fi

cat <<EOF

Done. Reboot once so the I2C and group changes take effect:
    sudo reboot

Then check the boards show up (expect 20 and 21):
    i2cdetect -y 1

Run the app by hand:
    sudo systemctl stop edna   # only if you enabled start at boot
    cd $APP_DIR && source venv/bin/activate && python app.py

Open http://$(hostname).local:5000 from a device on the same network.
EOF
