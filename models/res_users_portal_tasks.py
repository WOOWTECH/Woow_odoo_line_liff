# -*- coding: utf-8 -*-
"""A portal account may read tasks assigned to its own internal account.

The two Odoo users remain separate.  We intersect assignment with the internal
user's actual project.task record rules before a portal controller reads any
task with sudo.
"""

from odoo import SUPERUSER_ID, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _line_portal_assigned_task_ids(self, task_id=None):
        self.ensure_one()
        if (self.id != self.env.uid
                or not self.has_group('base.group_portal')
                or not self.env.registry.get('project.task')):
            return []

        counterparts = self.env['res.users'].sudo().search([
            ('partner_id', '=', self.partner_id.id),
            ('share', '=', False),
            ('active', '=', True),
            ('id', '!=', SUPERUSER_ID),
        ])
        domain = [('active', '=', True), ('project_id', '!=', False)]
        if task_id is not None:
            domain.append(('id', '=', task_id))

        task_ids = set()
        for counterpart in counterparts:
            # with_user applies the internal account's ACL and record rules.
            # Assignment is required as well; mere project access is not enough.
            tasks = self.env['project.task'].with_user(counterpart.id).with_context(
                allowed_company_ids=counterpart.company_ids.ids,
            )
            if tasks.has_access('read'):
                task_ids.update(tasks.search(
                    domain + [('user_ids', 'in', [counterpart.id])],
                ).ids)
        return sorted(task_ids)
