#!/usr/bin/env python3
import getpass
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_URL = "https://github.com/phanleil-blip/eDNA.git"
LED_URL = "https://raw.githubusercontent.com/pagniello-lab/EDNA_MODE/main/hardware/led.py"
WITTY_URL = "https://www.uugear.com/repo/WittyPi4/install.sh"

LED_PIN = 27  # GPIO17 is used by the Witty Pi
HOTSPOT_SSID = "eDNAMODE"
HOTSPOT_CONN = "eDNAMODE-hotspot"

HOME = Path.home()
APP_DIR = HOME / "eDNA"

SERVICE = """[Unit]
Description=eDNA sampler
After=network.target

[Service]
User={user}
WorkingDirectory={app_dir}
ExecStart={app_dir}/venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
"""


def run(*cmd, **kwargs):
    subprocess.run(cmd, check=True, **kwargs)


def ask(question):
    return input(f"{question} [y/N] ").strip().lower().startswith("y")


def install_packages():
    try:
        model = Path("/proc/device-tree/model").read_bytes()
    except FileNotFoundError:
        model = b""
    gpio_pkg = "python3-rpi-lgpio" if b"Raspberry Pi 5" in model else "python3-rpi.gpio"

    print("==> Installing system packages")
    run("sudo", "apt-get", "update")
    run("sudo", "apt-get", "install", "-y", "git", "python3-venv", "i2c-tools", gpio_pkg)

    print("==> Enabling I2C")
    run("sudo", "raspi-config", "nonint", "do_i2c", "0")
    run("sudo", "usermod", "-aG", "i2c,gpio", getpass.getuser())


def install_witty_pi():
    if (HOME / "wittypi").exists():
        return
    if not ask("Install the Witty Pi 4 software? (mount the hat first)"):
        return
    script = Path("/tmp/wittypi_install.sh")
    urllib.request.urlretrieve(WITTY_URL, script)
    run("sudo", "sh", str(script))


def setup_code():
    print("==> Getting the code")
    if (APP_DIR / ".git").exists():
        subprocess.run(["git", "-C", str(APP_DIR), "pull", "--ff-only"])
    else:
        run("git", "clone", REPO_URL, str(APP_DIR))

    hardware = APP_DIR / "hardware"
    hardware.mkdir(exist_ok=True)
    (APP_DIR / "templates").mkdir(exist_ok=True)
    (hardware / "__init__.py").touch()

    # The repo keeps everything in one folder; the code expects these locations
    moves = {
        "sample.py": "sampler.py",
        "pumps.py": "hardware/pumps.py",
        "schedule.py": "hardware/scheduler.py",
        "index.html": "templates/index.html",
    }
    for src, dst in moves.items():
        if (APP_DIR / src).exists():
            shutil.move(APP_DIR / src, APP_DIR / dst)

    led = hardware / "led.py"
    if not led.exists():
        urllib.request.urlretrieve(LED_URL, led)
    led.write_text(re.sub(
        r"^LED_PIN = \d+.*$",
        f"LED_PIN = {LED_PIN}  # not GPIO17, the Witty Pi uses it",
        led.read_text(),
        flags=re.M,
    ))

    scheduler = hardware / "scheduler.py"
    scheduler.write_text(scheduler.read_text().replace("/home/ore653", str(HOME)))


def install_python_libs():
    print("==> Installing Python libraries")
    run("python3", "-m", "venv", "--system-site-packages", str(APP_DIR / "venv"))
    run(str(APP_DIR / "venv/bin/pip"), "install", "flask", "adafruit-circuitpython-mcp230xx")


def setup_service():
    if not ask("Start the sampler automatically at boot?"):
        return
    unit = SERVICE.format(user=getpass.getuser(), app_dir=APP_DIR)
    run("sudo", "tee", "/etc/systemd/system/edna.service",
        input=unit, text=True, stdout=subprocess.DEVNULL)
    run("sudo", "systemctl", "daemon-reload")
    run("sudo", "systemctl", "enable", "edna.service")


def setup_hotspot():
    if not shutil.which("nmcli"):
        return False
    if not ask("Create a Wi-Fi hotspot so the sampler works without another network?"):
        return False
    password = getpass.getpass("Hotspot password (8+ characters): ")
    if len(password) < 8:
        print("Password too short, skipping hotspot.", file=sys.stderr)
        return False

    subprocess.run(["sudo", "nmcli", "connection", "delete", HOTSPOT_CONN],
                   stderr=subprocess.DEVNULL)
    # Low priority so a known Wi-Fi network wins when one is in range
    run("sudo", "nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0",
        "con-name", HOTSPOT_CONN, "ssid", HOTSPOT_SSID,
        "autoconnect", "yes", "connection.autoconnect-priority", "-10",
        "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
        "ipv4.method", "shared", "ipv6.method", "ignore",
        "wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.proto", "rsn",
        "wifi-sec.pairwise", "ccmp", "wifi-sec.group", "ccmp",
        "wifi-sec.psk", password)
    return True


def main():
    if os.geteuid() == 0:
        sys.exit("Run this as your normal user, not with sudo.")

    install_packages()
    install_witty_pi()
    setup_code()
    install_python_libs()
    setup_service()
    hotspot = setup_hotspot()

    print(f"""
Done. Reboot so the I2C and group changes take effect:
    sudo reboot

Then check the boards show up (expect 20 and 21, plus 08 with the Witty Pi):
    i2cdetect -y 1

Move the status LED to GPIO{LED_PIN}; GPIO17 is used by the Witty Pi.

Run the app by hand:
    sudo systemctl stop edna    # only if start at boot is enabled
    cd {APP_DIR} && source venv/bin/activate && python app.py

Open http://{socket.gethostname()}.local:5000 from a device on the same network.""")
    if hotspot:
        print(f"Or join the '{HOTSPOT_SSID}' Wi-Fi and open http://10.42.0.1:5000")
        print(f"Start the hotspot now with: sudo nmcli connection up {HOTSPOT_CONN}")


if __name__ == "__main__":
    main()
