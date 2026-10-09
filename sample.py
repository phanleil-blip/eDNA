import csv
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from hardware.led import set_led
from hardware.pumps import all_off, set_pump

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

SETTLE_SEC = 2
SUB_MAX_SEC = 3600
PRES_MAX_SEC = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "Sampler_log.txt"), logging.StreamHandler()],
)
log = logging.getLogger("sampler")

stop_event = threading.Event()
state = {"job": None}
_job_lock = threading.Lock()


def log_event(event, motor="", duration=0, notes=""):
    now = datetime.now()
    with open(LOG_DIR / "data.csv", "a", newline="") as f:
        csv.writer(f).writerow([now.date(), now.time(), event, motor, duration, notes])
    log.info("%s | motor=%s | duration=%ss | %s", event, motor, duration, notes)


def start_job(label, fn, *args):
    if not _job_lock.acquire(blocking=False):
        return False
    stop_event.clear()
    state["job"] = label

    def worker():
        set_led("sampling")
        try:
            fn(*args)
        except Exception:
            log.exception("Job %s failed", label)
        finally:
            all_off()
            set_led("on")
            state["job"] = None
            _job_lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return True


def run_pump(kind, unit, duration):
    motor = f"{kind}-{unit}"
    log_event("PUMP_START", motor, duration)
    start = time.monotonic()
    set_pump(kind, unit, True)
    try:
        finished = not stop_event.wait(duration)
    finally:
        set_pump(kind, unit, False)
    log_event("PUMP_STOP" if finished else "PUMP_ABORT", motor, round(time.monotonic() - start, 1))
    return finished


def run_sequence(cfg):
    log_event("SEQUENCE_START", notes=",".join(cfg["units"]))
    completed = _run_units(cfg)
    log_event("SEQUENCE_END" if completed else "SEQUENCE_ABORT")


def _run_units(cfg):
    for i, unit in enumerate(cfg["units"]):
        if i and stop_event.wait(cfg["interval_min"] * 60):
            return False
        if not run_pump("sub", unit, cfg["sample_duration"]):
            return False
        if stop_event.wait(SETTLE_SEC):
            return False
        if not run_pump("pres", unit, cfg["pres_duration"]):
            return False
    return True


def prime(cfg):
    log_event("PRIME_START")
    completed = all(
        run_pump("pres", unit, cfg["pres_duration"]) and not stop_event.wait(1)
        for unit in cfg["units"]
    )
    log_event("PRIME_END" if completed else "PRIME_ABORT")


def sequence_duration(cfg):
    n = len(cfg["units"])
    per_unit = cfg["sample_duration"] + SETTLE_SEC + cfg["pres_duration"]
    return n * per_unit + max(n - 1, 0) * cfg["interval_min"] * 60
