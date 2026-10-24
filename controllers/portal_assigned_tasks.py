# -*- coding: utf-8 -*-
"""Read-only Portal view of tasks assigned to the same person's staff user."""

from odoo import http
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.http import request
from odoo.tools import html2plaintext


class LineAssignedTasksPortal(CustomerPortal):

    @http.route(['/my/assigned-tasks', '/my/assigned-tasks/page/<int:page>'],
                type='http', auth='user', methods=['GET'], website=True,
                sitemap=False)
    def portal_my_assigned_tasks(self, page=1, **kw):
        if not request.env.registry.get('project.task'):
            return request.not_found()
        task_ids = request.env.user._line_portal_assigned_task_ids()
        pager = portal_pager(
            url='/my/assigned-tasks', total=len(task_ids), page=page,
            step=self._items_per_page,
        )
        tasks = request.env['project.task'].sudo().search(
            [('id', 'in', task_ids)],
            order='date_deadline asc, id desc',
            limit=self._items_per_page, offset=pager['offset'],
        )
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'line_assigned_tasks',
            'tasks': tasks,
            'pager': pager,
            'default_url': '/my/assigned-tasks',
        })
        return request.render('woow_odoo_line_liff.portal_my_assigned_tasks', values)

    @http.route('/my/assigned-tasks/<int:task_id>', type='http', auth='user',
                methods=['GET'], website=True, sitemap=False)
    def portal_my_assigned_task(self, task_id, **kw):
        if not request.env.registry.get('project.task'):
            return request.not_found()
        if task_id not in request.env.user._line_portal_assigned_task_ids(task_id):
            return request.not_found()
        task = request.env['project.task'].sudo().browse(task_id).exists()
        if not task:
            return request.not_found()
        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'line_assigned_task',
            'task': task,
            'description': html2plaintext(task.description or ''),
        })
        return request.render('woow_odoo_line_liff.portal_my_assigned_task', values)
