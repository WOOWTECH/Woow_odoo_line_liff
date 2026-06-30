# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/res_config_settings.py
# LINE Bridge 設定頁 — POS 風格 config 選擇器
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── POS 風格：config 選擇器 ──
    line_liff_config_id = fields.Many2one(
        'line.liff.config', string='LINE 設定檔',
        default=lambda self: self.env['line.liff.config']._get_default_config(),
    )

    # ── related 到選中的 config（可直接編輯） ──
    cfg_messaging_channel_id = fields.Char(
        related='line_liff_config_id.messaging_channel_id', readonly=False)
    cfg_messaging_channel_secret = fields.Char(
        related='line_liff_config_id.messaging_channel_secret', readonly=False)
    cfg_messaging_access_token = fields.Char(
        related='line_liff_config_id.messaging_access_token', readonly=False)
    cfg_login_channel_id = fields.Char(
        related='line_liff_config_id.login_channel_id', readonly=False)
    cfg_login_channel_secret = fields.Char(
        related='line_liff_config_id.login_channel_secret', readonly=False)
    cfg_liff_id_member = fields.Char(
        related='line_liff_config_id.liff_id_member', readonly=False)
    cfg_liff_id_news = fields.Char(
        related='line_liff_config_id.liff_id_news', readonly=False)
    cfg_liff_id_locations = fields.Char(
        related='line_liff_config_id.liff_id_locations', readonly=False)
    cfg_shop_name = fields.Char(
        related='line_liff_config_id.shop_name', readonly=False)
    cfg_shop_address = fields.Char(
        related='line_liff_config_id.shop_address', readonly=False)
    cfg_shop_phone = fields.Char(
        related='line_liff_config_id.shop_phone', readonly=False)
    cfg_shop_latitude = fields.Char(
        related='line_liff_config_id.shop_latitude', readonly=False)
    cfg_shop_longitude = fields.Char(
        related='line_liff_config_id.shop_longitude', readonly=False)
    cfg_shop_opening_hours = fields.Char(
        related='line_liff_config_id.shop_opening_hours', readonly=False)
    cfg_auto_line_notify = fields.Boolean(
        related='line_liff_config_id.auto_line_notify', readonly=False)
    cfg_admin_line_user_id = fields.Char(
        related='line_liff_config_id.admin_line_user_id', readonly=False)
    cfg_rebook_path = fields.Char(
        related='line_liff_config_id.rebook_path', readonly=False)
    cfg_richmenu_contact_text = fields.Text(
        related='line_liff_config_id.richmenu_contact_text', readonly=False)
    cfg_webhook_url = fields.Char(
        related='line_liff_config_id.webhook_url')
    cfg_liff_endpoint_news = fields.Char(
        related='line_liff_config_id.liff_endpoint_news')
    cfg_liff_endpoint_locations = fields.Char(
        related='line_liff_config_id.liff_endpoint_locations')
