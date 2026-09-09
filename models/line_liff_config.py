# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/line_liff_config.py
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

    # ── 好友統計（LINE Insight API 同步） ──
    follower_count = fields.Integer('好友數', readonly=True)
    target_reach = fields.Integer('可觸及人數', readonly=True)
    blocked_count = fields.Integer('封鎖數', readonly=True)
    follower_updated_at = fields.Datetime('統計更新時間', readonly=True)

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

    # ── 自動同步到 ir.config_parameter ──

    # line.liff.config 欄位 → ir.config_parameter key 對照表
    _SYNC_FIELDS = {
        'messaging_channel_id': 'woow_line_base.messaging_channel_id',
        'messaging_channel_secret': 'woow_line_base.messaging_channel_secret',
        'messaging_access_token': 'woow_line_base.messaging_access_token',
        'login_channel_id': 'woow_line_base.login_channel_id',
        'login_channel_secret': 'woow_line_base.login_channel_secret',
        'liff_id_member': 'woow_odoo_line_liff.liff_id_member',
        'liff_id_news': 'woow_odoo_line_liff.liff_id_news',
        'liff_id_locations': 'woow_odoo_line_liff.liff_id_locations',
        'shop_name': 'woow_odoo_line_liff.shop_name',
        'shop_address': 'woow_odoo_line_liff.shop_address',
        'shop_phone': 'woow_odoo_line_liff.shop_phone',
        'shop_latitude': 'woow_odoo_line_liff.shop_latitude',
        'shop_longitude': 'woow_odoo_line_liff.shop_longitude',
        'shop_opening_hours': 'woow_odoo_line_liff.shop_opening_hours',
        'rebook_path': 'woow_odoo_line_liff.rebook_path',
        'richmenu_contact_text': 'woow_odoo_line_liff.richmenu_contact_text',
        # H-18: 這兩個 key 讀取端（mail_notification_line.py / line_richmenu.py）
        # 用的是 woow_line_base 前綴，不是 woow_odoo_line_liff — 對齊既有消費端，不要改成
        # 看起來「比較一致」但實際讀不到的 woow_odoo_line_liff.* key。
        'admin_line_user_id': 'woow_line_base.admin_line_user_id',
        'auto_line_notify': 'woow_line_base.auto_line_notify',
    }

    # B-4: falsy 值一律 skip 的規則，對 Boolean 欄位不適用 —
    # 這裡列出的欄位在同步時永遠寫入（包含 False），見 _sync_to_system_params。
    _SYNC_BOOLEAN_FIELDS = {'auto_line_notify'}

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for vals, rec in zip(vals_list, records):
            fields_to_sync = [f for f in self._SYNC_FIELDS if f in vals]
            if fields_to_sync:
                rec._sync_to_system_params(fields_to_sync)
        return records

    def write(self, vals):
        res = super().write(vals)
        fields_to_sync = [f for f in self._SYNC_FIELDS if f in vals]
        if fields_to_sync:
            for rec in self:
                rec._sync_to_system_params(fields_to_sync)
        return res

    def _sync_to_system_params(self, fields_to_sync=None):
        """將 config 欄位同步到 ir.config_parameter（line.api.service 讀取來源）

        B-4：只同步這次 create/write 實際帶到的欄位（`fields_to_sync`），而且
        falsy 值一律 skip 不寫入 —— 分頁式漸進存檔（res.config.settings 的
        related 欄位）一次只會帶到使用者正在看的那個分頁，若對全部 16 個 key
        做無條件回寫，沒被觸碰的其他分頁欄位會被空字串覆蓋掉既有憑證/設定。
        要清空某個值，請用明確的清除動作，不要依賴存檔的副作用。

        H-18：`_SYNC_BOOLEAN_FIELDS` 裡的欄位（目前只有 auto_line_notify）不吃
        上面「falsy 就 skip」這條規則 —— Boolean 只有兩態，没有「空字串 vs 未填」
        的模糊地帶，如果連 False 也 skip，這個開關就永遠關不掉（等於把「欄位沒
        同步」的死開關換成「關不掉」的死開關，換湯不換藥）。所以只要這次
        create/write 有帶到這個欄位，就無條件把目前值（True 或 False）寫進去。
        """
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        field_names = fields_to_sync if fields_to_sync is not None else list(self._SYNC_FIELDS)
        synced = 0
        for field_name in field_names:
            if field_name not in self._SYNC_FIELDS:
                continue
            param_key = self._SYNC_FIELDS[field_name]
            value = getattr(self, field_name, False)
            if field_name in self._SYNC_BOOLEAN_FIELDS:
                ICP.set_param(param_key, str(bool(value)))
                synced += 1
                continue
            if not value:
                continue
            ICP.set_param(param_key, value)
            synced += 1
        if synced:
            _logger.info('LINE config %s: 已同步 %d 個參數到 ir.config_parameter',
                         self.name, synced)

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
