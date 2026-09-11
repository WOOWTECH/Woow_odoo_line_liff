# -*- coding: utf-8 -*-
"""A LIFF (passwordless) login must count as the customer's own login.

The customer's "Latest authentication" (res.users.login_date) is how an
operator sees when a customer last logged in, and res.users.log is Odoo's
audit trail of who logged in. A LIFF login used to be written by the
superuser with an explicit create_uid, which the ORM silently drops, so every
LIFF login was attributed to OdooBot and the customer's login date never
moved (seen live on three tenants on 2026-09-11).
"""
from unittest.mock import MagicMock, patch

from odoo.tests import HttpCase, tagged

MOCK_POST = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.post'
LOGIN_CHANNEL = '1234567890'
LINE_UID = 'U' + 'a1b2c3d4' * 4


@tagged('post_install', '-at_install', 'line_ci')
class TestLiffLoginCountsAsTheCustomersLogin(HttpCase):

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'woow_line_base.login_channel_id', LOGIN_CHANNEL)

    @staticmethod
    def _line_accepts_the_id_token(*args, **kwargs):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {
            'sub': LINE_UID, 'name': 'LIFF 客人', 'aud': LOGIN_CHANNEL,
        }
        return resp

    def test_liff_login_is_recorded_as_the_customers_login(self):
        last_log_before = self.env['res.users.log'].sudo().search(
            [], order='id desc', limit=1).id or 0

        with patch(MOCK_POST, side_effect=self._line_accepts_the_id_token):
            resp = self.url_open(
                '/liff/redirect/home', data={'id_token': 'fake-id-token'},
                allow_redirects=False)
        self.assertIn(resp.status_code, (302, 303),
                      'the LIFF login should succeed and redirect: %s' % resp.text[:200])

        self.env.invalidate_all()
        line_user = self.env['line.user'].sudo().search(
            [('line_user_id', '=', LINE_UID)])
        customer = self.env['res.users'].sudo().with_context(active_test=False).search(
            [('partner_id', '=', line_user.partner_id.id)])
        self.assertEqual(len(customer), 1, 'the LIFF login should use one portal user')

        new_logs = self.env['res.users.log'].sudo().search([('id', '>', last_log_before)])
        self.assertEqual(
            new_logs.mapped('create_uid'), customer,
            'the login record must name the customer, not %s'
            % ', '.join(new_logs.mapped('create_uid.name')))
        self.assertTrue(
            customer.login_date,
            "the customer's latest authentication must be set by the LIFF login")
