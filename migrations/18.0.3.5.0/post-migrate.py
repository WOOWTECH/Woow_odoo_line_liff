"""Remove the retired store-locations LIFF page setting on upgrade.

18.0.3.5.0 removes the /liff/locations page (Leaflet + OpenStreetMap tiles) and
its LIFF ID setting. The parameter record was loaded with noupdate="1", so
removing it from data/ir_config_parameter.xml does not delete the existing row.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.config_parameter'].search([('key', '=', 'woow_odoo_line_liff.liff_id_locations')]).unlink()
    env['ir.model.data'].search([
        ('module', '=', 'woow_odoo_line_liff'),
        ('name', '=', 'config_liff_id_locations'),
    ]).unlink()
