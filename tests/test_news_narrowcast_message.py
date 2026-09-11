# -*- coding: utf-8 -*-
"""A narrowcast must not be reported as a push to all friends.

A narrowcast only reaches the members of the chosen audience tag, but its
success notification reused the broadcast wording, 「推播給所有好友」, which
tells the operator the news went to everyone (seen live on komibright on
2026-09-11).
"""
from unittest.mock import MagicMock, patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

MOCK_POST = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.post'


@tagged('post_install', '-at_install', 'line_ci')
class TestNarrowcastSuccessMessage(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'woow_line_base.messaging_access_token', 'test_token')
        member = self.env['line.user'].create({
            'line_user_id': 'Unarrowcastmember', 'display_name': 'member',
            'is_follower': True, 'is_blocked': False, 'notification_enabled': True,
        })
        self.tag = self.env['line.audience.tag'].create({
            'name': 'VIP 名單', 'user_ids': [(6, 0, member.ids)],
            'line_audience_group_id': '555',
        })

    def test_narrowcast_success_names_the_audience_not_all_friends(self):
        news = self.env['line.news'].create({
            'title': '會員限定活動', 'state': 'published', 'push_method': 'narrowcast',
            'push_audience_tag_ids': [(6, 0, self.tag.ids)],
        })
        with patch(MOCK_POST, return_value=MagicMock(status_code=202, text='{}')):
            result = news.action_push_to_line()
        message = result['params']['message']
        self.assertEqual(result['params']['type'], 'success')
        self.assertNotIn('所有好友', message)
        self.assertIn('VIP 名單', message)
