# -*- coding: utf-8 -*-
"""Deleting a LINE audience must follow what LINE actually answered.

The "從 LINE 刪除" button used to ignore LINE's response: it always said
the audience was deleted and cleared the stored group id, so an audience that
LINE failed to delete stayed on LINE with nothing in Odoo pointing at it —
the same orphan problem H-8 fixed for rich menus. Re-syncing had the same gap
when it deleted the previous audience.
"""
import json
from unittest.mock import MagicMock, patch

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

MOCK_DELETE = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.delete'
MOCK_POST = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.post'


def _line_response(status, body=None):
    text = json.dumps(body) if body is not None else ''
    return MagicMock(status_code=status, text=text,
                     json=lambda: json.loads(text) if text else {})


@tagged('post_install', '-at_install', 'line_ci')
class TestAudienceDeleteFollowsLine(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'woow_line_base.messaging_access_token', 'test_token')
        self.follower = self.env['line.user'].create({
            'line_user_id': 'Uaudiencedelete', 'display_name': 'follower',
            'is_follower': True, 'is_blocked': False, 'notification_enabled': True,
        })

    def _tag(self, group_id):
        return self.env['line.audience.tag'].create({
            'name': 'Delete test', 'user_ids': [(6, 0, self.follower.ids)],
            'line_audience_group_id': group_id,
        })

    def test_failed_delete_keeps_the_link_and_says_why(self):
        tag = self._tag('12345')
        with patch(MOCK_DELETE, return_value=_line_response(500, {'message': 'Internal error'})):
            with self.assertRaises(UserError) as caught:
                tag.action_delete_from_line()
        self.assertIn('500', str(caught.exception))
        self.assertIn('Internal error', str(caught.exception))
        self.assertEqual(
            tag.line_audience_group_id, '12345',
            'the audience still exists on LINE, so Odoo must keep pointing at it')

    def test_successful_delete_clears_the_link(self):
        tag = self._tag('12345')
        with patch(MOCK_DELETE, return_value=_line_response(200, {})) as delete:
            result = tag.action_delete_from_line()
        self.assertIn('audienceGroup/12345', delete.call_args.args[0])
        self.assertFalse(tag.line_audience_group_id)
        self.assertEqual(result['params']['type'], 'success')

    def test_audience_already_gone_on_line_counts_as_deleted(self):
        tag = self._tag('12345')
        with patch(MOCK_DELETE, return_value=_line_response(404, {'message': 'Not found'})):
            result = tag.action_delete_from_line()
        self.assertFalse(tag.line_audience_group_id,
                         'LINE no longer has it, so the stale link should be cleared')
        self.assertEqual(result['params']['type'], 'success')
        self.assertIn('已不存在', result['params']['message'])

    def test_resync_warns_when_the_previous_audience_cannot_be_deleted(self):
        tag = self._tag('777')
        with patch(MOCK_POST, return_value=_line_response(202, {'audienceGroupId': 888})), \
                patch(MOCK_DELETE, return_value=_line_response(500, {'message': 'Internal error'})):
            result = tag.action_sync_to_line()
        self.assertEqual(tag.line_audience_group_id, '888',
                         'the freshly created audience is valid and must be used')
        self.assertEqual(result['params']['type'], 'warning',
                         'a leftover audience on LINE must not be reported as a clean success')
        self.assertIn('777', result['params']['message'],
                      'the operator needs the leftover audience id to clean it up')
