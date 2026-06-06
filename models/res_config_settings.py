# -*- coding: utf-8 -*-
# woow_line_bridge/models/res_config_settings.py
# 設定頁擴充：LINE 金鑰 + 店家資訊
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    """擴充系統設定頁

    加入 LINE 相關金鑰設定與店家資訊設定，
    全部存入 ir.config_parameter。
    """
    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------
    # LINE Login Channel
    # ------------------------------------------------------------------
    line_login_channel_id = fields.Char(
        string='LINE Login Channel ID',
        config_parameter='woow_line_bridge.login_channel_id',
    )
    line_login_channel_secret = fields.Char(
        string='LINE Login Channel Secret',
        config_parameter='woow_line_bridge.login_channel_secret',
    )

    # ------------------------------------------------------------------
    # LINE Messaging API Channel
    # ------------------------------------------------------------------
    line_messaging_channel_id = fields.Char(
        string='Messaging API Channel ID',
        config_parameter='woow_line_bridge.messaging_channel_id',
    )
    line_messaging_channel_secret = fields.Char(
        string='Messaging API Channel Secret',
        config_parameter='woow_line_bridge.messaging_channel_secret',
    )
    line_messaging_access_token = fields.Char(
        string='Messaging API Access Token',
        config_parameter='woow_line_bridge.messaging_access_token',
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
    # 輔助資訊（唯讀 computed，方便管理者設定 LINE Console）
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
