# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/line_event_log.py
# LINE Webhook 事件記錄
# 純記錄表，不含業務邏輯，用於追蹤與除錯
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class LineEventLog(models.Model):
    """LINE Webhook 事件記錄

    記錄所有收到的 LINE Webhook 事件，包含原始 payload，
    方便追蹤與除錯。
    """
    _name = 'line.event.log'
    _description = 'LINE 事件記錄'
    _order = 'create_date desc'

    # ------------------------------------------------------------------
    # 關聯欄位
    # ------------------------------------------------------------------
    config_id = fields.Many2one(
        'line.liff.config', string='LINE 設定檔',
        ondelete='set null', index=True)
    line_user_id = fields.Many2one(
        'line.user',
        string='LINE 用戶',
        ondelete='set null',
        index=True,
        help='觸發此事件的 LINE 用戶',
    )

    # ------------------------------------------------------------------
    # 事件分類
    # ------------------------------------------------------------------
    event_type = fields.Selection(
        selection=[
            ('follow', '追蹤'),
            ('unfollow', '取消追蹤'),
            ('message', '訊息'),
            ('postback', 'Postback'),
            ('join', '加入群組'),
            ('leave', '離開群組'),
            ('memberJoined', '成員加入'),
            ('memberLeft', '成員離開'),
            ('beacon', 'Beacon'),
            ('accountLink', '帳號連結'),
            ('things', 'IoT 裝置'),
            ('unsend', '收回訊息'),
            ('videoPlayComplete', '影片播放完成'),
            ('other', '其他'),
        ],
        string='事件類型',
        index=True,
        help='LINE Webhook 事件類型',
    )
    message_type = fields.Selection(
        selection=[
            ('text', '文字'),
            ('image', '圖片'),
            ('video', '影片'),
            ('audio', '音訊'),
            ('location', '位置'),
            ('sticker', '貼圖'),
            ('file', '檔案'),
            ('other', '其他'),
        ],
        string='訊息類型',
        help='當事件類型為 message 時的訊息子類型',
    )

    # ------------------------------------------------------------------
    # 內容欄位
    # ------------------------------------------------------------------
    raw_payload = fields.Text(
        string='原始 Payload',
        help='完整的 LINE Webhook 事件 JSON',
    )
    text_content = fields.Char(
        string='文字內容',
        help='當訊息類型為 text 時的文字內容',
    )

    # ------------------------------------------------------------------
    # 處理狀態
    # ------------------------------------------------------------------
    processed = fields.Boolean(
        string='已處理',
        default=False,
        help='此事件是否已被業務邏輯處理',
    )
    error_msg = fields.Text(
        string='錯誤訊息',
        help='處理此事件時發生的錯誤',
    )

    # ------------------------------------------------------------------
    # 時間（自動由 ORM 管理）
    # ------------------------------------------------------------------
    create_date = fields.Datetime(
        string='建立時間',
        readonly=True,
    )
