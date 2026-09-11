# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""H-3 / H-4: one bad event in a delivery must not erase the whole delivery.

Today the event loop has no per-event savepoint and a bare `except Exception`
swallows DB errors too. A single DB-level error (e.g. a value too large for a
btree-indexed column) leaves the connection's transaction aborted; every later
statement in the same request — including the other events' own
`line.event.log` inserts — then fails the same way and is silently swallowed
too. The endpoint still answers 200, and when Odoo commits at the end of the
request, PostgreSQL treats COMMIT-after-abort as a rollback: every event in
the delivery is lost, with no trace in the DB (H-3).

Separately, `line.event.log` rows are written with processed=True the instant
they are created and `error_msg` is never populated anywhere, so the "has
error" filter in the log view can never match anything (H-4).

`source.userId` becomes `line.user.line_user_id`, which is both indexed and
UNIQUE — an absurdly long value there is the public-payload trigger: LINE
itself would never send such a value, but the webhook accepts whatever is in
the signed body, so this is not a code-side mock — it is a real payload that
makes PostgreSQL itself raise "index row size exceeds maximum size".
"""

import base64
import hashlib
import hmac
import json
import os

from odoo.tests import HttpCase, tagged

SECRET = 'h3_h4_test_secret'

# Comfortably past PostgreSQL's btree index row limit (~2704 bytes on an
# 8kB-page install) so the INSERT into line.user.line_user_id (indexed,
# UNIQUE) fails at the database level, not in Python.
#
# It must be high-entropy, not a repeated character: PostgreSQL TOASTs and
# PGLZ-compresses varlena values before storage, and a long run of the same
# byte compresses to almost nothing, so it never comes close to the index
# limit. Verified directly against this rig's Postgres: `repeat('a', 100000)`
# inserts fine; ~3200 bytes of hex-encoded random data reliably raises
# "index row size ... exceeds btree version 4 maximum 2704".
HUGE_USER_ID = 'U' + os.urandom(1600).hex()


@tagged('post_install', '-at_install', 'line_ci')
class TestWebhookOneBadEventDoesNotEraseTheDelivery(HttpCase):

    def setUp(self):
        super().setUp()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_base.messaging_channel_secret', SECRET)
        ICP.set_param('woow_line_base.messaging_access_token', 'test_access_token')

    def _sign(self, body_bytes):
        return base64.b64encode(
            hmac.new(SECRET.encode(), body_bytes, hashlib.sha256).digest()
        ).decode()

    def _send(self, events):
        body = json.dumps({'events': events}).encode()
        signature = self._sign(body)
        return self.url_open('/line/webhook', data=body, headers={
            'Content-Type': 'application/json',
            'X-Line-Signature': signature,
        })

    def _events(self):
        return [
            {
                'type': 'message',
                'replyToken': 'reply-token-keep-1',
                'source': {'type': 'user', 'userId': 'Ukeep1'},
                'message': {'type': 'text', 'id': 'm1', 'text': 'keep-1'},
                'timestamp': 0,
            },
            {
                # This event's handler triggers a real DB-level error: an
                # INSERT into line.user.line_user_id (indexed, UNIQUE) whose
                # value is too large for PostgreSQL's btree index row limit.
                'type': 'follow',
                'replyToken': 'reply-token-huge',
                'source': {'type': 'user', 'userId': HUGE_USER_ID},
                'timestamp': 0,
            },
            {
                'type': 'message',
                'replyToken': 'reply-token-keep-3',
                'source': {'type': 'user', 'userId': 'Ukeep3'},
                'message': {'type': 'text', 'id': 'm3', 'text': 'keep-3'},
                'timestamp': 0,
            },
        ]

    def test_the_other_events_survive_one_events_db_error(self):
        response = self._send(self._events())
        self.assertEqual(response.status_code, 200)

        EventLog = self.env['line.event.log'].sudo()
        kept = EventLog.search([('text_content', 'in', ['keep-1', 'keep-3'])])
        self.assertEqual(
            len(kept), 2,
            "the other two events' line.event.log rows must survive the "
            "third event's DB error, not be rolled back with it")

    def test_the_failing_events_error_is_recorded_not_erased(self):
        # H-4, sharing this setup: the failing event must leave a trace with
        # error_msg set, and it must not be marked processed.
        self._send(self._events())

        EventLog = self.env['line.event.log'].sudo()
        follow_logs = EventLog.search([('event_type', '=', 'follow')])
        self.assertTrue(
            follow_logs, 'the follow event must leave some line.event.log '
            'trace even though its handler failed')
        self.assertTrue(
            any(log.error_msg for log in follow_logs),
            'the failing event must have error_msg set, recording why it failed')
        for log in follow_logs:
            if log.error_msg:
                self.assertFalse(log.processed, 'a failed event must not be processed=True')
                self.assertNotIn(HUGE_USER_ID, log.error_msg,
                                  'error_msg must record the exception, never the payload')

    def test_successful_events_are_marked_processed_only_after_their_handler_succeeds(self):
        self._send(self._events())

        EventLog = self.env['line.event.log'].sudo()
        for text in ('keep-1', 'keep-3'):
            log = EventLog.search([('text_content', '=', text)], limit=1)
            self.assertTrue(log, f'missing log row for {text!r}')
            self.assertTrue(log.processed, f'{text!r} handler succeeded; its log must be processed=True')
            self.assertFalse(log.error_msg, f'{text!r} succeeded; it must not carry an error_msg')
