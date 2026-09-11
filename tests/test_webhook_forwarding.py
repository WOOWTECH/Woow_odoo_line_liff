# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""H-5: forwarding a customer's message to Discuss must not depend on the
liff auto-reply handler succeeding, and its own failures must not vanish.

Today `_forward_to_livechat` only ever runs after `_handle_message` returns
without raising, so a failing auto-reply (e.g. the reply token call blowing
up at the LINE boundary) means the customer's message never reaches Discuss
either — even though the two are unrelated features. And every exception
inside the forwarding path itself — including a bare `except ImportError:
pass` — was logged (if at all) at `_logger.debug`, which production never
sees.

Needs `woow_odoo_livechat_line` installed alongside the liff bridge (state
`liff-line`): that is what `_forward_to_livechat` forwards *to*.
"""

import base64
import hashlib
import hmac
import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

SECRET = 'h5_test_secret'
FAKE_LINE_CHANNEL_ID = '1234567890'
# Same value as SECRET on purpose: with no line.liff.config record present,
# the webhook falls back to whichever LiveChat channel has line_enabled=True
# and signs against *its* secret (see test_webhook_without_livechat_line.py's
# TestWebhookFallsBackToLivechatSecret) — using the same string for both
# means the signed body verifies regardless of which secret wins.
FAKE_LINE_CHANNEL_SECRET = SECRET


@tagged('post_install', '-at_install', 'line_ci')
class TestForwardingSurvivesHandlerFailure(HttpCase):

    def setUp(self):
        super().setUp()
        if 'im_livechat.channel' not in self.env or \
                'line_enabled' not in self.env['im_livechat.channel']._fields:
            self.skipTest('needs woow_odoo_livechat_line installed (state liff-line)')

        # Clear the module-level OAuth token cache in woow_line_base: it is
        # shared process-wide, so a token cached by an earlier test would let
        # this one skip the very http_requests.post call it needs to control.
        from odoo.addons.woow_line_base.models.line_api_service import _token_cache
        _token_cache.clear()

        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_base.messaging_channel_secret', SECRET)
        ICP.set_param('woow_line_base.messaging_access_token', 'liff_side_access_token')

        self.operator = self.env['res.users'].create({
            'name': 'H5 Operator',
            'login': 'h5_operator',
            'email': 'h5_operator@test.example',
            'groups_id': [(4, self.env.ref('im_livechat.im_livechat_group_user').id)],
        })
        self.livechat_channel = self.env['im_livechat.channel'].create({
            'name': 'H5 LINE Channel',
            'user_ids': [(4, self.operator.id)],
            'line_enabled': True,
            'line_channel_id': FAKE_LINE_CHANNEL_ID,
            'line_channel_secret': FAKE_LINE_CHANNEL_SECRET,
        })

    def _sign(self, body_bytes):
        return base64.b64encode(
            hmac.new(SECRET.encode(), body_bytes, hashlib.sha256).digest()
        ).decode()

    def _send_message(self, user_id, text):
        body = json.dumps({'events': [{
            'type': 'message',
            'replyToken': 'reply-token-h5',
            'source': {'type': 'user', 'userId': user_id},
            'message': {'type': 'text', 'id': 'm-h5', 'text': text},
            'timestamp': 0,
        }]}).encode()
        return self.url_open('/line/webhook', data=body, headers={
            'Content-Type': 'application/json',
            'X-Line-Signature': self._sign(body),
        })

    def _discuss_texts(self, user_id):
        channel = self.env['discuss.channel'].sudo().search(
            [('line_user_id', '=', user_id)], limit=1)
        if not channel:
            return []
        return channel.message_ids.mapped('body')

    def test_forwarding_still_happens_when_the_auto_reply_fails(self):
        """The liff side's own reply is made to fail at the LINE boundary
        (line.api.service.reply is the one established exception to "only
        mock the network boundary" — a reply token can never be real). An
        auto-reply rule must exist and match, otherwise `_handle_message`
        never calls reply() at all and this proves nothing."""
        self.env['line.auto.reply'].create({
            'name': 'H5 auto reply',
            'keyword': 'help',
            'match_type': 'contains',
            'response_text': 'here to help!',
        })

        Api = type(self.env['line.api.service'])
        with patch.object(Api, 'reply', side_effect=RuntimeError('reply token already used')):
            response = self._send_message('Uh5-autoreply-fails', 'help me please')

        self.assertEqual(response.status_code, 200)
        texts = self._discuss_texts('Uh5-autoreply-fails')
        self.assertTrue(
            any('help me please' in (t or '') for t in texts),
            f"the customer's message must reach Discuss even though the "
            f"auto-reply failed; channel messages were: {texts!r}")

    def test_forwarding_failure_is_logged_at_warning_without_the_message_text(self):
        """Make the *forwarding* side fail at the LINE boundary: the guest's
        profile fetch (needed only for a brand-new LINE user) raises. This is
        not the RequestException the client already handles gracefully —
        it's the network boundary itself misbehaving in a way nothing catches
        today, so it must surface as a WARNING, and it must never carry the
        customer's message text."""
        from odoo.addons.woow_line_base.models import line_api_service as svc

        secret_text = 'do-not-log-this-secret-message-body'

        def fake_post(url, **kwargs):
            self.assertIn('oauth/accessToken', url)
            resp = type('R', (), {})()
            resp.status_code = 200
            resp.json = lambda: {'access_token': 'tok', 'expires_in': 3600}
            return resp

        def fake_get(url, **kwargs):
            raise ConnectionError('LINE profile endpoint unreachable')

        with patch.object(svc.http_requests, 'post', side_effect=fake_post), \
                patch.object(svc.http_requests, 'get', side_effect=fake_get), \
                self.assertLogs('odoo.addons.woow_odoo_line_liff.controllers.webhook',
                                 level='WARNING') as captured:
            response = self._send_message('Uh5-profile-fetch-fails', secret_text)

        self.assertEqual(response.status_code, 200)
        warning_text = '\n'.join(captured.output)
        self.assertNotIn(secret_text, warning_text,
                          "the WARNING log must not contain the customer's message")
