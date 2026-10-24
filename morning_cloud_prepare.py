"""Prepare the morning snapshot on GitHub Linux, never on the delivery PC.

The six independent existing collectors run with bounded concurrency. Ordinary
source files remain the website inputs; only a fully validated nine-box bundle
can replace the public ready snapshot. checkedAtKst means body revalidation,
not an invented observation time for weekly prices or a books sales period.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta

from morning_briefing_contract import (
    BOX_KEYS, KST, _body_issues, build_snapshot, validate_snapshot,
)

GROUPS = (
    ('fortune', 'fortune_fetch.py', ('fortune',)),
    ('weather', 'weather_fetch.py', ('weather',)),
    ('shortnews', 'daum_news_fetch.py', ('shortnews',)),
    ('subscriptions', 'aptinfo_fetch.py', ('subs', 'trend')),
    ('market', 'market_fetch.py', ('fuelfx', 'metalcoin', 'books')),
    ('realestate', 'naver_realestate_fetch.py', ('realestate',)),
)
CACHE_FILES = {
    'trend': ('neonet-trend-cache.json',),
    'fuelfx': ('fuel-cache.json', 'fx-cache.json'),
}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    _atomic_bytes(path, data)


def _atomic_bytes(path, data):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _text(path):
    try:
        return Path(path).read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError):
        return ''


def read_sources(root, now, only_keys=None):
    """Read raw approved source files without rendering unrelated boxes."""
    root = Path(root)
    weekday = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[now.weekday()]
    selected = set(BOX_KEYS if only_keys is None else only_keys)
    bodies = [''] * len(BOX_KEYS)
    for key in BOX_KEYS:
        if key not in selected:
            continue
        specific = root / f'{key}-{weekday}.txt'
        bodies[BOX_KEYS.index(key)] = _text(specific if specific.exists() else root / f'{key}.txt')
    # A weekly source has its own provenance clock. Never relabel this as daily.
    evidence = {}
    if 'trend' in selected:
        try:
            cache = json.loads((root / 'neonet-trend-cache.json').read_text(encoding='utf-8'))
            from neonet_trend import URL, REGIONS, format_digest
            if (cache.get('schemaVersion') != 1 or cache.get('sourceUrl') != URL
                    or [row['region'] for row in cache['data']['regions']] != list(REGIONS)):
                raise ValueError('invalid weekly source')
            bodies[4] = format_digest(cache)
            evidence['trendCheckedAtKst'] = cache['checkedAtKst']
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
            bodies[4] = ''
    # Match the web's newest verified YES24 file selection, without date editing.
    if 'books' in selected:
        from yes24_books import load_digest
        try:
            bodies[7] = load_digest(directory=root, today=now.date())
        except (OSError, UnicodeError, ValueError, TypeError):
            bodies[7] = ''
        period = re.search(r'^📅 집계 기간: (\d{4}-\d{2}-\d{2}) ~ (\d{4}-\d{2}-\d{2})$', bodies[7], re.M)
        if period:
            evidence.update(booksPeriodStart=period[1], booksPeriodEnd=period[2])
    return bodies, evidence


def _paths(root, group, now):
    name, _, keys = group
    weekday = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[now.weekday()]
    prefixes = list(keys) + (['latest'] if name == 'realestate' else [])
    paths = {Path(root) / filename for prefix in prefixes
             for filename in (f'{prefix}.txt', f'{prefix}-{weekday}.txt',
                              f'{prefix}-{now.date().isoformat()}.txt')}
    if name == 'realestate':
        paths.update(Path(root) / filename for filename in (
            'latest.json', f'latest-{weekday}.json', f'latest-{now.date().isoformat()}.json'))
    paths.update(Path(root) / filename for key in keys for filename in CACHE_FILES.get(key, ()))
    return paths


def _backup(paths):
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore(saved):
    for path, original in saved.items():
        if original is None:
            if path.exists():
                path.unlink()
        elif not path.exists() or path.read_bytes() != original:
            _atomic_bytes(path, original)


def _mtime(path):
    try:
        return Path(path).stat().st_mtime_ns
    except OSError:
        return None


def _group_issues(keys, bodies, evidence, now):
    issues = []
    for key in keys:
        issues.extend(_body_issues(key, bodies[BOX_KEYS.index(key)], now.date(), evidence))
    if 'trend' in keys:
        try:
            stamp = datetime.fromisoformat(evidence['trendCheckedAtKst'])
            if stamp.tzinfo is None or not timedelta(0) <= now - stamp <= timedelta(days=8):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            issues.append('trend: invalid weekly source check')
    if 'books' in keys:
        try:
            start = date.fromisoformat(evidence['booksPeriodStart'])
            end = date.fromisoformat(evidence['booksPeriodEnd'])
            if start.weekday() != 0 or end - start != timedelta(days=6) or not 1 <= (now.date() - end).days <= 8:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            issues.append('books: invalid weekly source period')
    return issues


def _run_group(root, group, now, absolute_deadline, runner, fixed_clock=False):
    name, script, keys = group
    saved = _backup(_paths(root, group, now))
    # Successful script exit alone is insufficient: several old collectors
    # intentionally exit zero after writing a failure message or using cache.
    expected = {key: Path(root) / ('neonet-trend-cache.json' if key == 'trend' else f'{key}.txt')
                for key in keys}
    before = {key: _mtime(path) for key, path in expected.items()}
    reason = None
    issue_count = 0
    boxes = []
    try:
        remaining = absolute_deadline - time.monotonic()
        if remaining <= 0:
            reason = 'global_deadline'
        else:
            result = runner([sys.executable, '-X', 'utf8', script], cwd=str(root),
                            capture_output=True, timeout=min(180, remaining), check=False)
            if result.returncode:
                reason = 'collector_exit_nonzero'
            else:
                # Other workers may be halfway through their own file writes.
                # Validate and restore by box, not by multi-box collector.
                checked_now = now if fixed_clock else datetime.now(KST)
                bodies, evidence = read_sources(root, checked_now, only_keys=keys)
                from morning_source_publication import source_issues
                for key in keys:
                    path = expected[key]
                    changed = _mtime(path) is not None and _mtime(path) != before[key]
                    issues = source_issues(key, bodies[BOX_KEYS.index(key)], evidence, checked_now)
                    retained_weekly = key == 'books' and not changed and not issues
                    box_reason = ('source_validation_failed' if issues else
                                  'collector_did_not_refresh_required_source' if not changed and not retained_weekly
                                  else None)
                    if box_reason:
                        paths = _paths(root, (name, script, (key,)), now)
                        _restore({path: data for path, data in saved.items() if path in paths})
                    boxes.append(dict(key=key, status='failed' if box_reason else
                                      'retained_weekly' if retained_weekly else 'ok',
                                      reason=box_reason, issueCount=len(issues)))
                failed = [box for box in boxes if box['status'] == 'failed']
                if failed:
                    reason = failed[0]['reason']
                    issue_count = sum(box['issueCount'] for box in failed)
    except subprocess.TimeoutExpired:
        reason = 'collector_timeout'
    except Exception:
        # Never echo subprocess output, request URLs, credentials or paths.
        reason = 'collector_exception'
    if reason and not boxes:
        _restore(saved)
        boxes = [dict(key=key, status='failed', reason=reason, issueCount=0) for key in keys]
    successful = any(box['status'] != 'failed' for box in boxes)
    return dict(group=name, status=('partial' if successful else 'failed') if reason else 'ok',
                reason=reason, issueCount=issue_count, boxes=boxes)


def collection_allowed():
    return (sys.platform.startswith('linux') and os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('RUNNER_OS') == 'Linux')


def prepare(root, output, report, *, collect=False, now=None, runner=None,
            deadline_seconds=270, max_workers=3):
    """Build the public bundle; injected runners are exclusively for tests."""
    root, output, report = map(Path, (root, output, report))
    if collect and runner is None and not collection_allowed():
        raise ValueError('live collection is allowed only on GitHub Linux runners')
    if max_workers < 1 or max_workers > 3 or not 0 < deadline_seconds <= 270:
        raise ValueError('collector concurrency/deadline outside approved bounds')
    fixed_now = now
    now = now or datetime.now(KST)
    groups = []
    if collect:
        deadline = time.monotonic() + deadline_seconds
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run_group, root, group, now, deadline,
                                       runner or subprocess.run, fixed_now is not None): group[0] for group in GROUPS}
            for future in as_completed(futures):
                groups.append(future.result())
        order = {group[0]: index for index, group in enumerate(GROUPS)}
        groups.sort(key=lambda row: order[row['group']])
    finished = fixed_now or datetime.now(KST)
    failed_groups = [group for group in groups if group['status'] != 'ok']
    diagnostics = dict(schemaVersion=1, checkedAtKst=finished.isoformat(),
                       mode='collect' if collect else 'export-only', groups=groups,
                       status='failed', snapshotWritten=False, websiteWritten=False)
    bodies, evidence = read_sources(root, finished)
    # The website can publish independently verified boxes without replacing
    # the sender's strict nine-box ready contract with a partial snapshot.
    eligible_keys = ([box['key'] for group in groups for box in group['boxes']
                      if box['status'] != 'failed'] if collect else list(BOX_KEYS))
    from morning_source_publication import build_publication
    try:
        publication = build_publication(bodies, finished, evidence=evidence, eligible_keys=eligible_keys)
        atomic_json(output.with_name('morning-website-sources.json'), publication)
        diagnostics.update(websiteWritten=True, websiteKeys=[box['key'] for box in publication['boxes']])
    except (ValueError, OSError, TypeError, KeyError):
        pass
    try:
        snapshot = build_snapshot(bodies, finished, evidence=evidence)
        if failed_groups:
            diagnostics['reason'] = 'collector_groups_failed_previous_snapshot_preserved'
        else:
            atomic_json(output, snapshot)
            diagnostics.update(status='ok', snapshotWritten=True,
                               snapshotSha256=snapshot['snapshotSha256'])
    except (ValueError, OSError, TypeError, KeyError):
        diagnostics['reason'] = 'incomplete_or_invalid_source_previous_snapshot_preserved'
    if diagnostics['status'] != 'ok' and diagnostics['websiteWritten']:
        diagnostics['status'] = 'partial'
    # Diagnostics contain only fixed group IDs/status codes, never report text.
    atomic_json(report, diagnostics)
    return diagnostics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--collect', action='store_true', help='Live collection on GitHub Linux only')
    mode.add_argument('--export-only', action='store_true', help='Validate current files without collection')
    parser.add_argument('--output', default='morning-briefing-ready.json')
    parser.add_argument('--report', default='morning-briefing-report.json')
    args = parser.parse_args(argv)
    try:
        result = prepare(Path.cwd(), Path(args.output), Path(args.report), collect=args.collect)
    except (ValueError, OSError):
        if sys.stdout is not None:
            print('Morning snapshot refused: invalid execution environment or output destination.')
        return 1
    if sys.stdout is not None:
        print('Morning snapshot:', result['status'])
        for group in result['groups']:
            print(group['group'] + ': ' + group['status'] +
                  (' (' + group['reason'] + ')' if group['reason'] else ''))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
