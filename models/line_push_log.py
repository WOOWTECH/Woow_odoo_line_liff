# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_push_log.py
# LINE 推播記錄
# 記錄每次推播的內容、狀態碼與回應，用於追蹤與除錯
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class LinePushLog(models.Model):
    """LINE 推播記錄

    記錄每次透過 LINE Messaging API 推播的結果，
    包含訊息內容、HTTP 狀態碼、回應內容等。
    """
    _name = 'line.push.log'
    _description = 'LINE 推播記錄'
    _order = 'create_date desc'

    # ------------------------------------------------------------------
    # 關聯欄位
    # ------------------------------------------------------------------
    line_user_id = fields.Many2one(
        'line.user',
        string='LINE 用戶',
        ondelete='set null',
        index=True,
        help='推播目標 LINE 用戶（multicast/broadcast 時可為空）',
    )

    # ------------------------------------------------------------------
    # 推播內容
    # ------------------------------------------------------------------
    messages = fields.Text(
        string='訊息內容',
        help='推播的 LINE messages JSON',
    )

    # ------------------------------------------------------------------
    # 回應結果
    # ------------------------------------------------------------------
    status_code = fields.Integer(
        string='HTTP 狀態碼',
        help='LINE API 回傳的 HTTP 狀態碼',
    )
    response_body = fields.Text(
        string='回應內容',
        help='LINE API 回傳的 response body',
    )
    success = fields.Boolean(
        string='成功',
        default=False,
        index=True,
        help='此次推播是否成功（HTTP 200）',
    )

    # ------------------------------------------------------------------
    # 時間（自動由 ORM 管理）
    # ------------------------------------------------------------------
    create_date = fields.Datetime(
        string='建立時間',
        readonly=True,
    )
