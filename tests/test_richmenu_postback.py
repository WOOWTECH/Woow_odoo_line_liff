# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Rich Menu postback buttons must reply with a link that actually opens.

A postback button (as opposed to a URI button) sends
`action=richmenu&target=X` to the webhook, and the bot replies with a text
message carrying a link. That link was built by a helper which assumes every
target has its own LIFF app, so for `book` / `my-bookings` it produced
`/liff/book` — a route that does not exist. A customer tapping 立即預約 or
我的預約 on a postback-style menu was handed a 404.

The assertion deliberately does not compare against a URL computed the way the
code computes it; that would pass by construction. It follows the link on the
running server and checks that the route resolves.
"""

import base64
import hashlib
import hmac
import json
from unittest.mock import patch
from urllib.parse import urlparse

from odoo.tests import HttpCase, tagged

SECRET = 'postback_test_secret'


@tagged('post_install', '-at_install', 'line_ci')
class TestRichMenuPostbackLinks(HttpCase):

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_base.messaging_channel_secret', SECRET)
        ICP.set_param('woow_line_base.messaging_access_token', 'test_token')
        # Force the non-LIFF fallback. A liff.line.me link cannot be followed
        # from a test, and the fallback is exactly where the bad path came from.
        for page in ('member', 'news'):
            ICP.set_param(f'woow_odoo_line_liff.liff_id_{page}', '')

    def _tap(self, target):
        """Deliver a signed rich-menu postback; return the text the bot replied."""
        body = json.dumps({'events': [{
            'type': 'postback',
            'replyToken': 'reply-token-test',
            'source': {'type': 'user', 'userId': 'Upostbacktest'},
            'postback': {'data': f'action=richmenu&target={target}'},
            'timestamp': 0,
        }]}).encode()
        signature = base64.b64encode(
            hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()

        sent = []

        def capture_reply(api, reply_token, messages, *args, **kwargs):
            sent.extend(messages)
            return True

        Api = type(self.env['line.api.service'])
        with patch.object(Api, 'reply', capture_reply):
            response = self.url_open('/line/webhook', data=body, headers={
                'Content-Type': 'application/json',
                'X-Line-Signature': signature,
            })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(sent, f'the bot sent no reply for target={target!r}')
        return sent[0]['text']

    def _link_path(self, text):
        url = next((word for word in text.split() if word.startswith('http')), None)
        self.assertTrue(url, f'the reply carries no link: {text!r}')
        return urlparse(url).path

    def test_booking_buttons_reply_with_a_link_that_opens(self):
        for target in ('book', 'my-bookings'):
            path = self._link_path(self._tap(target))
            response = self.url_open(path, allow_redirects=False)
            self.assertNotEqual(
                response.status_code, 404,
                f'{target!r}: the reply links to {path}, which is a 404')

    def test_news_button_still_replies_with_a_link_that_opens(self):
        """Guard the target that already worked, so the fix doesn't move it."""
        path = self._link_path(self._tap('news'))
        response = self.url_open(path, allow_redirects=False)
        self.assertNotEqual(response.status_code, 404, f'news: the reply links to {path}, which is a 404')

    def test_locations_button_replies_with_shop_info_and_navigation(self):
        """18.0.3.5.0: no web page any more; the bot answers with the shop details and a Google Maps link."""
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_odoo_line_liff.shop_name', '測試店')
        ICP.set_param('woow_odoo_line_liff.shop_address', '台北市測試路 1 號')
        ICP.set_param('woow_odoo_line_liff.shop_latitude', '25.0330')
        ICP.set_param('woow_odoo_line_liff.shop_longitude', '121.5654')
        text = self._tap('locations')
        self.assertIn('測試店', text)
        self.assertIn('台北市測試路 1 號', text)
        self.assertIn('https://www.google.com/maps/dir/?api=1&destination=25.033,121.5654', text)
        self.assertNotIn('/liff/locations', text)

    def test_locations_button_without_coordinates_has_no_map_link(self):
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_odoo_line_liff.shop_latitude', '1]);alert(1);//')
        ICP.set_param('woow_odoo_line_liff.shop_longitude', '121.5')
        text = self._tap('locations')
        self.assertNotIn('google.com/maps', text)
        self.assertNotIn('alert(1)', text)
