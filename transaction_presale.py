"""Keep auxiliary presale collection distinct from verified apartment totals."""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PRESALE_BUDGET_SECONDS = 20
REASONS = {'timeout': '수집 시간초과', 'failed': '조회 실패',
           'baseline_pending': '비교 기준 미확보'}


def count_line(count, status='ok'):
    if status == 'ok' and type(count) is int and count >= 0:
        return f'분양권/입주권 {count:,}건'
    return '분양권/입주권 집계 미확인(' + REASONS.get(status, '조회 미완료') + ')'


def failure_status(error):
    reason = getattr(error, 'reason', error)
    detail = getattr(error, 'stderr', '') or ''
    if isinstance(detail, bytes):
        detail = detail.decode('utf-8', errors='replace')
    last_line = detail.strip().splitlines()[-1] if detail.strip() else ''
    return 'timeout' if isinstance(reason, (TimeoutError, subprocess.TimeoutExpired)) or any(
        word in (str(reason)+' '+last_line).lower() for word in ('timed out', 'timeouterror', 'curl: (28)')) else 'failed'


def state_status(state):
    if state.get('presale_status') in ('ok', *REASONS):
        return state['presale_status']
    if state.get('auxiliary_complete') is False or '분양권 CSV 일시 실패' in state.get('source', ''):
        return 'failed'
    return 'ok'


def repair_outputs(today, directory=Path('.')):
    """Correct a known failed auxiliary count without recollecting apartments."""
    directory = Path(directory)
    try:
        state = json.loads((directory/'transactions-state.json').read_text(encoding='utf-8'))
        status = state_status(state)
        if state.get('last_output_date') != today.isoformat() or status == 'ok':
            return False
        text = (directory/f'transactions-{today.isoformat()}.txt').read_text(encoding='utf-8')
        if not text.startswith(f'{today.month}/{today.day}('):
            return False
        total = re.search(r'^전국 ([\d,]+)건', text, re.M)
        if not total or int(total[1].replace(',', '')) != sum(
                not r.get('is_presale') for r in state.get('today_new_records', [])):
            return False
        fixed, count = re.subn(r'^분양권/입주권 [^\n]*', count_line(None, status), text, count=1, flags=re.M)
        if not count:
            return False
        from realestate_transactions_fetch import WEEKDAY_EN
        for name in ('transactions.txt', f'transactions-{WEEKDAY_EN[today.weekday()]}.txt',
                     f'transactions-{today.isoformat()}.txt'):
            (directory/name).write_text(fixed, encoding='utf-8')
        return fixed != text
    except (OSError, ValueError, TypeError, KeyError):
        return False


def fetch_rows(today):
    """A subprocess deadline also bounds DNS, connection and download waits."""
    environment = os.environ.copy()
    environment.pop('MOLIT_API_KEY', None)
    worker = Path(__file__).with_name('realestate_transactions_fetch.py')
    try:
        result = subprocess.run([sys.executable, '-X', 'utf8', str(worker),
                                 '--presale-payload', today.isoformat()],
                                capture_output=True, text=True, encoding='utf-8', check=True,
                                timeout=PRESALE_BUDGET_SECONDS, env=environment)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
        stages = error.stderr or ''
        if isinstance(stages, bytes):
            stages = stages.decode('utf-8', errors='replace')
        known = [stage for stage in ('official_page', 'official_csv', 'legacy_transport')
                 if 'presale_stage='+stage in stages]
        print('Presale request stopped at:', known[-1] if known else 'worker_start')
        raise
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or not rows or any(not r.get('is_presale') for r in rows):
        raise ValueError('invalid auxiliary rows')
    return rows


def fetch_payload(today):
    """Use a session matching the official page; one independent legacy fallback."""
    from realestate_transactions_fetch import (DOWNLOAD_PAGE, DOWNLOAD_URL, download_form,
                                               parse_government_csv, fetch_nationwide_transactions)
    from curl_cffi import requests
    try:
        with requests.Session(impersonate='chrome') as session:
            headers = {'Referer': DOWNLOAD_PAGE, 'Accept': '*/*'}
            print('presale_stage=official_page', file=sys.stderr, flush=True)
            page = session.get(DOWNLOAD_PAGE, headers=headers, timeout=(4, 6))
            if page.status_code in (403, 429):
                raise PermissionError('official source restricted')
            page.raise_for_status()
            print('presale_stage=official_csv', file=sys.stderr, flush=True)
            response = session.post(DOWNLOAD_URL, data=download_form(today, 'E'),
                                    headers=headers, timeout=(4, 10))
            if response.status_code in (403, 429):
                raise PermissionError('official source restricted')
            response.raise_for_status()
            return parse_government_csv(response.content, '분양권/입주권')
    except PermissionError:
        raise
    except Exception:
        print('presale_stage=legacy_transport', file=sys.stderr, flush=True)
        return fetch_nationwide_transactions(today, thing_no='E', property_type='분양권/입주권')


def refresh(today, directory=Path('.'), fetcher=fetch_rows):
    """Retry only the missing auxiliary part in the existing scheduled job."""
    from realestate_transactions_fetch import KST, tokenized_rows, classify_records, update_history_max
    directory = Path(directory)
    path = directory/'transactions-state.json'
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('last_output_date') != today.isoformat() or state_status(state) == 'ok':
        return False
    if state_status(state) == 'baseline_pending' and state.get('presale_baseline_date') == today.isoformat():
        return False
    try:
        rows = fetcher(today)
    except Exception as error:
        state['auxiliary_complete'] = False
        state['presale_status'] = failure_status(error)
        path.write_text(json.dumps(state, ensure_ascii=False, separators=(',', ':'), sort_keys=True)+'\n', encoding='utf-8')
        repair_outputs(today, directory)
        print('Presale retry unresolved:', state['presale_status'], '; verified apartments retained')
        return False
    current = tokenized_rows(rows)
    state['presale_collected_at'] = datetime.now(KST).isoformat()
    state['source'] = state.get('source', '').replace(' (분양권 CSV 일시 실패)',
                                                    ' + 실거래가 공개시스템 전국 CSV')
    yesterday = (today-timedelta(days=1)).isoformat()
    baseline_valid = (state.get('presale_baseline_date') in (yesterday, today.isoformat())
                      and state.get('presale_baseline_started_date') != today.isoformat())
    if baseline_valid:
        previous = set(state.get('seen_tokens', []))
        added = classify_records([r for token, r in current.items() if token not in previous], state.get('history_max', {}))
        state['today_new_records'] = list(tokenized_rows([*state.get('today_new_records', []), *added]).values())
        carried = state.get('today_presale_count')
        state['today_presale_count'] = (carried+len(added) if type(carried) is int else
                                        sum(bool(r.get('is_presale')) for r in state['today_new_records']))
        state['presale_status'] = 'ok'
    else:
        # A fresh month-long file alone cannot prove today's newly registered count.
        state['presale_status'] = 'baseline_pending'
        state['presale_baseline_started_date'] = today.isoformat()
    state['presale_baseline_date'] = today.isoformat()
    state['auxiliary_complete'] = True
    state['seen_tokens'] = sorted(set(state.get('seen_tokens', [])) | set(current))
    state['history_max'] = update_history_max(state.get('history_max', {}), rows)
    path.write_text(json.dumps(state, ensure_ascii=False, separators=(',', ':'), sort_keys=True)+'\n', encoding='utf-8')
    if state['presale_status'] != 'ok':
        repair_outputs(today, directory)
    else:
        from realestate_transactions_fetch import WEEKDAY_EN
        text = (directory/f'transactions-{today.isoformat()}.txt').read_text(encoding='utf-8')
        total = state['today_presale_count']
        fixed = re.sub(r'^분양권/입주권 [^\n]*', count_line(total), text, count=1, flags=re.M)
        for name in ('transactions.txt', f'transactions-{WEEKDAY_EN[today.weekday()]}.txt', f'transactions-{today.isoformat()}.txt'):
            (directory/name).write_text(fixed, encoding='utf-8')
    return True
