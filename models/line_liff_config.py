# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_liff_config.py
# LINE LIFF 設定檔 — 多實體架構（類似 POS config）
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LineLiffConfig(models.Model):
    """LINE LIFF 設定檔

    每筆記錄代表一個 LINE 官方帳號的完整設定，
    包含 Messaging API 憑證、LIFF IDs、店家資訊、行為設定。
    類似 POS 的 pos.config 多門市架構。
    """
    _name = 'line.liff.config'
    _description = 'LINE LIFF 設定檔'
    _order = 'sequence, id'

    # ── 基本 ──
    name = fields.Char('名稱', required=True, help='例如「Mark Studio LINE」')
    sequence = fields.Integer('排序', default=10)
    active = fields.Boolean('啟用', default=True)
    company_id = fields.Many2one(
        'res.company', string='公司',
        default=lambda self: self.env.company, required=True)

    # ── LINE Messaging API 憑證 ──
    messaging_channel_id = fields.Char('Messaging Channel ID')
    messaging_channel_secret = fields.Char('Messaging Channel Secret')
    messaging_access_token = fields.Char('Messaging Access Token')

    # ── LINE Login 憑證（LIFF token 驗證） ──
    login_channel_id = fields.Char('Login Channel ID')
    login_channel_secret = fields.Char('Login Channel Secret')

    # ── LIFF IDs ──
    liff_id_member = fields.Char('LIFF ID - 會員中心',
        help='用於 Portal 登入跳轉的 LIFF App ID')
    liff_id_news = fields.Char('LIFF ID - 最新消息')
    liff_id_locations = fields.Char('LIFF ID - 店家位置')

    # ── 店家資訊 ──
    shop_name = fields.Char('店家名稱')
    shop_address = fields.Char('店家地址')
    shop_phone = fields.Char('店家電話')
    shop_latitude = fields.Char('緯度')
    shop_longitude = fields.Char('經度')
    shop_opening_hours = fields.Char('營業時間')

    # ── 行為設定 ──
    auto_line_notify = fields.Boolean('自動 LINE 推播', default=False,
        help='追蹤欄位變更時自動推播 LINE 通知')
    admin_line_user_id = fields.Char('管理員 LINE User ID',
        help='用於 Rich Menu 預覽')
    rebook_path = fields.Char('重新預約路徑', default='/liff/redirect/book')
    richmenu_contact_text = fields.Text('聯絡回覆文字',
        default='歡迎直接傳訊息給我們，將由專人為您服務！')

    # ── 計算欄位（URL） ──
    webhook_url = fields.Char('Webhook URL', compute='_compute_urls')
    liff_endpoint_news = fields.Char('最新消息端點', compute='_compute_urls')
    liff_endpoint_locations = fields.Char('店家位置端點', compute='_compute_urls')

    def _compute_urls(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', '')
        for rec in self:
            rec.webhook_url = f'{base_url}/line/webhook/{rec.id}' if base_url and rec.id else ''
            rec.liff_endpoint_news = f'{base_url}/liff/news' if base_url else ''
            rec.liff_endpoint_locations = f'{base_url}/liff/locations' if base_url else ''

    # ── Helper 方法 ──

    def _get_api_credentials(self):
        """回傳 (channel_id, channel_secret, access_token) 供 line.api.service 使用"""
        self.ensure_one()
        return (
            self.messaging_channel_id or '',
            self.messaging_channel_secret or '',
            self.messaging_access_token or '',
        )

    @api.model
    def _get_default_config(self):
        """取得第一筆 active config（向下相容單實體模式）"""
        return self.sudo().search([('active', '=', True)], limit=1)

    @api.model
    def _get_config_by_liff_id(self, liff_id):
        """從 LIFF ID 反查 config 記錄"""
        if not liff_id:
            return self.browse()
        return self.sudo().search([
            '|', '|',
            ('liff_id_member', '=', liff_id),
            ('liff_id_news', '=', liff_id),
            ('liff_id_locations', '=', liff_id),
        ], limit=1)
