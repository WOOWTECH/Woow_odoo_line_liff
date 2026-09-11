# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The webhook must not crash when im_livechat is installed without the LINE bridge.

When no LINE config supplies a channel secret, the webhook falls back to a
LiveChat channel's secret. It checked only that the `im_livechat.channel` model
exists, then read `line_enabled` / `line_channel_secret` — but those fields are
added by `woow_odoo_livechat_line`, which this module does not depend on.

`im_livechat` itself is very often present (website_livechat pulls it in), so a
tenant with this module, stock LiveChat, and no secret configured yet — the
normal state during onboarding — got `ValueError: Invalid field 'line_enabled'`
and a 500 on every call, including LINE Console's "Verify" button.

The expected status is the endpoint's own documented behaviour for "no usable
secret": 403 Invalid signature.
"""

import base64
import hashlib
import hmac
import json

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'line_ci')
class TestWebhookWithoutLivechatLine(HttpCase):

    def setUp(self):
        super().setUp()
        if 'im_livechat.channel' not in self.env:
            self.skipTest('needs stock im_livechat installed to reproduce the state')
        if 'line_enabled' in self.env['im_livechat.channel']._fields:
            self.skipTest('woow_odoo_livechat_line is installed here, so its fields '
                          'exist and the failure cannot occur')
        # Onboarding state: nothing configured yet.
        self.env['ir.config_parameter'].sudo().set_param(
            'woow_line_base.messaging_channel_secret', '')
        self.env['line.liff.config'].sudo().search([]).write({'active': False})

    def test_webhook_without_any_secret_refuses_instead_of_crashing(self):
        body = json.dumps({'events': []}).encode()
        for path in ('/line/webhook', '/line/webhook/1'):
            response = self.url_open(path, data=body, headers={
                'Content-Type': 'application/json',
                'X-Line-Signature': 'not-a-real-signature',
            })
            self.assertEqual(
                response.status_code, 403,
                f'{path} returned {response.status_code} — with no usable secret '
                f'it should refuse the request, not crash')


@tagged('post_install', '-at_install', 'line_ci')
class TestWebhookFallsBackToLivechatSecret(HttpCase):
    """The other direction: when woow_odoo_livechat_line IS installed, a LiveChat
    channel's secret must still be accepted. Guards against the fix above
    disabling the fallback it was meant to protect."""

    SECRET = 'livechat_channel_secret_for_tests'

    def setUp(self):
        super().setUp()
        if 'im_livechat.channel' not in self.env or \
                'line_enabled' not in self.env['im_livechat.channel']._fields:
            self.skipTest('needs woow_odoo_livechat_line installed')
        self.env['ir.config_parameter'].sudo().set_param(
            'woow_line_base.messaging_channel_secret', '')
        self.env['line.liff.config'].sudo().search([]).write({'active': False})
        channel = self.env['im_livechat.channel'].sudo().create({'name': 'fallback'})
        channel.write({'line_channel_id': '123', 'line_channel_secret': self.SECRET,
                       'line_enabled': True})

    def test_a_request_signed_with_the_livechat_secret_is_accepted(self):
        body = json.dumps({'events': []}).encode()
        signature = base64.b64encode(
            hmac.new(self.SECRET.encode(), body, hashlib.sha256).digest()).decode()
        response = self.url_open('/line/webhook', data=body, headers={
            'Content-Type': 'application/json', 'X-Line-Signature': signature})
        self.assertEqual(response.status_code, 200)
