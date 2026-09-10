"""Two repairs that have both already bitten production tenants.

1. Orphaned `ir.config_parameter` xml_ids — same failure as in
   woow_line_base's migration of this version: the parameter row was deleted
   and recreated, the xml_id still points at the old id, and `-u` dies on
   `ir_config_parameter_key_uniq`. Seen on mujimed (all 11 liff parameters).

2. Residue from the `woow_line_bridge` → `woow_odoo_line_liff` rename. The
   module was renamed without a migration, so the old module's xml_ids were
   left behind — 327 of them on komibright, which produced a duplicate LINE
   root menu, duplicated columns on the contact form, duplicated search
   filters, two LINE blocks in Settings, and a stale `line.news.public` ACL
   that kept granting the Public group read access on line.news.

   IMPORTANT: 256 of those rows point at the SAME records this module owns
   (193 ir.model.fields, 46 selections, 15 models, 2 inherits). Their
   ir_model_data rows are deleted here, never the records — letting Odoo's
   uninstall machinery reach those ir.model.fields would DROP the real table
   columns holding the customer LINE bindings.
"""

import logging

_logger = logging.getLogger(__name__)

MODULE = 'woow_odoo_line_liff'
LEGACY = 'woow_line_bridge'

# Records the legacy module duplicated outright. Their metadata AND the record
# are removed, in this order — menus point at actions, actions at views.
DUPLICATED_MODELS = ('ir.ui.menu', 'ir.actions.act_window', 'ir.ui.view',
                     'ir.model.access')

# Records whose metadata we drop but which must stay: on at least one tenant
# these were the ONLY copies of rules the customer relies on.
KEEP_RECORD_MODELS = ('line.auto.reply', 'ir.model.constraint')


def _repair_orphaned_params(cr):
    cr.execute("""
        SELECT d.id, d.name, d.res_id
          FROM ir_model_data d
         WHERE d.module = %s
           AND d.model = 'ir.config_parameter'
           AND NOT EXISTS (
                 SELECT 1 FROM ir_config_parameter p WHERE p.id = d.res_id)
    """, (MODULE,))
    orphans = cr.fetchall()
    for imd_id, name, old_res_id in orphans:
        suffix = name[len('config_'):] if name.startswith('config_') else name
        cr.execute("""
            SELECT p.id FROM ir_config_parameter p
             WHERE p.key LIKE %s
               AND NOT EXISTS (
                     SELECT 1 FROM ir_model_data d2
                      WHERE d2.model = 'ir.config_parameter'
                        AND d2.res_id = p.id AND d2.id <> %s)
             ORDER BY p.id LIMIT 1
        """, ('%%.%s' % suffix, imd_id))
        row = cr.fetchone()
        if row:
            cr.execute("UPDATE ir_model_data SET res_id = %s WHERE id = %s",
                       (row[0], imd_id))
            _logger.info('%s: repointed %s from %s to %s', MODULE, name,
                         old_res_id, row[0])
        else:
            cr.execute("DELETE FROM ir_model_data WHERE id = %s", (imd_id,))
    if orphans:
        _logger.warning('%s: repaired %d orphaned config-parameter xml_ids',
                        MODULE, len(orphans))


def _clear_legacy_residue(cr):
    cr.execute("SELECT count(*) FROM ir_model_data WHERE module = %s", (LEGACY,))
    total = cr.fetchone()[0]
    if not total:
        return

    # 1. Records this module also owns, or that no longer exist: metadata only.
    cr.execute("""
        DELETE FROM ir_model_data legacy
         WHERE legacy.module = %s
           AND legacy.model NOT IN %s
           AND legacy.model NOT IN %s
    """, (LEGACY, DUPLICATED_MODELS, KEEP_RECORD_MODELS))
    shared = cr.rowcount

    # 2. Records that only the legacy module ever owned and that duplicate
    #    this module's UI. Skip anything this module also claims.
    removed = {}
    for model in DUPLICATED_MODELS:
        table = model.replace('.', '_')
        cr.execute("""
            SELECT legacy.id, legacy.res_id
              FROM ir_model_data legacy
             WHERE legacy.module = %s AND legacy.model = %s
               AND NOT EXISTS (
                     SELECT 1 FROM ir_model_data live
                      WHERE live.module = %s AND live.model = legacy.model
                        AND live.res_id = legacy.res_id)
        """, (LEGACY, model, MODULE))
        rows = cr.fetchall()
        if not rows:
            continue
        imd_ids = tuple(r[0] for r in rows)
        res_ids = tuple(r[1] for r in rows)
        cr.execute("DELETE FROM ir_model_data WHERE id IN %s", (imd_ids,))
        cr.execute("DELETE FROM %s WHERE id IN %%s" % table, (res_ids,))
        removed[model] = len(rows)

    # 3. Keep the records, drop only the ownership link.
    cr.execute("DELETE FROM ir_model_data WHERE module = %s AND model IN %s",
               (LEGACY, KEEP_RECORD_MODELS))
    kept = cr.rowcount

    cr.execute("SELECT count(*) FROM ir_model_data WHERE module = %s", (LEGACY,))
    left = cr.fetchone()[0]
    _logger.warning(
        '%s: cleared %d %s xml_ids — %d metadata-only (records shared with '
        'this module and left untouched), %s removed as duplicates, %d links '
        'dropped with the record kept; %d remaining',
        MODULE, total, LEGACY, shared, removed or '{}', kept, left)


def migrate(cr, version):
    if not version:
        return
    _repair_orphaned_params(cr)
    _clear_legacy_residue(cr)
