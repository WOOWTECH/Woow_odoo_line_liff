# -*- coding: utf-8 -*-
"""Re-uploading one tab of a tabbed rich menu must not drop anyone back to the default menu.

2026-11-16/17 (evergreen): the officer menu has two tabs, 會員服務 and 管理工具. They switch to each other through
richmenuswitch aliases. Officers are assigned to the 會員服務 menu in Odoo (current_richmenu_id). When someone taps
the 管理工具 tab, LINE links that person to the 管理工具 menu, and Odoo never hears about it.

action_reupload_to_line() used to re-link only the users with current_richmenu_id == self. It also never repointed
the aliases. Re-uploading 管理工具 then deleted the menu those officers were really on, so they fell back to the
default menu. And the tab switch kept pointing at a deleted menu until someone repointed the alias by hand.

The LINE HTTP boundary is replaced with a fake that keeps the per-user links and aliases the way LINE would.
"""
import base64
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


class FakeLine:
    """Just enough of LINE's rich-menu state: menus, per-user links, aliases, and a call log."""

    def __init__(self):
        self.menus = set()
        self.links = {}          # line_user_id -> richMenuId
        self.aliases = {}        # alias id -> richMenuId
        self.default = None
        self.calls = []
        self.counter = 0
        self.fail_alias_update = False
        self.fail_bulk_link = False

    def install(self, test):
        Service = type(test.env['line.api.service'])
        fake = self

        def create_ex(self_, menu_data, **kw):
            fake.counter += 1
            new = f'richmenu-new-{fake.counter}'
            fake.menus.add(new)
            fake.calls.append(('create', new))
            return new, 200, ''

        def upload_ex(self_, richmenu_id, image_data, content_type='image/png', **kw):
            fake.calls.append(('image', richmenu_id))
            return True, 200, ''

        def delete_ex(self_, richmenu_id, **kw):
            fake.calls.append(('delete', richmenu_id))
            fake.menus.discard(richmenu_id)
            # LINE drops every per-user link to a deleted menu: those users fall back to the default menu
            for uid, menu in list(fake.links.items()):
                if menu == richmenu_id:
                    del fake.links[uid]
            return True, 200, ''

        def update_alias(self_, alias_id, richmenu_id, **kw):
            fake.calls.append(('alias', alias_id, richmenu_id))
            if fake.fail_alias_update:
                return False
            fake.aliases[alias_id] = richmenu_id
            return True

        def link_users(self_, richmenu_id, line_user_ids, **kw):
            fake.calls.append(('bulk_link', richmenu_id, tuple(line_user_ids)))
            if fake.fail_bulk_link:
                return False
            for uid in line_user_ids:
                fake.links[uid] = richmenu_id
            return True

        def link_user(self_, richmenu_id, line_user_id, **kw):
            fake.calls.append(('link', richmenu_id, line_user_id))
            fake.links[line_user_id] = richmenu_id
            return True

        def get_user_menu(self_, line_user_id, **kw):
            fake.calls.append(('get', line_user_id))
            return fake.links.get(line_user_id)

        def set_default(self_, richmenu_id, **kw):
            fake.calls.append(('default', richmenu_id))
            fake.default = richmenu_id
            return True

        for name, fn in {
            'richmenu_create_ex': create_ex, 'richmenu_upload_image_ex': upload_ex,
            'richmenu_delete_ex': delete_ex, 'richmenu_update_alias': update_alias,
            'richmenu_link_to_users': link_users, 'richmenu_link_to_user': link_user,
            'richmenu_get_user_menu': get_user_menu, 'richmenu_set_default': set_default,
        }.items():
            p = patch.object(Service, name, fn)
            p.start()
            test.addCleanup(p.stop)
        return self

    def menu_of(self, line_user_id):
        """What the person sees: their own link, else the default menu."""
        return self.links.get(line_user_id, self.default)


@tagged('post_install', '-at_install', 'line_ci')
class TestRichMenuReuploadTabs(TransactionCase):

    def setUp(self):
        super().setUp()
        self.line = FakeLine().install(self)
        image = base64.b64encode(b'fake-image-bytes')
        Menu = self.env['line.richmenu']

        def menu(name, line_id, switch_to, state='uploaded'):
            self.line.menus.add(line_id)
            return Menu.create({
                'name': name, 'line_richmenu_id': line_id, 'state': state,
                'image': image, 'image_filename': 'menu.png',
                'area_ids': [
                    (0, 0, {'x': 0, 'y': 0, 'width': 1250, 'height': 200,
                            'action_type': 'richmenuswitch', 'action_value': switch_to}),
                    (0, 0, {'x': 1250, 'y': 0, 'width': 1250, 'height': 200,
                            'action_type': 'message', 'action_value': 'hi'}),
                ],
            })

        self.main = menu('一般選單', 'richmenu-main', 'tab-x-unused', state='active')
        self.main.is_default = True
        self.line.default = 'richmenu-main'
        self.home = menu('幹部－會員服務', 'richmenu-home-old', 'tab-admin')
        self.admin = menu('幹部－管理工具', 'richmenu-admin-old', 'tab-home')
        Alias = self.env['line.richmenu.alias']
        for alias_id, target in (('tab-home', self.home), ('tab-admin', self.admin)):
            Alias.create({'alias_id': alias_id, 'richmenu_id': target.id, 'line_alias_id': alias_id})
            self.line.aliases[alias_id] = target.line_richmenu_id

        LineUser = self.env['line.user']
        # officers: assigned to the 會員服務 tab in Odoo
        self.on_home = LineUser.create({'line_user_id': 'U-on-home', 'current_richmenu_id': self.home.id})
        self.switched = LineUser.create({'line_user_id': 'U-switched', 'current_richmenu_id': self.home.id})
        # an officer assigned straight to 管理工具 who has tapped over to 會員服務
        self.admin_on_home = LineUser.create({'line_user_id': 'U-admin-on-home',
                                              'current_richmenu_id': self.admin.id})
        # an ordinary member on the default menu
        self.member = LineUser.create({'line_user_id': 'U-member'})
        self.line.links.update({
            'U-on-home': 'richmenu-home-old',
            'U-switched': 'richmenu-admin-old',      # tapped 管理工具: LINE linked them there
            'U-admin-on-home': 'richmenu-home-old',
        })
        self.line.calls.clear()

    def _new_id(self, menu):
        menu.invalidate_recordset()
        return menu.line_richmenu_id

    def test_reupload_keeps_everyone_on_the_tab_they_were_on(self):
        self.admin.action_reupload_to_line()
        new_admin = self._new_id(self.admin)

        self.assertNotEqual(new_admin, 'richmenu-admin-old')
        self.assertNotIn('richmenu-admin-old', self.line.menus, 'old menu should be deleted')
        # the officer who had tapped over to 管理工具 is on the new 管理工具, not on the default menu
        self.assertEqual(self.line.menu_of('U-switched'), new_admin)
        # nobody else moved
        self.assertEqual(self.line.menu_of('U-on-home'), 'richmenu-home-old')
        self.assertEqual(self.line.menu_of('U-admin-on-home'), 'richmenu-home-old',
                         'someone assigned to 管理工具 but on 會員服務 must not be pulled back')
        self.assertEqual(self.line.menu_of('U-member'), 'richmenu-main')
        # Odoo assignments are unchanged
        self.assertEqual(self.switched.current_richmenu_id, self.home)

    def test_reupload_repoints_the_alias_before_deleting_the_old_menu(self):
        self.admin.action_reupload_to_line()
        new_admin = self._new_id(self.admin)

        self.assertEqual(self.line.aliases['tab-admin'], new_admin)
        self.assertEqual(self.line.aliases['tab-home'], 'richmenu-home-old')
        kinds = [c[0] for c in self.line.calls]
        self.assertLess(kinds.index('alias'), kinds.index('delete'))
        self.assertLess(kinds.index('bulk_link'), kinds.index('delete'))

    def test_failed_alias_update_cancels_and_keeps_the_old_menu(self):
        self.line.fail_alias_update = True
        with self.assertRaises(UserError):
            self.admin.action_reupload_to_line()

        self.assertIn('richmenu-admin-old', self.line.menus)
        self.assertEqual(self.line.aliases['tab-admin'], 'richmenu-admin-old')
        self.assertEqual(self.line.menu_of('U-switched'), 'richmenu-admin-old')
        created = [c[1] for c in self.line.calls if c[0] == 'create']
        self.assertTrue(created)
        self.assertNotIn(created[0], self.line.menus, 'the half-made new menu should be removed again')
        self.assertNotIn('delete', [c[0] for c in self.line.calls if c[1:] == ('richmenu-admin-old',)])

    def test_failed_relink_keeps_the_old_menu_and_warns(self):
        self.line.fail_bulk_link = True
        result = self.admin.action_reupload_to_line()

        self.assertIn('richmenu-admin-old', self.line.menus, 'old menu must stay while people are still on it')
        self.assertEqual(self.line.menu_of('U-switched'), 'richmenu-admin-old')
        self.assertEqual(result['params']['type'], 'warning')
        self.assertEqual(self.line.aliases['tab-admin'], self._new_id(self.admin))

    def test_too_many_people_to_check_keeps_the_old_menu(self):
        with patch.object(type(self.admin), '_REUPLOAD_LOOKUP_LIMIT', 1):
            result = self.admin.action_reupload_to_line()

        self.assertIn('richmenu-admin-old', self.line.menus)
        self.assertEqual(self.line.menu_of('U-switched'), 'richmenu-admin-old')
        self.assertEqual(result['params']['type'], 'warning')
        self.assertNotIn('get', [c[0] for c in self.line.calls])

    def test_reupload_of_the_assigned_tab_still_relinks_its_people(self):
        self.home.action_reupload_to_line()
        new_home = self._new_id(self.home)

        self.assertEqual(self.line.menu_of('U-on-home'), new_home)
        self.assertEqual(self.line.menu_of('U-admin-on-home'), new_home)
        self.assertEqual(self.line.menu_of('U-switched'), 'richmenu-admin-old',
                         'someone assigned to 會員服務 but on 管理工具 stays where they are')
        self.assertEqual(self.line.aliases['tab-home'], new_home)
        self.assertNotIn('richmenu-home-old', self.line.menus)

    def test_tab_from_the_default_menu_also_checks_unassigned_people(self):
        """Default menu with a tab: people with no Odoo assignment can be linked to the tab by LINE."""
        self.main.area_ids[0].action_value = 'tab-admin'
        self.line.links['U-member'] = 'richmenu-admin-old'
        self.admin.action_reupload_to_line()
        new_admin = self._new_id(self.admin)

        self.assertEqual(self.line.menu_of('U-member'), new_admin)
        self.assertEqual(self.line.menu_of('U-switched'), new_admin)

    def test_unrelated_menus_are_left_alone(self):
        """A menu outside the tab group: its people are not even looked up."""
        self.admin.action_reupload_to_line()
        looked_up = {c[1] for c in self.line.calls if c[0] == 'get'}
        self.assertEqual(looked_up, {'U-on-home', 'U-switched', 'U-admin-on-home'})
