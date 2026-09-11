# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""H-2: news broadcast treated every failure as "quota exceeded" and
doubled messages.

action_push_to_line() called api.broadcast(), which only returns a bool.
Any failure — a timeout after LINE already accepted the send, a 400, a
401, a 5xx — was logged as "受限 (429)" and silently downgraded to
multicast, so a timeout meant every known follower got the news twice,
and a real error was hidden from the user.

These tests drive the public push button (action_push_to_line) on a
published line.news record, with only the LINE HTTP boundary mocked
(woow_line_base.models.line_api_service.http_requests), and assert on
what a user/operator can see: which LINE endpoints were actually called,
and the line.push.log rows the product itself writes.
"""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

MOCK_POST = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.post'


@tagged('post_install', '-at_install', 'line_ci')
class TestNewsBroadcastFallback(TransactionCase):

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_base.messaging_access_token', 'test_token')
        self.follower = self.env['line.user'].create({
            'line_user_id': 'Ufollower1',
            'is_follower': True,
            'is_blocked': False,
            'notification_enabled': True,
        })
        self.news = self.env['line.news'].create({
            'title': 'H-2 test article',
            'push_method': 'broadcast',
        })
        self.news.action_publish()

    def _push_log_rows(self):
        return self.env['line.push.log'].sudo().search(
            [], order='id asc')

    def test_broadcast_200_logs_success_and_never_multicasts(self):
        with patch(MOCK_POST) as mock_post:
            mock_post.return_value = type('R', (), {
                'status_code': 200, 'text': '{}',
            })()
            result = self.news.action_push_to_line()

        called_urls = [c.args[0] for c in mock_post.call_args_list]
        self.assertEqual(called_urls, ['https://api.line.me/v2/bot/message/broadcast'],
                          'a 200 broadcast must not also multicast')

        rows = self._push_log_rows()
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows.success)
        self.assertEqual(rows.status_code, 200)
        self.assertEqual(result['params']['type'], 'success')

    def test_broadcast_429_downgrades_to_multicast_and_logs_both(self):
        responses = [
            type('R', (), {'status_code': 429, 'text': '{"message":"quota"}'})(),
            type('R', (), {'status_code': 200, 'text': '{}'})(),
        ]
        with patch(MOCK_POST, side_effect=responses) as mock_post:
            result = self.news.action_push_to_line()

        called_urls = [c.args[0] for c in mock_post.call_args_list]
        self.assertEqual(called_urls, [
            'https://api.line.me/v2/bot/message/broadcast',
            'https://api.line.me/v2/bot/message/multicast',
        ])

        rows = self._push_log_rows()
        self.assertEqual(len(rows), 2, 'both the failed broadcast and the multicast must be logged')
        self.assertEqual(rows[0].status_code, 429)
        self.assertFalse(rows[0].success)
        self.assertEqual(rows[1].status_code, 200)
        self.assertTrue(rows[1].success)
        self.assertEqual(result['params']['type'], 'success')

    def test_broadcast_500_does_not_multicast_and_reports_failure(self):
        with patch(MOCK_POST) as mock_post:
            mock_post.return_value = type('R', (), {
                'status_code': 500, 'text': '{"message":"internal error"}',
            })()
            result = self.news.action_push_to_line()

        called_urls = [c.args[0] for c in mock_post.call_args_list]
        self.assertEqual(called_urls, ['https://api.line.me/v2/bot/message/broadcast'],
                          'a 500 must fail loudly, never silently fan out to multicast')

        rows = self._push_log_rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows.success)
        self.assertEqual(rows.status_code, 500)

        self.assertEqual(result['params']['type'], 'danger')
        self.assertIn('500', result['params']['message'])

    def test_broadcast_timeout_does_not_multicast(self):
        """A timeout may mean LINE already accepted the broadcast; sending a
        multicast on top of it would double-deliver to every follower."""
        import requests

        with patch(MOCK_POST, side_effect=requests.exceptions.Timeout('timed out')) as mock_post:
            result = self.news.action_push_to_line()

        called_urls = [c.args[0] for c in mock_post.call_args_list]
        self.assertEqual(called_urls, ['https://api.line.me/v2/bot/message/broadcast'],
                          'a network timeout must not trigger a multicast fallback')

        rows = self._push_log_rows()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows.success)
        self.assertEqual(rows.status_code, 0)
        self.assertEqual(result['params']['type'], 'danger')
