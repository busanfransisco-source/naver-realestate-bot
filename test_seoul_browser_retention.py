import json
import re
import shutil
import subprocess
import unittest
from datetime import datetime

import gen_briefing
from production_data_cards import KEYS, KST, card_metadata, load_contents, pending_body, valid_card


class BrowserRetentionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node needed for JavaScript execution')
    def test_expiry_and_next_day_keep_original_body_and_label_copy(self):
        body = '서울 주요 상권 실시간\n조회: 2026-10-03 10:56 (KST)\n원자료 시각: 10:30~10:40\n최신 78곳'
        contents = {key: pending_body(key) for key in KEYS}
        contents['seoulcommerce'] = body
        page = gen_briefing.build_html(new_data_contents=contents)
        script = re.search(r'function refreshDataCardExpiry\(\) \{.*?</script>', page, re.S).group(0).removesuffix('</script>')
        harness = '''
const assert = require('assert');
const body = BODY;
const ta = {id:'ta-seoulcommerce', value:body};
const status = {textContent:'',style:{}};
const button = {disabled:false,textContent:'복사'};
const card = {dataset:{expires:'2026-10-03T11:00:00+09:00',dailyExpires:'2026-10-04T00:00:00+09:00'},querySelector:s=>s==='textarea'?ta:s==='.data-status'?status:button};
global.document={querySelectorAll:()=>[card]};
global.window={}; global.setInterval=()=>{};
Date.now=()=>Date.parse('2026-10-03T11:15:00+09:00');
SCRIPT
assert.equal(ta.value,body);assert.equal(button.disabled,false);
assert.equal(button.textContent,'복사');
assert.equal(status.textContent,'');
window.__content_seoulcommerce=body;
Date.now=()=>Date.parse('2026-10-04T11:15:00+09:00');
refreshDataCardExpiry();assert.equal(ta.value,body);
assert.equal(button.textContent,'이전 자료 복사');
assert.equal(window.__content_seoulcommerce,body);
'''.replace('BODY', json.dumps(body, ensure_ascii=False)).replace('SCRIPT', script)
        result = subprocess.run([shutil.which('node'), '-e', harness], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(valid_card('seoulcommerce', card_metadata('seoulcommerce', body), datetime(2026,10,3,11,15,tzinfo=KST)))


if __name__ == '__main__':
    unittest.main()
