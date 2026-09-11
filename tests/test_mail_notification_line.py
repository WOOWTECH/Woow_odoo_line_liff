# -*- coding: utf-8 -*-
# woow_odoo_line_liff/tests/test_mail_notification_line.py
# H-14: one message notifying two LINE-bound partners must reach both,
# and a partner with two notification records for the same message must
# still get exactly one push.
from unittest.mock import patch, MagicMock

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'line_ci')
class TestMailNotificationLinePush(TransactionCase):

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_base.auto_line_notify', 'True')
        ICP.set_param('woow_line_base.messaging_access_token', 'test_token')

    def _make_bound_partner(self, name, line_uid):
        partner = self.env['res.partner'].create({'name': name})
        self.env['line.user'].create({
            'line_user_id': line_uid,
            'display_name': name,
            'partner_id': partner.id,
            'is_follower': True,
            'is_blocked': False,
            'notification_enabled': True,
        })
        return partner

    @patch('odoo.addons.woow_line_base.models.line_api_service.http_requests.post')
    def test_message_to_two_partners_pushes_both(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, text='{}')
        partner_a = self._make_bound_partner('Partner A', 'Ua')
        partner_b = self._make_bound_partner('Partner B', 'Ub')

        record = self.env['res.partner'].create({'name': 'Notify target record'})
        record.message_post(
            body='hello from the chatter',
            partner_ids=(partner_a + partner_b).ids,
        )

        pushed_to = [c.kwargs['json']['to'] for c in mock_post.call_args_list]
        self.assertEqual(
            pushed_to.count('Ua'), 1,
            f'partner A must receive exactly one push, got calls to: {pushed_to}')
        self.assertEqual(
            pushed_to.count('Ub'), 1,
            f'partner B must receive exactly one push, got calls to: {pushed_to}')

    @patch('odoo.addons.woow_line_base.models.line_api_service.http_requests.post')
    def test_single_notification_still_gets_exactly_one_push(self, mock_post):
        """Guard: keying the dedupe on (message, partner) must not cause the
        plain single-notification case to be pushed more than once.

        Odoo 18's own schema (a partial unique index on mail_notification
        over (mail_message_id, res_partner_id)) makes it impossible for one
        partner to hold two notification rows for the same message, so that
        can't be exercised here; this guards the case the fix can actually
        regress.
        """
        mock_post.return_value = MagicMock(status_code=200, text='{}')
        partner = self._make_bound_partner('Partner C', 'Uc')

        record = self.env['res.partner'].create({'name': 'Notify target record 2'})
        record.message_post(
            body='single partner notification',
            partner_ids=partner.ids,
        )

        pushed_to = [c.kwargs['json']['to'] for c in mock_post.call_args_list]
        self.assertEqual(
            pushed_to.count('Uc'), 1,
            f'a single notification must produce exactly one push, got calls to: {pushed_to}')
