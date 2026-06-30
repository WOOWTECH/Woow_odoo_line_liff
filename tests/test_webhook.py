# -*- coding: utf-8 -*-
# woow_odoo_line_liff/tests/test_webhook.py
# Webhook controller 單元測試
import base64
import hashlib
import hmac
import json

from odoo.tests.common import HttpCase


class TestWebhookSignature(HttpCase):
    """測試 Webhook 簽章驗證"""

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_base.messaging_channel_secret', 'test_webhook_secret')
        ICP.set_param('woow_line_base.messaging_access_token', 'test_access_token')

    def _sign(self, body_bytes, secret='test_webhook_secret'):
        return base64.b64encode(
            hmac.new(secret.encode(), body_bytes, hashlib.sha256).digest()
        ).decode()

    def test_webhook_invalid_signature_returns_403(self):
        body = json.dumps({'events': []}).encode()
        response = self.url_open(
            '/line/webhook',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Line-Signature': 'invalid_signature',
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_webhook_valid_signature_returns_200(self):
        body = json.dumps({'events': []}).encode()
        signature = self._sign(body)
        response = self.url_open(
            '/line/webhook',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Line-Signature': signature,
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_webhook_invalid_json_returns_400(self):
        body = b'not valid json'
        signature = self._sign(body)
        response = self.url_open(
            '/line/webhook',
            data=body,
            headers={
                'Content-Type': 'application/json',
                'X-Line-Signature': signature,
            },
        )
        self.assertEqual(response.status_code, 400)
