import subprocess
from datetime import datetime, timedelta

WITTY_PI_DIR = "/home/ore653/wittypi"
SCHEDULE_FILE = f"{WITTY_PI_DIR}/schedule.wpi"

MIN_LEAD_SEC = 120
MARGIN_SEC = 180


def _hms(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"H{h} M{m} S{s}"


def _apply(text):
    with open(SCHEDULE_FILE, "w") as f:
        f.write(text)
    subprocess.run(["sudo", "./runScript.sh"], cwd=WITTY_PI_DIR, check=True)


def clear_schedule():
    _apply("")


def schedule_wakeup(sample_time, runtime_sec):
    now = datetime.now()
    wake = datetime.combine(now.date(), datetime.strptime(sample_time, "%H:%M").time())
    if wake <= now:
        wake += timedelta(days=1)

    lead = int((wake - now).total_seconds())
    if lead < MIN_LEAD_SEC:
        raise ValueError("Sample time must be at least 2 minutes away")

    # The Pi stays on for the first 2 minutes, then sleeps until wake time
    _apply(f"""BEGIN {now:%Y-%m-%d %H:%M:%S}
END   2035-12-31 23:59:59

ON M2
OFF {_hms(lead - MIN_LEAD_SEC)}

ON {_hms(runtime_sec + MARGIN_SEC)}
OFF M15 WAIT
""")
