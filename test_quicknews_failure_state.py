import os, tempfile, unittest, json
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
import daum_news_fetch as news
import quicknews_state as state

NOW=datetime(2026,11,18,18,30,tzinfo=state.KST)
def body(day=18):
    lines=[f'26년 11월 {day}일 수요일 오늘의 퀵뉴스⚡','']
    for i,label in enumerate(['정치','경제','사회','국제']*2):
        lines += [f'🔥 ({label}) 정부가 지원 계획을 발표했습니다.',f'https://v.daum.net/v/202611{day:02d}180000{i:03d}','']
    return '\n'.join(lines)

class FailureStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def seed(self,day=18):
        for n in ['shortnews.txt','shortnews-wed.txt']:(self.root/n).write_text(body(day),encoding='utf-8')
    def test_zero_preserves_exact_files_and_returns_failure(self):
        self.seed(); before={p.name:p.read_bytes() for p in self.root.iterdir()}
        self.assertFalse(state.commit_candidate('26년 11월 18일 수요일\n(오늘 뉴스 수집에 실패했습니다)',NOW,self.root))
        for n,b in before.items(): self.assertEqual((self.root/n).read_bytes(),b)
        self.assertTrue(state.load_report(self.root).startswith(state.NOTICE))
        self.assertNotIn('polite',str(json.loads((self.root/state.STATUS).read_text())['issues']))
    def test_previous_day_keeps_header_and_links(self):
        self.seed(17);state.commit_candidate('',NOW,self.root)
        report=state.load_report(self.root)
        self.assertIn('11월 17일',report);self.assertNotIn('11월 18일',report)
        self.assertIn('https://v.daum.net/v/20261117',report)
    def test_no_previous_file_explicit_empty(self):
        state.commit_candidate('',NOW,self.root)
        self.assertEqual(state.load_report(self.root),state.EMPTY)
        self.assertFalse((self.root/'shortnews.txt').exists())
    def test_recovery_replaces_and_clears_failure(self):
        self.seed(17);state.commit_candidate('',NOW,self.root)
        self.assertTrue(state.commit_candidate(body(),NOW,self.root))
        self.assertEqual(state.load_report(self.root, NOW),body().strip())
        self.assertEqual(json.loads((self.root/state.STATUS).read_text())['status'],'ok')
    def test_stale_candidate_rejected(self):
        self.assertFalse(state.commit_candidate(body(17),NOW,self.root))
    def test_missing_link_rejected(self):
        candidate=body().replace('https://v.daum.net/v/20261118180000000','원문 링크 미확인')
        self.assertFalse(state.commit_candidate(candidate,NOW,self.root))
    def test_incomplete_categories_rejected(self):
        self.assertFalse(state.commit_candidate(body().replace('(국제)','(사회)'),NOW,self.root))
    def test_broken_status_does_not_hide_failure(self):
        self.seed();(self.root/state.STATUS).write_text('{broken')
        self.assertTrue(state.load_report(self.root).startswith(state.NOTICE))
    def test_collector_exception_preserves_files_and_nonzero(self):
        self.seed();old=os.getcwd()
        try:
            os.chdir(self.root)
            with patch.object(news,'collect_news',side_effect=TimeoutError),patch.object(news,'get_indicators',return_value=[]),patch.object(news,'todays_quote',return_value=None):
                with self.assertRaises(SystemExit) as cm:news.main()
                self.assertEqual(cm.exception.code,1)
            self.assertEqual((self.root/'shortnews.txt').read_text(),body())
        finally:os.chdir(old)

if __name__=='__main__':unittest.main()

class IntegrationTests(unittest.TestCase):
    setUp = FailureStateTests.setUp
    tearDown = FailureStateTests.tearDown
    seed = FailureStateTests.seed
    def test_render_and_health_keep_failure_and_do_not_misdiagnose_politeness(self):
        import gen_briefing,briefing_health,html
        self.seed();state.commit_candidate('',NOW,self.root)
        old=os.getcwd()
        try:
            os.chdir(self.root)
            displayed=gen_briefing.read_section_text('shortnews','wed')
            self.assertTrue(displayed.startswith(state.NOTICE))
            page='<section class="card" data-slot="3"><textarea id="ta-shortnews">'+html.escape(displayed)+'</textarea></section>'
            with patch.object(briefing_health,'KEYS',('shortnews',)),patch('kospi_quote.indicator_issues',return_value=[]):
                row=briefing_health.inspect(page,NOW)[0]
            self.assertEqual(row['status'],'failed')
            self.assertTrue(any('latest collection failed' in x for x in row['issues']))
            self.assertFalse(any('polite' in x for x in row['issues']))
        finally:os.chdir(old)
    def test_hash_change_without_quote_is_not_recovery(self):
        self.seed(17);state.commit_candidate('',NOW,self.root)
        (self.root/'shortnews.txt').write_text(body())
        self.assertTrue(state.load_report(self.root, NOW).startswith(state.NOTICE))

class DawnAndBackupTests(unittest.TestCase):
    setUp = FailureStateTests.setUp
    tearDown = FailureStateTests.tearDown
    seed = FailureStateTests.seed
    def test_backup_headlines_and_urls_survive_display(self):
        backup=body().replace('정부가 지원 계획을 발표했습니다.','정부 지원 계획 발표')
        (self.root/'shortnews.txt').write_text(backup)
        self.assertEqual(state.load_report(self.root,NOW),backup.strip())
    def test_old_without_status_is_labeled_and_not_redated(self):
        self.seed(17)
        report=state.load_report(self.root,NOW)
        self.assertTrue(report.startswith(state.NOTICE));self.assertIn('11월 17일',report)
    def test_future_and_invalid_date_not_displayed(self):
        for text in [body(19),body().replace('11월 18일','13월 99일')]:
            (self.root/'shortnews.txt').write_text(text)
            self.assertEqual(state.load_report(self.root,NOW),state.EMPTY)
    def test_whitespace_cannot_clear_failure(self):
        self.seed();state.commit_candidate('',NOW,self.root)
        f=self.root/'shortnews.txt';f.write_text(f.read_text()+'\n')
        self.assertTrue(state.load_report(self.root,NOW).startswith(state.NOTICE))
    def test_newer_success_not_overwritten_by_old_dawn_failure(self):
        state.commit_candidate(body(),NOW,self.root)
        source=self.root/'incoming.json'
        source.write_text(json.dumps(dict(status='failed',attemptedAtKst=NOW.replace(hour=6).isoformat())))
        self.assertFalse(state.merge_status(source,self.root,NOW))
        self.assertEqual(json.loads((self.root/state.STATUS).read_text())['status'],'ok')
    def test_dawn_failure_is_carried_and_recovery_clears(self):
        self.seed();source=self.root/'incoming.json'
        source.write_text(json.dumps(dict(status='failed',attemptedAtKst=NOW.replace(hour=6).isoformat())))
        self.assertTrue(state.merge_status(source,self.root,NOW))
        self.assertTrue(state.load_report(self.root,NOW).startswith(state.NOTICE))
        self.assertTrue(state.commit_candidate(body(),NOW,self.root))
        self.assertEqual(state.load_report(self.root,NOW),body().strip())
    def test_dawn_rejects_future_and_yesterday_status(self):
        source=self.root/'incoming.json'
        for stamp in [NOW.replace(day=17),NOW.replace(hour=20)]:
            source.write_text(json.dumps(dict(status='failed',attemptedAtKst=stamp.isoformat())))
            self.assertFalse(state.merge_status(source,self.root,NOW))
