# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Attack-surface tests: perform the attack, assert it fails.

tests/test_security_fixes.py asserts the fixes are *present*. This file asserts
the holes are *closed* — it runs the attack and checks the outcome, because
those are not the same claim. A whitelist that exists but has a gap, an ACL
that is absent but shadowed by a record rule, a sanitiser that rejects the
obvious payload but not an encoded one: all of those pass a presence check and
fail a real attempt.
"""

from contextlib import contextmanager
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged

from ..controllers import liff_redirect as liff_redirect_module
from ..controllers.liff_redirect import LiffRedirectController, _json_for_script


@contextmanager
def bound_request(env):
    """Bind a minimal `request` so controller helpers can be unit-tested.

    These helpers reach for `request.env` to get a cursor and the registry.
    Outside an HTTP request that werkzeug local is unbound, so calling them
    directly raises RuntimeError before any of the logic under test runs.
    Only `.env` is needed, so a stub carrying the test env exercises the
    real decision logic without standing up a whole HTTP stack.
    """
    class _Req:
        pass
    stub = _Req()
    stub.env = env
    with patch.object(liff_redirect_module, 'request', stub):
        yield


@tagged('post_install', '-at_install', 'line_ci')
class TestRedirectInjection(TransactionCase):
    """B-2: `target` is interpolated into an inline <script> on an auth='none',
    csrf=False endpoint that Rich Menu trains users to tap."""

    def setUp(self):
        super().setUp()
        self.ctrl = LiffRedirectController()

    def test_no_payload_survives_sanitising(self):
        """Every one of these must be rejected outright, not escaped and kept.

        Escaping is the second line of defence; the whitelist is the first, and
        a payload that reaches the escaper is already further in than it should
        be.
        """
        payloads = [
            '</script><script>alert(1)</script>',
            '"; alert(1); //',
            "'; alert(1); //',",
            '</SCRIPT >',                      # tag matching is case/space lax
            '\\u003c/script\\u003e',           # pre-escaped, hoping for a double decode
            'book\x00</script>',               # null byte truncation
            'book\n</script>',                 # newline
            'book\r\n</script>',
            '＜/script＞',                      # fullwidth look-alikes
            'javascript:alert(1)',
            'data:text/html,<script>alert(1)</script>',
            '//evil.example.com',              # protocol-relative redirect
            'https://evil.example.com',
            '../../web/session/logout',        # traversal
            'book?a=1&b=</script>',
            'x' * 200,
        ]
        for payload in payloads:
            got = self.ctrl._sanitize_target(payload)
            self.assertEqual(
                got, 'book',
                f'{payload!r} was not rejected — _sanitize_target returned {got!r}')

    def test_escaped_output_can_never_close_the_script_block(self):
        """Belt and braces: whatever does get through must not be able to end
        the block. json.dumps alone does not escape < > / — that was the
        mechanism of the original bug."""
        for value in ('</script>', '</ScRiPt>', 'a</script>b', '<!--<script>'):
            out = _json_for_script(value)
            self.assertNotIn('</script', out.lower())
            self.assertNotIn('<', out)
            self.assertNotIn('>', out)

    def test_legitimate_targets_are_not_broken_by_the_whitelist(self):
        """Over-tightening breaks every Rich Menu button in production, which
        is a worse outage than the bug. Pin the known-good set."""
        for good in LiffRedirectController.REDIRECT_TARGETS:
            self.assertEqual(self.ctrl._sanitize_target(good), good)
        self.assertEqual(self.ctrl._sanitize_target('booking/42'), 'booking/42')


@tagged('post_install', '-at_install', 'line_ci')
class TestPasswordlessLoginEscalation(TransactionCase):
    """B-3: the LIFF login writes a session directly, skipping
    _check_credentials and therefore 2FA. Without a share gate, binding a LINE
    account to an internal user's partner turns a rich-menu tap into that
    user's session.

    The escalation path found during the audit: the guest-link wizard is open
    to the lowest-privilege operator group and its partner_id carries no
    domain, so an operator can pick the CEO's contact card from a dropdown.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ctrl = LiffRedirectController()
        cls.internal = cls.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'CEO',
                'login': 'ceo_target_b3',
                'groups_id': [(6, 0, [cls.env.ref('base.group_user').id])],
            })

    def test_partner_owned_by_an_internal_user_is_refused(self):
        """The core attack. Must be refused, not silently downgraded."""
        with bound_request(self.env):
            user, blocked = self.ctrl._find_portal_user_for_partner(
                self.internal.partner_id)
        self.assertTrue(
            blocked,
            'a partner bound to an internal user was not flagged as blocked — '
            'a LIFF tap would hand out that account')
        self.assertFalse(
            user, 'the internal user was returned as a login target')

    def test_returned_user_is_always_a_share_user(self):
        portal = self.env['res.users'].with_context(
            no_reset_password=True).create({
                'name': 'genuine portal customer',
                'login': 'customer_b3',
                'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
            })
        with bound_request(self.env):
            user, blocked = self.ctrl._find_portal_user_for_partner(
                portal.partner_id)
        self.assertFalse(blocked)
        self.assertTrue(user, 'a legitimate portal customer could not log in')
        self.assertTrue(user.share, 'a non-share user was handed back')

    def test_existing_login_belonging_to_an_internal_user_is_not_reused(self):
        """The second path: _create_portal_user used to match on the login
        string alone, so colliding with an internal account's login handed that
        account over."""
        partner = self.env['res.partner'].create({'name': 'attacker contact'})
        with bound_request(self.env):
            user = self.ctrl._create_portal_user(partner, self.internal.login)
        if user:
            self.assertNotEqual(
                user.id, self.internal.id,
                'a login collision handed back the internal account')
            self.assertTrue(user.share, 'a non-share account was created/reused')
            self.assertEqual(user.partner_id.id, partner.id)


@tagged('post_install', '-at_install', 'line_ci')
class TestDraftNewsLeak(TransactionCase):
    """B-9: draft articles were readable by anyone. The controller was only one
    of three doors — the ACL door lets the stock /web/image route serve the
    same records even after the controller is fixed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.draft = cls.env['line.news'].create({'title': 'unpublished secret'})

    def test_draft_is_not_published(self):
        self.assertEqual(self.draft.state, 'draft')
        self.assertFalse(self.draft.is_published)

    def test_public_user_cannot_read_a_draft_record(self):
        """This is the /web/image bypass in model terms: the stock route reads
        the record as the requesting user, so if Public can read it, the image
        is served regardless of what our own controller does."""
        public = self.env.ref('base.public_user', raise_if_not_found=False)
        if not public:
            self.skipTest('base.public_user not present')
        with self.assertRaises(
                AccessError,
                msg='the Public user could read a draft line.news record — '
                    'the stock /web/image route will serve its cover image'):
            self.env['line.news'].with_user(public).browse(
                self.draft.id).read(['title', 'image'])

    def test_public_user_cannot_enumerate_news(self):
        public = self.env.ref('base.public_user', raise_if_not_found=False)
        if not public:
            self.skipTest('base.public_user not present')
        with self.assertRaises(AccessError):
            self.env['line.news'].with_user(public).search([])
