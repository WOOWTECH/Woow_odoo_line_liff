# -*- coding: utf-8 -*-
"""/liff/clear-session must actually end the current session.

It exists to rescue a customer stuck on a broken LIFF session (every page
403). The route was declared save_session=False, and in Odoo 18 that makes
the request skip saving the session altogether (odoo/http.py _save_session
returns early when can_save is False), so the "clear" was never persisted
and the customer stayed logged in exactly as before.
"""
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'line_ci')
class TestLiffClearSession(HttpCase):

    def setUp(self):
        super().setUp()
        self.env['res.users'].create({
            'name': 'Clear session customer', 'login': 'clear_session_customer',
            'password': 'clear-session-pw-123',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })

    def _my_home_needs_login(self):
        resp = self.url_open('/my/home', allow_redirects=False)
        return resp.status_code in (302, 303) and '/web/login' in resp.headers.get('Location', '')

    def test_clear_session_logs_the_customer_out(self):
        self.authenticate('clear_session_customer', 'clear-session-pw-123')
        self.assertFalse(self._my_home_needs_login(), 'precondition: the customer is logged in')

        self.url_open('/liff/clear-session?r=/my/home', allow_redirects=False)

        self.assertTrue(self._my_home_needs_login(),
                        'after /liff/clear-session the member page must ask for a new login')
