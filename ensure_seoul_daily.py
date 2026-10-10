"""Update previous-day display; collect only the two target-time windows."""
from seoul_previous_day import main
from seoul_previous_day import active_hour


def needs_collection(entry, now):
    return active_hour(now) is not None


if __name__ == '__main__':
    if not main():
        raise SystemExit('Seoul target slot missing; previous-day display preserved')
