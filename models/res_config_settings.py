# -*- coding: utf-8 -*-
# woow_line_bridge/models/res_config_settings.py
# Bridge 擴充設定：LIFF ID、店家資訊、自動推播開關、管理員 LINE UID
# API 金鑰（login/messaging）已在 woow_line_base 定義，不重複
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------
    # 自動推播開關（mail.notification hook 用）
    # ------------------------------------------------------------------
    auto_line_notify = fields.Boolean(
        string='自動推送 LINE 通知',
        config_parameter='woow_line_base.auto_line_notify',
        help='啟用後，當任何 mail.thread 模型的追蹤欄位變更時，自動推送 LINE Flex 通知。',
    )

    # ------------------------------------------------------------------
    # 管理員 LINE User ID（Rich Menu 預覽用）
    # ------------------------------------------------------------------
    line_admin_user_id = fields.Char(
        string='管理員 LINE User ID',
        config_parameter='woow_line_base.admin_line_user_id',
        help='用於預覽 Rich Menu',
    )

    # ------------------------------------------------------------------
    # LIFF ID
    # ------------------------------------------------------------------
    line_liff_id_member = fields.Char(
        string='LIFF ID - 會員中心',
        config_parameter='woow_line_bridge.liff_id_member',
    )
    line_liff_id_news = fields.Char(
        string='LIFF ID - 最新消息',
        config_parameter='woow_line_bridge.liff_id_news',
    )
    line_liff_id_locations = fields.Char(
        string='LIFF ID - 店家位置',
        config_parameter='woow_line_bridge.liff_id_locations',
    )

    # ------------------------------------------------------------------
    # 店家資訊
    # ------------------------------------------------------------------
    line_shop_name = fields.Char(
        string='店家名稱',
        config_parameter='woow_line_bridge.shop_name',
    )
    line_shop_address = fields.Char(
        string='店家地址',
        config_parameter='woow_line_bridge.shop_address',
    )
    line_shop_phone = fields.Char(
        string='店家電話',
        config_parameter='woow_line_bridge.shop_phone',
    )
    line_shop_latitude = fields.Char(
        string='緯度',
        config_parameter='woow_line_bridge.shop_latitude',
    )
    line_shop_longitude = fields.Char(
        string='經度',
        config_parameter='woow_line_bridge.shop_longitude',
    )
    line_shop_opening_hours = fields.Char(
        string='營業時間',
        config_parameter='woow_line_bridge.shop_opening_hours',
    )

    # ------------------------------------------------------------------
    # 輔助資訊（唯讀 computed）
    # ------------------------------------------------------------------
    line_webhook_url = fields.Char(
        string='Webhook URL',
        compute='_compute_line_urls',
    )
    line_liff_endpoint_news = fields.Char(
        string='最新消息 Endpoint',
        compute='_compute_line_urls',
    )
    line_liff_endpoint_locations = fields.Char(
        string='店家位置 Endpoint',
        compute='_compute_line_urls',
    )

    @api.depends()
    def _compute_line_urls(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for record in self:
            record.line_webhook_url = f'{base_url}/line/webhook' if base_url else ''
            record.line_liff_endpoint_news = f'{base_url}/liff/news' if base_url else ''
            record.line_liff_endpoint_locations = f'{base_url}/liff/locations' if base_url else ''
