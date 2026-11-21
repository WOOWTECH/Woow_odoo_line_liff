# Part of Odoo. See LICENSE file for full copyright and licensing details.
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from odoo.addons.woow_odoo_line_liff.controllers.liff_redirect import (
    LiffRedirectController,
)
from odoo.addons.woow_odoo_line_liff.controllers.webhook import (
    LineWebhookController,
)
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'line_ci')
class TestDownstreamExtensionHooks(TransactionCase):

    def test_bridge_base_path_default(self):
        self.assertEqual(LiffRedirectController()._get_bridge_base_path(), '/liff/redirect')

    def test_prepare_event_hook_runs_before_log_and_handler(self):
        calls = []
        controller = LineWebhookController()
        event = {'type': 'message', 'source': {'userId': 'U-hook'}}

        request_path = (
            'odoo.addons.woow_odoo_line_liff.controllers.webhook.request')
        # Supplying the replacement avoids mock introspecting an unbound
        # Werkzeug LocalProxy before an HTTP request exists.
        with patch(request_path, new=MagicMock()) as mocked_request, \
             patch.object(controller, '_prepare_event_line_user',
                          side_effect=lambda *args: calls.append('prepare')), \
             patch.object(controller, '_log_event') as log, \
             patch.object(controller, '_handle_message',
                          side_effect=lambda *args: calls.append('handler')), \
             patch.object(controller, '_forward_to_livechat_marked'):
            mocked_request.env.cr.savepoint.side_effect = lambda: nullcontext()
            log.return_value.write.side_effect = lambda *args: calls.append('log_done')
            controller._process_event(event)

        self.assertEqual(calls, ['prepare', 'handler', 'log_done'])

    def test_auto_push_skip_default_is_false(self):
        notification = self.env['mail.notification']
        self.assertFalse(notification._line_auto_push_skip(
            notification, self.env['mail.message'], self.env['res.partner'],
            self.env['line.user'],
        ))
