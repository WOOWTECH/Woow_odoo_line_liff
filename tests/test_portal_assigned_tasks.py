# -*- coding: utf-8 -*-
"""A dual-account contact can see only their own staff-assigned tasks in Portal."""

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install', 'line_ci')
class TestPortalAssignedTasks(HttpCase):

    def setUp(self):
        super().setUp()
        if not self.env.registry.get('project.task'):
            self.skipTest('Project is optional for the LINE addon')

        Users = self.env['res.users'].sudo().with_context(no_reset_password=True)
        partner = self.env['res.partner'].sudo().create({'name': 'Portal task owner'})
        staff = Users.create({
            'name': 'Portal task owner staff',
            'login': 'line_task_owner_staff',
            'password': 'test-password-staff',
            'partner_id': partner.id,
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('project.group_project_user').id,
            ])],
        })
        portal = Users.create({
            'name': 'Portal task owner member',
            'login': 'line_task_owner_portal',
            'password': 'test-password-portal',
            'partner_id': partner.id,
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        stranger = Users.create({
            'name': 'Unrelated portal member',
            'login': 'line_task_unrelated_portal',
            'password': 'test-password-other',
            'groups_id': [(6, 0, [self.env.ref('base.group_portal').id])],
        })
        project = self.env['project.project'].sudo().create({
            'name': 'Staff only task project',
            'privacy_visibility': 'followers',
        })
        Task = self.env['project.task'].sudo().with_context(
            mail_create_nolog=True, mail_create_nosubscribe=True,
        )
        own_task = Task.create({
            'name': 'Task visible to matching portal contact',
            'project_id': project.id,
            'user_ids': [(6, 0, [staff.id])],
        })
        unrelated_task = Task.create({
            'name': 'Task without this staff assignment',
            'project_id': project.id,
        })
        self.staff = staff
        self.portal = portal
        self.stranger = stranger
        self.own_task = own_task
        self.unrelated_task = unrelated_task

    def test_partner_identity_intersects_staff_assignment_and_record_rules(self):
        portal = self.portal.with_user(self.portal)
        self.assertEqual(self.env['project.task'].with_user(self.portal).search_count([]), 0)
        self.assertEqual(portal._line_portal_assigned_task_ids(), [self.own_task.id])
        self.assertEqual(
            portal._line_portal_assigned_task_ids(self.unrelated_task.id), [],
        )
        self.assertEqual(
            self.stranger.with_user(self.stranger)._line_portal_assigned_task_ids(), [],
        )
        self.assertEqual(
            self.staff.with_user(self.staff)._line_portal_assigned_task_ids(), [],
        )

    def test_portal_home_list_and_detail_enforce_the_same_owner_rule(self):
        self.authenticate(self.portal.login, 'test-password-portal')
        home = self.url_open('/my/home')
        self.assertEqual(home.status_code, 200)
        self.assertIn('/my/assigned-tasks', home.text)
        self.assertIn('我的專案任務', home.text)

        listing = self.url_open('/my/assigned-tasks')
        self.assertEqual(listing.status_code, 200)
        self.assertIn(self.own_task.name, listing.text)
        self.assertNotIn(self.unrelated_task.name, listing.text)

        detail = self.url_open('/my/assigned-tasks/%s' % self.own_task.id)
        self.assertEqual(detail.status_code, 200)
        self.assertIn(self.own_task.name, detail.text)

        denied = self.url_open(
            '/my/assigned-tasks/%s' % self.unrelated_task.id,
            allow_redirects=False,
        )
        self.assertEqual(denied.status_code, 404)

        self.authenticate(self.stranger.login, 'test-password-other')
        denied = self.url_open(
            '/my/assigned-tasks/%s' % self.own_task.id,
            allow_redirects=False,
        )
        self.assertEqual(denied.status_code, 404)
