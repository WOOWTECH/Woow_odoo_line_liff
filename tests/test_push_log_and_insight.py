# -*- coding: utf-8 -*-
# woow_odoo_line_liff/tests/test_push_log_and_insight.py
"""push 稽核日誌與 Insight 抓取狀態（woow_paas_platform#1831：合併自 markstudio 站上 18.0.3.2.6）。"""
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import requests

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged

MOCK_POST = 'odoo.addons.woow_line_base.models.line_api_service.http_requests.post'
TOKEN = 'test-token-should-never-be-logged'


@tagged('post_install', '-at_install', 'line_ci')
class TestPushAuditLog(TransactionCase):

    def setUp(self):
        super().setUp()
        self.ICP = self.env['ir.config_parameter'].sudo()
        self.ICP.set_param('woow_line_base.messaging_access_token', TOKEN)
        self.api = self.env['line.api.service']
        self.PushLog = self.env['line.push.log'].sudo()
        self.messages = [{'type': 'text', 'text': '客人的私人內容'}, {'type': 'flex', 'altText': 'x'}]

    def _new_logs(self, before):
        return self.PushLog.search([('id', '>', before)])

    def _last_id(self):
        return self.PushLog.search([], order='id desc', limit=1).id or 0

    def test_accepted_push_logs_summary_only(self):
        before = self._last_id()
        with patch(MOCK_POST, return_value=MagicMock(status_code=200, text='{}')):
            ok = self.api.push_message('U' + 'a' * 32, self.messages)
        self.assertIs(ok, True, 'push_message 必須維持回傳 bool')
        log = self._new_logs(before)
        self.assertEqual(len(log), 1)
        self.assertEqual(log.result_state, 'accepted')
        self.assertEqual(log.operation_source, 'push_message')
        self.assertEqual(json.loads(log.messages), {'count': 2, 'types': ['text', 'flex']})
        self.assertNotIn('私人內容', log.messages)

    def test_network_error_is_unknown_not_failed(self):
        before = self._last_id()
        with patch(MOCK_POST, side_effect=requests.Timeout('timed out')):
            ok, status, _body = self.api.push_message_ex('U' + 'b' * 32, self.messages)
        self.assertFalse(ok)
        self.assertEqual(status, 0)
        self.assertEqual(self._new_logs(before).result_state, 'unknown',
                         '逾時時 LINE 可能已受理，不可記成失敗')

    def test_rejected_push_is_failed_and_token_redacted(self):
        before = self._last_id()
        body = '{"message":"bad token %s"}' % TOKEN
        with patch(MOCK_POST, return_value=MagicMock(status_code=400, text=body)):
            self.api.push_message('U' + 'c' * 32, self.messages)
        log = self._new_logs(before)
        self.assertEqual(log.result_state, 'failed')
        self.assertNotIn(TOKEN, log.response_body)

    def test_no_token_is_not_attempted(self):
        self.ICP.set_param('woow_line_base.messaging_access_token', '')
        before = self._last_id()
        with patch(MOCK_POST) as post:
            ok = self.api.push_message('U' + 'd' * 32, self.messages)
        self.assertFalse(ok)
        post.assert_not_called()
        self.assertEqual(self._new_logs(before).result_state, 'not_attempted')

    def test_log_failure_never_blocks_send(self):
        with patch(MOCK_POST, return_value=MagicMock(status_code=200, text='{}')), \
                patch.object(type(self.PushLog), 'create', side_effect=Exception('boom')):
            self.assertTrue(self.api.push_message('U' + 'e' * 32, self.messages))


@tagged('post_install', '-at_install', 'line_ci')
class TestInsightFetchState(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Log = self.env['line.insight.log']
        self.delivery_map = {'apiPush': 'delivery_push', 'apiReply': 'delivery_reply'}

    def test_ready_payload_missing_key_means_zero(self):
        state, values, err = self.Log._normalise_insight_response(
            {'status': 'ready', 'apiPush': 5}, self.delivery_map, 'delivery')
        self.assertEqual((state, err), ('ready', ''))
        self.assertEqual(values, {'delivery_push': 5, 'delivery_reply': 0})

    def test_unready_is_not_converted_to_zero(self):
        state, values, _err = self.Log._normalise_insight_response(
            {'status': 'unready'}, self.delivery_map, 'delivery')
        self.assertEqual((state, values), ('unready', {}))

    def test_malformed_values_rejected(self):
        for bad in (None, -1, True, '3'):
            state, values, _err = self.Log._normalise_insight_response(
                {'status': 'ready', 'apiPush': bad}, self.delivery_map, 'delivery')
            self.assertEqual((state, values), ('error', {}), repr(bad))
        self.assertEqual(self.Log._normalise_insight_response(None, self.delivery_map, 'd')[0], 'error')

    def test_combined_state(self):
        combine = self.Log._combined_fetch_state
        self.assertEqual(combine('ready', 'ready'), 'ready')
        self.assertEqual(combine('ready', 'error'), 'partial')
        self.assertEqual(combine('error', 'unready'), 'error')
        self.assertEqual(combine('unready', 'out_of_service'), 'out_of_service')
        self.assertEqual(combine('unready', 'unready'), 'unready')

    def test_backfill_requires_line_manager(self):
        user = self.env['res.users'].create({
            'name': 'no line rights', 'login': 'insight_no_rights',
            'groups_id': [(6, 0, [self.env.ref('base.group_user').id])],
        })
        with self.assertRaises(AccessError):
            self.Log.with_user(user).backfill_insight(['2026-01-01'])

    def test_backfill_rejects_future_and_bad_dates(self):
        future = (self.Log._tokyo_today() + timedelta(days=1)).isoformat()
        for dates in ([future], ['2026-02-30'], ['20260101'], [], 'x'):
            with self.assertRaises(ValidationError):
                self.Log._parse_backfill_dates(dates)
