# -*- coding: utf-8 -*-
# woow_odoo_line_liff/__init__.py
# 模組根 init，載入 models 與 controllers
import logging

from . import models
from . import controllers

_logger = logging.getLogger(__name__)


def _fix_empty_login(env):
    """post_init_hook: 修正既有 LINE 用戶的空 login

    升級到 18.0.3.2.0 時針對舊資料庫做一次性補救：
    - 有 email 的 LINE 用戶 → 用 email 當 login
    - 沒 email 的 LINE 用戶 → 用 line_<uid>@line.placeholder

    未來認證流程一律經過 LiffRedirectController._safe_login，
    此 hook 只處理歷史髒資料，不需在正常路徑再跑。
    """
    env.cr.execute("""
        UPDATE res_users u
        SET login = lu.email
        FROM line_user lu
        JOIN res_partner rp ON rp.id = lu.partner_id
        WHERE u.partner_id = rp.id
          AND (u.login IS NULL OR u.login = '')
          AND lu.email IS NOT NULL AND lu.email != ''
    """)
    if env.cr.rowcount:
        _logger.info('Fixed %d LINE users with empty login (email)', env.cr.rowcount)

    env.cr.execute("""
        UPDATE res_users u
        SET login = 'line_' || lu.line_user_id || '@line.placeholder'
        FROM line_user lu
        JOIN res_partner rp ON rp.id = lu.partner_id
        WHERE u.partner_id = rp.id
          AND (u.login IS NULL OR u.login = '')
          AND (lu.email IS NULL OR lu.email = '')
          AND lu.line_user_id IS NOT NULL
    """)
    if env.cr.rowcount:
        _logger.info('Fixed %d LINE users with empty login (placeholder)', env.cr.rowcount)
