# -*- coding: utf-8 -*-
# woow_line_bridge/models/res_partner.py
# Bridge 擴充 res.partner：has_line_bound 計算欄位 + push_to_line 快捷方法
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # line_user_ids 已在 woow_line_base 定義，不重複宣告

    has_line_bound = fields.Boolean(
        string='已綁定 LINE',
        compute='_compute_has_line_bound',
        store=True,
        help='是否已綁定至少一個追蹤中的 LINE 帳號',
    )

    @api.depends('line_user_ids', 'line_user_ids.is_follower')
    def _compute_has_line_bound(self):
        for partner in self:
            partner.has_line_bound = bool(
                partner.line_user_ids.filtered(lambda lu: lu.is_follower)
            )

    def push_to_line(self, msg_or_flex):
        """快捷方法：推播 LINE 通知給此聯絡人

        :param msg_or_flex: 字串（純文字）、dict（Flex Message）或 list（messages）
        :return: True/False
        """
        self.ensure_one()
        line_users = self.line_user_ids.filtered(
            lambda lu: lu.is_follower and not lu.is_blocked and lu.notification_enabled
        )
        if not line_users:
            return False

        if isinstance(msg_or_flex, str):
            messages = [{'type': 'text', 'text': msg_or_flex}]
        elif isinstance(msg_or_flex, dict):
            messages = [{
                'type': 'flex',
                'altText': msg_or_flex.get('altText', '通知'),
                'contents': msg_or_flex.get('contents', msg_or_flex),
            }]
        else:
            messages = msg_or_flex if isinstance(msg_or_flex, list) else []

        return bool(self.env['line.api.service'].push(line_users, messages))
