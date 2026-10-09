"""Update previous-day display; collect only the two target-time windows."""
from seoul_previous_day import main


def needs_collection(entry, now):
    return now.hour in (12, 18) and now.minute <= 20


if __name__ == '__main__':
    main()
