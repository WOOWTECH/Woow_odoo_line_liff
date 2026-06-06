# -*- coding: utf-8 -*-
# woow_line_bridge/models/res_partner.py
# 擴充 res.partner：加入 LINE 關聯欄位 + 馬克健身客戶管理欄位
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    """擴充 res.partner

    新增：
    - LINE 用戶關聯（One2many）
    - has_line_bound 計算欄位
    - 馬克健身特殊欄位（身體狀況、偏好時段）
    - push_to_line() 快捷方法
    """
    _inherit = 'res.partner'

    # ------------------------------------------------------------------
    # LINE 關聯
    # ------------------------------------------------------------------
    line_user_ids = fields.One2many(
        'line.user',
        'partner_id',
        string='LINE 帳號',
        help='綁定的 LINE 用戶帳號',
    )
    has_line_bound = fields.Boolean(
        string='已綁定 LINE',
        compute='_compute_has_line_bound',
        store=True,
        help='是否已綁定至少一個 LINE 帳號',
    )

    # ------------------------------------------------------------------
    # 馬克健身客戶管理欄位
    # ------------------------------------------------------------------
    body_condition_notes = fields.Text(
        string='身體狀況備註',
        help='肩頸痠痛、腰痛、過敏等身體狀況記錄',
    )
    preferred_time_slot = fields.Selection(
        selection=[
            ('morning', '早上 (09:00-12:00)'),
            ('afternoon', '下午 (12:00-17:00)'),
            ('evening', '晚上 (17:00-21:00)'),
        ],
        string='偏好時段',
        help='客戶偏好的預約時段',
    )
    last_visit_date = fields.Datetime(
        string='上次到店',
        compute='_compute_visit_stats',
        store=True,
        help='最後一次完成預約的時間',
    )
    visit_count = fields.Integer(
        string='總訪問次數',
        compute='_compute_visit_stats',
        store=True,
        help='已完成（done）的預約總次數',
    )

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------

    @api.depends('line_user_ids', 'line_user_ids.is_follower')
    def _compute_has_line_bound(self):
        for partner in self:
            partner.has_line_bound = bool(
                partner.line_user_ids.filtered(lambda lu: lu.is_follower)
            )

    @api.depends_context('lang')
    def _compute_visit_stats(self):
        """計算到店統計

        從 appointment.booking 查詢 state='done' 的記錄。
        """
        Booking = self.env['appointment.booking'].sudo()
        for partner in self:
            bookings = Booking.search([
                ('partner_id', '=', partner.id),
                ('state', '=', 'done'),
            ], order='start_datetime desc')
            partner.visit_count = len(bookings)
            partner.last_visit_date = bookings[0].start_datetime if bookings else False

    # ------------------------------------------------------------------
    # 業務方法
    # ------------------------------------------------------------------

    def push_to_line(self, msg_or_flex):
        """快捷方法：推播 LINE 通知給此聯絡人

        :param msg_or_flex: 字串（純文字）或 dict（Flex Message）
        :return: True/False
        """
        self.ensure_one()
        return self.env['line.bridge'].notify_partner(self, msg_or_flex)
