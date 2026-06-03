# -*- coding: utf-8 -*-
# woow_line_bridge/controllers/liff_pages.py
# 自建 LIFF 頁面 Controller
# 渲染：會員中心 /liff/member、最新消息 /liff/news、店家位置 /liff/locations
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class LiffPagesController(http.Controller):
    """LIFF 自建頁面 Controller

    這些頁面直接在 LIFF 內顯示，不需要跳轉到 portal。
    auth='public' 因為初次打開時用戶尚未登入 Odoo。
    """

    @http.route('/liff/member', type='http', auth='public', website=True)
    def liff_member(self, **kwargs):
        """會員中心主入口頁

        6 宮格功能列表，品牌色。
        """
        ICP = request.env['ir.config_parameter'].sudo()
        liff_id = ICP.get_param('woow_line_bridge.liff_id_member', '')
        shop_name = ICP.get_param('woow_line_bridge.shop_name', 'Mark Studio 馬克健身')

        values = {
            'liff_id': liff_id,
            'shop_name': shop_name,
            'error': kwargs.get('error', ''),
        }
        return request.render('woow_line_bridge.liff_member_page', values)

    @http.route('/liff/news', type='http', auth='public', website=True)
    def liff_news(self, **kwargs):
        """最新消息頁（Phase 3 補完內容）"""
        ICP = request.env['ir.config_parameter'].sudo()
        shop_name = ICP.get_param('woow_line_bridge.shop_name', 'Mark Studio 馬克健身')

        values = {
            'shop_name': shop_name,
        }
        return request.render('woow_line_bridge.liff_news_page', values)

    @http.route('/liff/locations', type='http', auth='public', website=True)
    def liff_locations(self, **kwargs):
        """店家位置頁（Phase 3 補完地圖）"""
        ICP = request.env['ir.config_parameter'].sudo()
        shop_name = ICP.get_param('woow_line_bridge.shop_name', 'Mark Studio 馬克健身')
        shop_address = ICP.get_param('woow_line_bridge.shop_address', '')
        shop_phone = ICP.get_param('woow_line_bridge.shop_phone', '')
        shop_lat = ICP.get_param('woow_line_bridge.shop_latitude', '')
        shop_lng = ICP.get_param('woow_line_bridge.shop_longitude', '')
        shop_hours = ICP.get_param('woow_line_bridge.shop_opening_hours', '')

        values = {
            'shop_name': shop_name,
            'shop_address': shop_address,
            'shop_phone': shop_phone,
            'shop_latitude': shop_lat,
            'shop_longitude': shop_lng,
            'shop_opening_hours': shop_hours,
        }
        return request.render('woow_line_bridge.liff_locations_page', values)
