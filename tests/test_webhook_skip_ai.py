# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""A message a keyword auto-reply has already answered is forwarded to Live
Chat under the context key ``im_livechat_ai_skip``, so an AI Live Chat
(im_livechat_ai) records it without answering it a second time. A message no
rule answered, or whose reply failed at LINE, is forwarded without the key.

Needs `woow_odoo_livechat_line` (state `liff-line`), like test_webhook_forwarding.
"""
from unittest.mock import patch

from odoo.tests import tagged

from .test_webhook_forwarding import TestForwardingSurvivesHandlerFailure

KEY = 'im_livechat_ai_skip'


@tagged('post_install', '-at_install', 'line_ci')
class TestKeywordAnsweredSkipsAi(TestForwardingSurvivesHandlerFailure):

    def setUp(self):
        super().setUp()
        self.env['line.auto.reply'].create({
            'name': 'skip-ai rule', 'keyword': '營業時間', 'match_type': 'contains',
            'response_text': '週一至週五 9:00-18:00',
        })
        Channel = type(self.env['discuss.channel'])
        original = Channel.message_post
        self.seen = []

        def spy(channel, **kwargs):
            if channel.line_user_id:
                self.seen.append((kwargs.get('body'), bool(channel.env.context.get(KEY))))
            return original(channel, **kwargs)

        patcher = patch.object(Channel, 'message_post', autospec=True, side_effect=spy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _skip_flag(self, text):
        return [flag for body, flag in self.seen if text in str(body or '')]

    def test_keyword_answered_is_forwarded_with_skip(self):
        Api = type(self.env['line.api.service'])
        with patch.object(Api, 'reply', return_value=True):
            self.assertEqual(self._send_message('Uskip-answered', '請問營業時間？').status_code, 200)
        self.assertEqual(self._skip_flag('請問營業時間？'), [True])

    def test_no_rule_is_forwarded_without_skip(self):
        Api = type(self.env['line.api.service'])
        with patch.object(Api, 'reply', return_value=True) as reply:
            self.assertEqual(self._send_message('Uskip-norule', '我想問窗簾').status_code, 200)
        reply.assert_not_called()
        self.assertEqual(self._skip_flag('我想問窗簾'), [False])

    def test_failed_reply_is_forwarded_without_skip(self):
        Api = type(self.env['line.api.service'])
        with patch.object(Api, 'reply', return_value=False):
            self.assertEqual(self._send_message('Uskip-failed', '營業時間呢').status_code, 200)
        self.assertEqual(self._skip_flag('營業時間呢'), [False])

    # The inherited forwarding tests already run in TestForwardingSurvivesHandlerFailure.
    test_forwarding_still_happens_when_the_auto_reply_fails = None
    test_forwarding_failure_is_logged_at_warning_without_the_message_text = None
