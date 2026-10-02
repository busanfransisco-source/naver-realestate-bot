"""Build a local 29-card preview; never replace the live 26-card briefing.

All three cards use source dates and fail closed. Power is excluded.
This script exports manual-share text but does not send messages.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import json

import requests

from daily_data_card_sources import (
    SourceUnavailable,
    WIKIMEDIA_TOPICS,
    build_crypto_digest,
    fetch_crypto_history,
    fetch_seoul_commerce_digest,
    fetch_wikimedia_digest,
)
from gen_briefing import build_html
from local_api_secrets import load_secret


WIKI_TITLES = tuple(title for titles in WIKIMEDIA_TOPICS.values() for title in titles)
OUTPUT = Path("tmp/briefing-29-preview.html")
LEGACY_OUTPUT = Path("tmp/briefing-30-preview.html")
PENDING_SEOUL = "집계 대기 · 최신 상권 자료 검증 실패\n\n자동공유 비활성\n출처: 서울 열린데이터광장"


def failure_reason(error):
    """Public diagnostic labels only; never expose an exception URL or API key."""
    if isinstance(error, requests.Timeout):
        return '네트워크 응답 시간 초과'
    if isinstance(error, requests.HTTPError):
        return '원자료 서버 HTTP 오류'
    if isinstance(error, requests.RequestException):
        return '원자료 서버 연결 실패'
    if isinstance(error, SourceUnavailable):
        message = str(error)
        if any(word in message for word in ('오래', '미래', '최신', '지연', 'fresh')):
            return '원자료 기준시각 또는 최신 표본 부족'
        return '원자료 형식 또는 집계 검증 실패'
    return '인증 또는 자료 형식 검증 실패'


def preview_contents(session=requests, *, today_utc=None, diagnostics=None):
    today_utc = today_utc or datetime.now(timezone.utc).date()
    contents = {"seoulcommerce": PENDING_SEOUL}
    try:
        contents['seoulcommerce'] = fetch_seoul_commerce_digest(session, load_secret('seoul'))
    except (requests.RequestException, SourceUnavailable, ValueError, RuntimeError) as error:
        contents['seoulcommerce'] = PENDING_SEOUL
        if diagnostics is not None:
            diagnostics['seoulcommerce'] = failure_reason(error)
    try:
        history = fetch_crypto_history(session)
        source_day = history[0][0]
        if not 0 <= (today_utc - source_day).days <= 1:
            raise SourceUnavailable("원자료 기준일이 오래됐거나 미래입니다")
        contents["cryptofear"] = build_crypto_digest(history)
    except (requests.RequestException, SourceUnavailable, ValueError) as error:
        contents["cryptofear"] = "집계 대기 · 새 원자료 검증 실패\n\n자동공유 비활성\n출처: Alternative.me"
        if diagnostics is not None:
            diagnostics['cryptofear'] = failure_reason(error)
    try:
        digest = fetch_wikimedia_digest(session, WIKI_TITLES, today=today_utc)
        match = re.search(r"집계 마감: (\d{4}-\d{2}-\d{2}) \(UTC\)", digest)
        if not match or not 1 <= (today_utc - datetime.fromisoformat(match.group(1)).date()).days <= 3:
            raise SourceUnavailable("공통 집계 마감일이 오래됐거나 미래입니다")
        contents["wikiinterest"] = digest
    except (requests.RequestException, SourceUnavailable, ValueError) as error:
        contents["wikiinterest"] = "집계 대기 · 새 원자료 검증 실패\n\n자동공유 비활성\n출처: Wikimedia Analytics API"
        if diagnostics is not None:
            diagnostics['wikiinterest'] = failure_reason(error)
    return contents


def main():
    OUTPUT.parent.mkdir(exist_ok=True)
    contents = preview_contents()
    html = build_html(new_data_contents=contents)
    rendered = "<!-- LOCAL PREVIEW ONLY: 29 CARDS, POWER EXCLUDED; DO NOT DEPLOY OR AUTO-SEND -->\n" + html
    OUTPUT.write_text(rendered, encoding="utf-8")
    # Refresh the previously opened preview too, so it cannot retain the removed card.
    LEGACY_OUTPUT.write_text(rendered, encoding="utf-8")
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=9)))
    output_dir = Path('tmp') / f'share-ready-{now:%Y-%m-%d-%H%M%S}'
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {'generated_at_kst': now.isoformat(), 'manual_share_ready': {},
                'auto_send_enabled': False, 'power_excluded': True, 'files': {}}
    for key, content in contents.items():
        ready = '집계 대기' not in content and '자동공유 비활성' not in content
        manifest['manual_share_ready'][key] = ready
        if ready:
            if key == 'seoulcommerce':
                match = re.search(r'원자료 시각: (\d{2}:\d{2})~', content)
                if not match:
                    raise ValueError('서울 상권 원자료 시각 누락')
                source_min = datetime.combine(now.date(), datetime.strptime(match.group(1), '%H:%M').time(), now.tzinfo)
                manifest['seoul_snapshot_expires_at_kst'] = (source_min + timedelta(minutes=30)).isoformat()
            filename = f'{key}.txt'
            (output_dir / filename).write_text(content + '\n', encoding='utf-8')
            manifest['files'][key] = filename
    manifest['all_manual_share_ready'] = all(manifest['manual_share_ready'].values())
    (output_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(OUTPUT.resolve())
    print(output_dir.resolve())
    if not manifest['all_manual_share_ready']:
        raise SystemExit('Some sources failed freshness checks: manual-share bundle incomplete')


if __name__ == "__main__":
    main()
