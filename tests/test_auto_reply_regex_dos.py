# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""H-19: a catastrophic regex auto-reply rule can pin a worker with one message.

`(a+)+` against 26 "a" characters takes ~38s under Python's `re`, which has no
timeout, and the `regex` module (which does support one) is not in the
odoo:18 image. So the defence is static: reject catastrophic patterns on
save (`@api.constrains`), and re-check at match time too, since data saved
before this fix (or written straight to the DB) would otherwise still run.
"""

import time
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged

CATASTROPHIC_PATTERNS = [
    '(a+)+b',
    '(a*)*b',
    '(a+)*b',
    '(a|ab)+c',
]


@tagged('post_install', '-at_install', 'line_ci')
class TestAutoReplyRegexValidatedOnSave(TransactionCase):
    """The seam here is the model's own public write path (create), the way
    the settings UI would use it — not a private helper."""

    def test_catastrophic_patterns_are_rejected_on_save(self):
        for pattern in CATASTROPHIC_PATTERNS:
            with self.assertRaises(
                    ValidationError,
                    msg=f'{pattern!r} should be rejected as a regex auto-reply rule'):
                self.env['line.auto.reply'].create({
                    'name': 'bad rule',
                    'keyword': pattern,
                    'match_type': 'regex',
                    'response_text': 'hello',
                })

    def test_a_legitimate_regex_rule_is_still_accepted(self):
        rule = self.env['line.auto.reply'].create({
            'name': 'booking keyword',
            'keyword': '^(預約|booking)',
            'match_type': 'regex',
            'response_text': '請問想預約什麼服務呢？',
        })
        self.assertTrue(rule.exists())

    def test_an_invalid_but_non_catastrophic_pattern_is_still_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['line.auto.reply'].create({
                'name': 'unbalanced paren',
                'keyword': '(unclosed',
                'match_type': 'regex',
                'response_text': 'hello',
            })

    def test_contains_and_exact_rules_are_never_checked_as_regex(self):
        # A literal string that would be a catastrophic *pattern* if
        # interpreted as regex must still save fine when it is not regex.
        rule = self.env['line.auto.reply'].create({
            'name': 'literal keyword',
            'keyword': '(a+)+b',
            'match_type': 'contains',
            'response_text': 'hello',
        })
        self.assertTrue(rule.exists())


@tagged('post_install', '-at_install', 'line_ci')
class TestAutoReplyRegexSafeAtMatchTime(HttpCase):
    """H-3/H-4's shared webhook-signing setup, reused here (see
    test_webhook_robustness.py) — this file only needs its own secret."""

    SECRET = 'h19_test_secret'

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_base.messaging_channel_secret', self.SECRET)
        ICP.set_param('woow_line_base.messaging_access_token', 'h19_access_token')

    def _sign(self, body_bytes):
        import base64
        import hashlib
        import hmac
        return base64.b64encode(
            hmac.new(self.SECRET.encode(), body_bytes, hashlib.sha256).digest()
        ).decode()

    def _send_message(self, text, user_id='Uh19'):
        import json
        body = json.dumps({'events': [{
            'type': 'message',
            'replyToken': 'reply-token-h19',
            'source': {'type': 'user', 'userId': user_id},
            'message': {'type': 'text', 'id': 'm-h19', 'text': text},
            'timestamp': 0,
        }]}).encode()
        return self.url_open('/line/webhook', data=body, headers={
            'Content-Type': 'application/json',
            'X-Line-Signature': self._sign(body),
        })

    def test_a_legitimate_regex_rule_still_replies(self):
        self.env['line.auto.reply'].create({
            'name': 'booking keyword',
            'keyword': '^(預約|booking)',
            'match_type': 'regex',
            'response_text': '請問想預約什麼服務呢？',
            'sequence': 5,
        })

        sent = []

        def capture_reply(api, reply_token, messages, *args, **kwargs):
            sent.extend(messages)
            return True

        Api = type(self.env['line.api.service'])
        with patch.object(Api, 'reply', capture_reply):
            response = self._send_message('booking a table for two')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(sent, 'the legitimate regex rule should have replied')
        self.assertEqual(sent[0]['text'], '請問想預約什麼服務呢？')

    def test_a_catastrophic_rule_saved_before_this_fix_is_skipped_not_run(self):
        """Simulate legacy data: a rule that was legitimate when saved, whose
        keyword was later swapped for a catastrophic one directly in the DB
        — bypassing @api.constrains, which only runs through the ORM. This is
        the one place raw SQL is fine: arranging legacy data, not driving the
        seam under test.
        """
        rule = self.env['line.auto.reply'].create({
            'name': 'was legitimate',
            'keyword': 'hello',
            'match_type': 'regex',
            'response_text': 'hi there',
            'sequence': 1,
        })
        self.env.cr.execute(
            "UPDATE line_auto_reply SET keyword = %s WHERE id = %s",
            ('(a+)+b', rule.id),
        )
        rule.invalidate_recordset(['keyword'])

        sent = []

        def capture_reply(api, reply_token, messages, *args, **kwargs):
            sent.extend(messages)
            return True

        Api = type(self.env['line.api.service'])
        started = time.monotonic()
        with patch.object(Api, 'reply', capture_reply):
            response = self._send_message('a' * 30)
        elapsed = time.monotonic() - started

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            elapsed, 5,
            f'a message must not hang a worker on a legacy catastrophic '
            f'regex rule (took {elapsed:.1f}s)')
        self.assertFalse(
            sent, 'the catastrophic legacy rule must be skipped, not matched')
