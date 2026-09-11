# -*- coding: utf-8 -*-
# woow_odoo_line_liff/tests/test_audience_sync.py
# N2: LINE Audience 同步不能把封鎖/退訂用戶送去 narrowcast 名單
from unittest.mock import patch, MagicMock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'line_ci')
class TestAudienceSync(TransactionCase):

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_base.messaging_access_token', 'test_token')

    def _make_user(self, line_user_id, is_follower=True, is_blocked=False,
                    notification_enabled=True):
        return self.env['line.user'].create({
            'line_user_id': line_user_id,
            'display_name': line_user_id,
            'is_follower': is_follower,
            'is_blocked': is_blocked,
            'notification_enabled': notification_enabled,
        })

    @patch('odoo.addons.woow_line_base.models.line_api_service.http_requests.post')
    def test_sync_excludes_blocked_and_opted_out_users(self, mock_post):
        eligible = self._make_user('Ueligible')
        blocked = self._make_user('Ublocked', is_blocked=True)
        opted_out = self._make_user('Uoptedout', notification_enabled=False)

        tag = self.env['line.audience.tag'].create({
            'name': 'Test Tag',
            'user_ids': [(6, 0, (eligible + blocked + opted_out).ids)],
        })

        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {'audienceGroupId': 111},
        )

        tag.action_sync_to_line()

        self.assertEqual(mock_post.call_count, 1)
        sent_ids = [a['id'] for a in mock_post.call_args.kwargs['json']['audiences']]
        self.assertIn(
            'Ueligible', sent_ids,
            'the eligible user must be in the synced audience')
        self.assertNotIn(
            'Ublocked', sent_ids,
            'a blocked user must not be in the synced audience')
        self.assertNotIn(
            'Uoptedout', sent_ids,
            'a user who opted out of notifications must not be in the synced audience')

    @patch('odoo.addons.woow_line_base.models.line_api_service.http_requests.delete')
    @patch('odoo.addons.woow_line_base.models.line_api_service.http_requests.post')
    def test_sync_keeps_old_audience_when_create_fails(self, mock_post, mock_delete):
        eligible = self._make_user('Ueligible2')
        tag = self.env['line.audience.tag'].create({
            'name': 'Test Tag 2',
            'user_ids': [(6, 0, eligible.ids)],
            'line_audience_group_id': '999',
        })

        mock_post.return_value = MagicMock(status_code=400, text='error')

        tag.action_sync_to_line()

        mock_delete.assert_not_called()
        self.assertEqual(
            tag.line_audience_group_id, '999',
            'the old audience group id must be kept when the new create fails')
