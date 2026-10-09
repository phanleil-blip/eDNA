import json
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import sampler
from hardware.led import set_led
from hardware.pumps import UNITS
from hardware.scheduler import clear_schedule, schedule_wakeup

CONFIG_FILE = Path(__file__).with_name("config.json")
DEFAULTS = {
    "sample_time": "02:00",
    "sample_duration": 10.0,
    "pres_duration": 5.0,
    "interval_min": 1.0,
    "units": ["1A", "1B", "2A"],
    "armed": False,
}
BOOT_WINDOW_SEC = (-300, 1800)

app = Flask(__name__)


def load_config():
    try:
        saved = json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        saved = {}
    return {**DEFAULTS, **saved}


def save_config(cfg):
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=4))
    tmp.replace(CONFIG_FILE)


def form_float(name, lo, hi):
    try:
        value = float(request.form[name])
    except (KeyError, ValueError):
        abort(400, f"Invalid {name}")
    if not lo <= value <= hi:
        abort(400, f"{name} must be between {lo} and {hi}")
    return value


def start(label, fn, *args):
    if not sampler.start_job(label, fn, *args):
        abort(409, "A job is already running")
    return redirect(url_for("index"))


def due(cfg):
    target = datetime.strptime(cfg["sample_time"], "%H:%M").time()
    now = datetime.now()
    offset = (now - datetime.combine(now.date(), target)).total_seconds()
    offset = (offset + 43200) % 86400 - 43200  # signed distance to the nearest occurrence
    return BOOT_WINDOW_SEC[0] <= offset <= BOOT_WINDOW_SEC[1]


def run_scheduled(cfg):
    try:
        sampler.run_sequence(cfg)
    finally:
        save_config({**load_config(), "armed": False})


def boot():
    cfg = load_config()
    if not cfg["armed"]:
        try:
            clear_schedule()
        except (OSError, subprocess.CalledProcessError):
            sampler.log.exception("Could not clear Witty Pi schedule")
        return
    if not due(cfg):
        sampler.log.warning("Armed, but boot is outside the sample window; not running")
        return
    sampler.start_job("scheduled sample", run_scheduled, cfg)


@app.get("/")
def index():
    return render_template(
        "index.html",
        cfg=load_config(),
        units=UNITS,
        job=sampler.state["job"],
        sub_max=sampler.SUB_MAX_SEC,
        pres_max=sampler.PRES_MAX_SEC,
    )


@app.get("/status")
def status():
    return jsonify(job=sampler.state["job"])


@app.post("/config")
def save_settings():
    units = [u for u in UNITS if u in request.form.getlist("units")]
    if not units:
        abort(400, "Select at least one unit")
    sample_time = request.form.get("sample_time", "")
    try:
        datetime.strptime(sample_time, "%H:%M")
    except ValueError:
        abort(400, "Invalid sample_time")

    save_config({
        "sample_time": sample_time,
        "sample_duration": form_float("sample_duration", 0.1, sampler.SUB_MAX_SEC),
        "pres_duration": form_float("pres_duration", 0.1, sampler.PRES_MAX_SEC),
        "interval_min": form_float("interval_min", 0, 1440),
        "units": units,
        "armed": False,
    })
    return redirect(url_for("index"))


@app.post("/pump/<kind>/<unit>")
def pump(kind, unit):
    if kind not in ("sub", "pres") or unit not in UNITS:
        abort(404)
    limit = sampler.SUB_MAX_SEC if kind == "sub" else sampler.PRES_MAX_SEC
    duration = form_float("duration", 0.1, limit)
    return start(f"{kind}-{unit}", sampler.run_pump, kind, unit, duration)


@app.post("/test")
def test():
    return start("test run", sampler.run_sequence, load_config())


@app.post("/prime")
def prime():
    return start("priming", sampler.prime, load_config())


@app.post("/stop")
def stop():
    sampler.stop_event.set()
    return redirect(url_for("index"))


@app.post("/arm")
def arm():
    cfg = load_config()
    try:
        schedule_wakeup(cfg["sample_time"], sampler.sequence_duration(cfg))
    except ValueError as e:
        abort(400, str(e))
    except (OSError, subprocess.CalledProcessError):
        sampler.log.exception("Could not apply Witty Pi schedule")
        abort(500, "Could not apply Witty Pi schedule")
    save_config({**cfg, "armed": True})
    return redirect(url_for("index"))


if __name__ == "__main__":
    set_led("on")
    boot()
    app.run(host="0.0.0.0", port=5000)
