"""Remove the retired same-contact staff-task Portal views on upgrade.

Removing XML files from a module does not remove their database views. The
home-card view would otherwise call a model method removed in this release.
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
