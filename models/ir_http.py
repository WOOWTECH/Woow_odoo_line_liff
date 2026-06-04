# -*- coding: utf-8 -*-
# woow_line_bridge/models/ir_http.py
# 攔截壞 session cookie 造成的 403 錯誤
# 根因：LIFF redirect 流程曾把 uid=False 存進 session，
# 導致 Odoo session 驗證執行 WHERE id = false → SQL 型別錯誤 → 403
import logging

from odoo import models
from odoo.http import request

_logger = logging.getLogger(__name__)


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _authenticate(cls, endpoint):
        """攔截壞 session 導致的認證錯誤

        當 session cookie 的 uid 是 False (boolean) 而非 int 或 None 時，
        Odoo 的 session 驗證會 crash (integer = boolean SQL error)。
        攔截這個錯誤，清掉壞 session 後重試。
        """
        try:
            return super()._authenticate(endpoint)
        except Exception:
            # 只攔截 LIFF 相關路由的 session 錯誤
            path = request.httprequest.path or ''
            if '/liff/' in path or '/line/' in path:
                _logger.warning(
                    'Session error on %s — clearing bad session and retrying',
                    path,
                )
                try:
                    request.session.uid = None
                    request.session.login = None
                    request.session.session_token = None
                except Exception:
                    pass
                # 重試認證
                return super()._authenticate(endpoint)
            raise
