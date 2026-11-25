"""Run existing independent collectors on GitHub with three bounded workers."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import time

from morning_cloud_prepare import collection_allowed

# Members of each group run in order. Shared data-cards.json writers stay together.
# Analysis candidates consume the realestate collector's latest.json.
GROUPS = (
    ("transactions", ("ensure_transactions_daily.py",)),
    ("daily", ("weather_fetch.py", "fortune_fetch.py")),
    ("realestate", ("naver_realestate_fetch.py", "naver_realestate_analysis_fetch.py")),
    ("quicknews", ("daum_news_fetch.py",)),
    ("news", ("world_news_fetch.py", "finance_news_fetch.py", "ai_news_fetch.py")),
    ("market", ("market_fetch.py",)),
    ("subscriptions", ("aptinfo_fetch.py",)),
    ("supplydemand", ("supply_demand.py",)),
    ("data_cards", ("ensure_wiki_daily.py", "ensure_seoul_daily.py")),
)
SCRIPTS = frozenset(script for _, scripts in GROUPS for script in scripts)
SECRET_OWNERS = {"RONE_KEY": "aptinfo_fetch.py", "SEOUL_OPEN_DATA_KEY": "ensure_seoul_daily.py"}


def collect(root=Path("."), *, runner=None):
    if runner is None and not collection_allowed():
        raise ValueError("live collection is allowed only on GitHub Linux runners")
    runner = runner or subprocess.run
    root = Path(root)

    def run_group(group):
        name, scripts = group
        outcomes = []
        for script in scripts:
            started = time.monotonic()
            environment = os.environ.copy()
            for key, owner in SECRET_OWNERS.items():
                if script != owner:
                    environment.pop(key, None)
            options = dict(cwd=str(root), env=environment, check=False, timeout=180)
            try:
                if script == "daum_news_fetch.py":
                    with (root / "shortnews-debug.log").open("w", encoding="utf-8") as log:
                        result = runner([sys.executable, "-X", "utf8", script],
                                        stdout=log, stderr=subprocess.STDOUT, **options)
                else:
                    result = runner([sys.executable, "-X", "utf8", script], **options)
                status = "ok" if result.returncode == 0 else "failed"
            except (subprocess.SubprocessError, OSError):
                status = "failed"
            elapsed = round(time.monotonic() - started, 3)
            print(f"Collector {script}: {status}; elapsed_seconds={elapsed}", flush=True)
            outcomes.append(dict(script=script, status=status, elapsedSeconds=elapsed))
        return dict(group=name, scripts=outcomes)

    with ThreadPoolExecutor(max_workers=3) as executor:
        groups = list(executor.map(run_group, GROUPS))
    return groups


if __name__ == "__main__":
    results = collect()
    sys.exit(any(script["status"] != "ok" for group in results for script in group["scripts"]))
