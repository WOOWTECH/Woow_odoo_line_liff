# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The LINE secrets on the Settings page are for system administrators only.

The Settings page fields are `related` to the selected `line.liff.config` and are
computed as superuser. When the config picker changes, the web client sends a
follow-up `res.config.settings.onchange`: it skips `default_get` and, on a new
record, checks no model access, so any logged-in user (every LINE member who
opens the LIFF gets a portal account) could ask for these fields over RPC.
Attack-style: ask for each secret alone on that path and check it is refused,
with a non-secret field on the same path as the control.
"""

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user, tagged

SOURCE = {
    'cfg_messaging_channel_secret': 'messaging_channel_secret',
    'cfg_messaging_access_token': 'messaging_access_token',
    'cfg_login_channel_secret': 'login_channel_secret',
}
SECRETS = tuple(SOURCE)
FAKE = {
    'messaging_channel_id': 'liffguard-fake-channel-id',  # not a secret: the control
    'messaging_channel_secret': 'liffguard-fake-msg-secret',
    'messaging_access_token': 'liffguard-fake-msg-token',
    'login_channel_secret': 'liffguard-fake-login-secret',
}


@tagged('post_install', '-at_install', 'line_ci')
class TestSettingsSecretAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # One active config per database (see _check_single_active_config): reuse it when the
        # database has one, otherwise create one.
        Config = cls.env['line.liff.config']
        cls.config = Config._get_default_config()
        if cls.config:
            cls.config.write(FAKE)
        else:
            cls.config = Config.create(dict(FAKE, name='LIFFGUARD test config'))
        cls.employee = new_test_user(cls.env, login='liffguard_employee', groups='base.group_user')
        cls.portal = new_test_user(cls.env, login='liffguard_portal', groups='base.group_portal')
        cls.admin = new_test_user(cls.env, login='liffguard_admin', groups='base.group_user,base.group_system')

    def _picker_onchange(self, user, *names):
        """The follow-up onchange the web client sends when the config picker changes."""
        spec = {name: {} for name in ('line_liff_config_id',) + names}
        return self.env['res.config.settings'].with_user(user).onchange(
            {'line_liff_config_id': self.config.id}, ['line_liff_config_id'], spec)['value']

    def test_non_admins_do_not_get_line_secrets(self):
        for user in (self.employee, self.portal):
            with self.subTest(user=user.login):
                control = self._picker_onchange(user, 'cfg_messaging_channel_id')
                self.assertEqual(control.get('cfg_messaging_channel_id'), FAKE['messaging_channel_id'])
                for name in SECRETS:
                    with self.subTest(field=name), self.assertRaises(AccessError):
                        self._picker_onchange(user, name)

    def test_admin_still_gets_line_secrets(self):
        values = self._picker_onchange(self.admin, *SECRETS)
        for name, source in SOURCE.items():
            self.assertEqual(values.get(name), FAKE[source])
