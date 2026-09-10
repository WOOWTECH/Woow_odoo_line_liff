# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests for the 2026-09 pre-deployment security fixes.

Each test here corresponds to a finding that reached production once. They
exist so that reopening one of those holes fails the suite instead of a
customer.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..controllers.liff_redirect import LiffRedirectController, _json_for_script


@tagged('post_install', '-at_install', 'line_ci')
class TestLiffRedirectSanitising(TransactionCase):
    """B-2: the redirect bridge embeds `target` in an inline <script>."""

    def setUp(self):
        super().setUp()
        self.ctrl = LiffRedirectController()

    def test_script_terminator_is_rejected(self):
        """A target that could close the <script> block never survives."""
        for hostile in ('</script>', 'book</script><b>', 'a"></script>',
                        "book'; alert(1); //"):
            self.assertEqual(
                self.ctrl._sanitize_target(hostile), 'book',
                f'{hostile!r} should have been rejected, not echoed back')

    def test_legitimate_targets_pass_through(self):
        for good in LiffRedirectController.REDIRECT_TARGETS:
            self.assertEqual(self.ctrl._sanitize_target(good), good)
        self.assertEqual(self.ctrl._sanitize_target('booking/42'), 'booking/42')

    def test_empty_and_overlong_fall_back(self):
        self.assertEqual(self.ctrl._sanitize_target(''), 'book')
        self.assertEqual(self.ctrl._sanitize_target(None), 'book')
        self.assertEqual(self.ctrl._sanitize_target('x' * 65), 'book')

    def test_json_for_script_escapes_angle_brackets(self):
        """json.dumps alone does NOT escape < > / — that was the actual bug."""
        out = _json_for_script('</script>')
        self.assertNotIn('</script>', out)
        self.assertIn('\\u003c', out)
        self.assertIn('\\u003e', out)

    def test_book_target_default_is_not_a_hardcoded_appointment_id(self):
        """新-2: /appointment/1/schedule was hardcoded and 404'd on most
        tenants. The safe default must not assume an appointment type id."""
        self.assertNotIn('/appointment/1/',
                         LiffRedirectController.REDIRECT_TARGETS['book'])


@tagged('post_install', '-at_install', 'line_ci')
class TestLiffConfigSync(TransactionCase):
    """B-4/B-5: config writes used to blank unrelated credentials."""

    def _param(self, key):
        return self.env['ir.config_parameter'].sudo().get_param(key)

    def test_partial_write_does_not_blank_other_params(self):
        """Saving one tab must not wipe the fields on the other tabs."""
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('woow_line_base.messaging_access_token', 'TOKEN-KEEP-ME')
        ICP.set_param('woow_odoo_line_liff.shop_name', 'SHOP-KEEP-ME')

        cfg = self.env['line.liff.config'].create({
            'name': 'sync test',
            'shop_phone': '02-1234-5678',
        })
        self.assertEqual(self._param('woow_line_base.messaging_access_token'),
                         'TOKEN-KEEP-ME',
                         'creating a config wiped an existing credential')
        self.assertEqual(self._param('woow_odoo_line_liff.shop_name'),
                         'SHOP-KEEP-ME')

        cfg.write({'shop_address': 'somewhere'})
        self.assertEqual(self._param('woow_line_base.messaging_access_token'),
                         'TOKEN-KEEP-ME',
                         'writing one field wiped an existing credential')

    def test_only_one_active_config_allowed(self):
        """B-5: the sending layer is global, so a second active config would
        silently overwrite the first one's credentials."""
        self.env['line.liff.config'].create({'name': 'first'})
        # Odoo's assertRaises override calls issubclass() on the argument, so
        # it must be a single class, not a tuple.
        with self.assertRaises(UserError):
            self.env['line.liff.config'].create({'name': 'second'})

    def test_admin_fields_reach_the_keys_their_consumers_read(self):
        """H-18: these two were missing from _SYNC_FIELDS, so the settings
        page silently did nothing. The consumers read the woow_line_base.*
        namespace, not woow_odoo_line_liff.*."""
        SYNC = self.env['line.liff.config']._SYNC_FIELDS
        self.assertEqual(SYNC.get('admin_line_user_id'),
                         'woow_line_base.admin_line_user_id')
        self.assertEqual(SYNC.get('auto_line_notify'),
                         'woow_line_base.auto_line_notify')


@tagged('post_install', '-at_install', 'line_ci')
class TestNewsPublication(TransactionCase):
    """B-9: draft articles were publicly readable."""

    def test_is_published_follows_state(self):
        news = self.env['line.news'].create({'title': 'draft one'})
        self.assertEqual(news.state, 'draft')
        self.assertFalse(
            news.is_published,
            'a draft must never compute as published — the public endpoints '
            'and the ACL both key off this')

    def test_public_acl_does_not_grant_blanket_read(self):
        """Even with the controller fixed, a public ACL would let anyone read
        drafts through the stock /web/image route."""
        public = self.env.ref('base.group_public', raise_if_not_found=False)
        if not public:
            self.skipTest('base.group_public not installed')
        acl = self.env['ir.model.access'].search([
            ('model_id.model', '=', 'line.news'),
            ('group_id', '=', public.id),
            ('perm_read', '=', True),
        ])
        self.assertFalse(
            acl, f'line.news is still readable by the public group via {acl.mapped("name")}')
