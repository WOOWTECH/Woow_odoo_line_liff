# -*- coding: utf-8 -*-
# woow_line_bridge/models/res_config_settings.py
# 設定頁擴充：LIFF ID + 店家資訊
# LINE Login / Messaging API 金鑰已移至 woow_line_base
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    """擴充系統設定頁

    加入 LIFF ID 與店家資訊設定，全部存入 ir.config_parameter。
    LINE Login / Messaging API 金鑰由 woow_line_base 提供。
    """
    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------
    # LIFF ID
    # ------------------------------------------------------------------
    line_liff_id_member = fields.Char(
        string='LIFF ID - 會員中心',
        config_parameter='woow_line_liff.liff_id_member',
    )
    line_liff_id_news = fields.Char(
        string='LIFF ID - 最新消息',
        config_parameter='woow_line_liff.liff_id_news',
    )
    line_liff_id_locations = fields.Char(
        string='LIFF ID - 店家位置',
        config_parameter='woow_line_liff.liff_id_locations',
    )

    # ------------------------------------------------------------------
    # 店家資訊
    # ------------------------------------------------------------------
    line_shop_name = fields.Char(
        string='店家名稱',
        config_parameter='woow_line_liff.shop_name',
    )
    line_shop_address = fields.Char(
        string='店家地址',
        config_parameter='woow_line_liff.shop_address',
    )
    line_shop_phone = fields.Char(
        string='店家電話',
        config_parameter='woow_line_liff.shop_phone',
    )
    line_shop_latitude = fields.Char(
        string='緯度',
        config_parameter='woow_line_liff.shop_latitude',
    )
    line_shop_longitude = fields.Char(
        string='經度',
        config_parameter='woow_line_liff.shop_longitude',
    )
    line_shop_opening_hours = fields.Char(
        string='營業時間',
        config_parameter='woow_line_liff.shop_opening_hours',
    )
