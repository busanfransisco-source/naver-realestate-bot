"""Preserve observed original article URLs in readable/copyable quicknews text."""
import html
import re

ARTICLE_ROW = re.compile(r'^\S+ \((?:톱뉴스|정치|경제|사회|국제|날씨)\) (.+)$')
URL = re.compile(r'https://v\.daum\.net/v/[0-9]{10,20}')
MISSING = '원문 링크 미확인'


def source_line(url):
    return url if isinstance(url, str) and URL.fullmatch(url) else MISSING


def source_issues(body):
    lines = body.splitlines()
    issues = []
    for index, line in enumerate(lines):
        if not ARTICLE_ROW.match(line):
            continue
        next_line = lines[index+1] if index+1 < len(lines) else ''
        if next_line != MISSING and not URL.fullmatch(next_line):
            issues.append('each quicknews article needs its observed source URL or explicit missing notice')
    return list(dict.fromkeys(issues))


def render_preview(body):
    lines = []
    for line in body.split('\n'):
        if URL.fullmatch(line):
            safe = html.escape(line, quote=True)
            lines.append(f'<a class="news-source-link" href="{safe}" target="_blank" rel="noopener noreferrer">{safe}</a>')
        else:
            lines.append(html.escape(line))
    return '\n'.join(lines)
