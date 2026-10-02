import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
import audit_data_cards as audit
from production_data_cards import KEYS, KST, card_metadata, pending_body


class AuditTests(unittest.TestCase):
    def test_expired_render_is_allowed_only_with_source_expiry_guard(self):
        now = datetime(2026, 10, 3, 18, 20, tzinfo=KST)
        body = '조회: 2026-10-03\n원자료 시각: 17:40~17:50'
        entry = card_metadata('seoulcommerce', body)
        entries = {key: card_metadata(key, pending_body(key)) for key in KEYS}
        entries['seoulcommerce'] = entry
        cache = {'cards': entries, 'generatedAtKst': now.isoformat()}
        sections = [f'<section class="card" data-expires="{entry["expiresAtKst"]}"><textarea id="ta-seoulcommerce">{body}</textarea></section>']
        sections += [f'<section class="card"><textarea id="ta-{key}">{pending_body(key)}</textarea></section>' for key in KEYS[1:]]
        sections += ['<section class="card"></section>'] * 26
        page = ''.join(sections) + '<script>refreshDataCardExpiry()</script>'
        expected = {key: pending_body(key) for key in KEYS}
        with patch.object(audit, 'load_contents', return_value=expected):
            self.assertTrue(audit.assess(cache, page, cache, now)['deploymentMatched'])
            self.assertFalse(audit.assess(cache, page.replace('refreshDataCardExpiry', 'missing'), cache, now)['deploymentMatched'])

    def test_source_cache_difference_is_not_deployment_success(self):
        now = datetime.now(KST)
        cache = {'cards': {}, 'generatedAtKst': now.isoformat()}
        with patch.object(audit, 'load_contents', return_value={k: pending_body(k) for k in KEYS}):
            self.assertFalse(audit.assess(cache, '', {'cards': {}}, now)['deploymentMatched'])


if __name__ == '__main__':
    unittest.main()
