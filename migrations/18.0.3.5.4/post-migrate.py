"""Idempotently remove views retired before downstream version 18.0.3.3.3.

Some downstream installations reached 18.0.3.3.3 without carrying the shared
18.0.3.3.2 migration.  Repeating the cleanup at 18.0.3.5.4 ensures those
databases converge when they return to the shared release line.
"""

from odoo import SUPERUSER_ID, api


VIEW_NAMES = (
    'portal_home_assigned_tasks',
    'portal_assigned_task_breadcrumbs',
    'portal_my_assigned_tasks',
    'portal_my_assigned_task',
)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    View = env['ir.ui.view']
    views = View.search([
        ('key', 'in', ['woow_odoo_line_liff.%s' % name for name in VIEW_NAMES]),
    ])
    for name in VIEW_NAMES:
        view = env.ref('woow_odoo_line_liff.%s' % name, raise_if_not_found=False)
        if view and view._name == 'ir.ui.view':
            views |= view
    views.unlink()
