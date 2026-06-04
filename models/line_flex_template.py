# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_flex_template.py
# LINE Flex Message 模板工廠（AbstractModel）
# 集中管理所有 Flex Message 版型，方便維護與擴充
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# 馬克健身品牌色
BRAND_PRIMARY = '#B8956A'
BRAND_SECONDARY = '#8B6F47'
BRAND_BG = '#FAF6F2'
BRAND_CARD = '#FFFFFF'
BRAND_TEXT = '#2D2620'
BRAND_TEXT_SUB = '#6B5B4E'
LINE_GREEN = '#06C755'


class LineFlexTemplate(models.AbstractModel):
    """LINE Flex Message 模板工廠

    所有 Flex Message 版型集中在這裡，
    其他模組透過 self.env['line.flex.template'].build_xxx() 取得。
    """
    _name = 'line.flex.template'
    _description = 'LINE Flex Message 模板工廠'

    # ------------------------------------------------------------------
    # 輔助方法
    # ------------------------------------------------------------------

    def _get_base_url(self):
        """取得 Odoo 網站 base URL"""
        return self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')

    def _get_shop_name(self):
        """取得店家名稱"""
        return self.env['ir.config_parameter'].sudo().get_param(
            'woow_line_liff.shop_name', 'Mark Studio 馬克健身',
        )

    def _get_liff_id(self, page):
        """取得指定頁面的 LIFF ID

        :param page: 頁面名稱（member / news / locations）
        """
        key = f'woow_line_liff.liff_id_{page}'
        return self.env['ir.config_parameter'].sudo().get_param(key, '')

    def _liff_url(self, page):
        """組合 LIFF URL

        :param page: 頁面名稱
        :return: https://liff.line.me/{liff_id}
        """
        liff_id = self._get_liff_id(page)
        if liff_id:
            return f'https://liff.line.me/{liff_id}'
        return self._get_base_url() + f'/liff/{page}'

    # ------------------------------------------------------------------
    # 公開方法：歡迎訊息
    # ------------------------------------------------------------------

    def build_welcome(self, display_name=''):
        """建構歡迎 Flex Message（加好友時推送）

        :param display_name: LINE 用戶顯示名稱
        :return: Flex Message contents dict
        """
        shop_name = self._get_shop_name()
        member_url = self._liff_url('member')
        greeting = f'{display_name} 您好！' if display_name else '您好！'

        return {
            'type': 'bubble',
            'size': 'mega',
            'header': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': BRAND_PRIMARY,
                'paddingAll': '20px',
                'contents': [
                    {
                        'type': 'text',
                        'text': f'歡迎來到{shop_name}',
                        'color': '#FFFFFF',
                        'weight': 'bold',
                        'size': 'lg',
                        'align': 'center',
                    },
                ],
            },
            'body': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': BRAND_BG,
                'paddingAll': '20px',
                'spacing': 'md',
                'contents': [
                    {
                        'type': 'text',
                        'text': greeting,
                        'color': BRAND_TEXT,
                        'size': 'md',
                        'weight': 'bold',
                    },
                    {
                        'type': 'text',
                        'text': '感謝您加入我們的 LINE 好友！\n點擊下方按鈕開始體驗專業按摩伸展服務。',
                        'color': BRAND_TEXT_SUB,
                        'size': 'sm',
                        'wrap': True,
                    },
                    {
                        'type': 'separator',
                        'margin': 'lg',
                    },
                    {
                        'type': 'box',
                        'layout': 'vertical',
                        'margin': 'lg',
                        'spacing': 'sm',
                        'contents': [
                            {
                                'type': 'button',
                                'action': {
                                    'type': 'uri',
                                    'label': '立即預約',
                                    'uri': member_url,
                                },
                                'style': 'primary',
                                'color': BRAND_PRIMARY,
                                'height': 'md',
                            },
                            {
                                'type': 'button',
                                'action': {
                                    'type': 'uri',
                                    'label': '會員中心',
                                    'uri': member_url,
                                },
                                'style': 'secondary',
                                'height': 'md',
                            },
                        ],
                    },
                ],
            },
        }

    # ------------------------------------------------------------------
    # 公開方法：預約確認（Phase 2 補完）
    # ------------------------------------------------------------------

    def build_booking_confirmed(self, booking):
        """建構預約確認 Flex Message

        :param booking: appointment.booking record
        :return: Flex Message contents dict
        """
        shop_name = self._get_shop_name()
        base_url = self._get_base_url()

        start_dt = fields_Datetime_context_timestamp(
            self, booking.start_datetime,
        ) if booking.start_datetime else ''
        # 簡化版，Phase 2 會補完完整格式
        date_str = str(booking.start_datetime or '')

        return {
            'type': 'bubble',
            'size': 'mega',
            'header': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': BRAND_PRIMARY,
                'paddingAll': '16px',
                'contents': [
                    {
                        'type': 'text',
                        'text': '預約確認',
                        'color': '#FFFFFF',
                        'weight': 'bold',
                        'size': 'lg',
                        'align': 'center',
                    },
                ],
            },
            'body': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': BRAND_BG,
                'paddingAll': '20px',
                'spacing': 'md',
                'contents': [
                    {
                        'type': 'text',
                        'text': f'預約編號：{booking.name or ""}',
                        'color': BRAND_TEXT,
                        'size': 'md',
                        'weight': 'bold',
                    },
                    {
                        'type': 'text',
                        'text': f'服務：{booking.appointment_type_id.name or ""}',
                        'color': BRAND_TEXT_SUB,
                        'size': 'sm',
                    },
                    {
                        'type': 'text',
                        'text': f'時間：{date_str}',
                        'color': BRAND_TEXT_SUB,
                        'size': 'sm',
                    },
                    {
                        'type': 'text',
                        'text': f'地點：{shop_name}',
                        'color': BRAND_TEXT_SUB,
                        'size': 'sm',
                    },
                ],
            },
        }

    # ------------------------------------------------------------------
    # 公開方法：預約取消（Phase 2 補完）
    # ------------------------------------------------------------------

    def build_booking_cancelled(self, booking):
        """建構預約取消 Flex Message

        :param booking: appointment.booking record
        :return: Flex Message contents dict
        """
        base_url = self._get_base_url()
        member_url = self._liff_url('member')

        return {
            'type': 'bubble',
            'size': 'mega',
            'header': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': '#E74C3C',
                'paddingAll': '16px',
                'contents': [
                    {
                        'type': 'text',
                        'text': '預約已取消',
                        'color': '#FFFFFF',
                        'weight': 'bold',
                        'size': 'lg',
                        'align': 'center',
                    },
                ],
            },
            'body': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': BRAND_BG,
                'paddingAll': '20px',
                'spacing': 'md',
                'contents': [
                    {
                        'type': 'text',
                        'text': f'預約編號：{booking.name or ""}',
                        'color': BRAND_TEXT,
                        'size': 'md',
                        'weight': 'bold',
                    },
                    {
                        'type': 'text',
                        'text': f'服務：{booking.appointment_type_id.name or ""}',
                        'color': BRAND_TEXT_SUB,
                        'size': 'sm',
                    },
                    {
                        'type': 'separator',
                        'margin': 'lg',
                    },
                    {
                        'type': 'button',
                        'action': {
                            'type': 'uri',
                            'label': '重新預約',
                            'uri': member_url,
                        },
                        'style': 'primary',
                        'color': BRAND_PRIMARY,
                        'margin': 'lg',
                    },
                ],
            },
        }

    # ------------------------------------------------------------------
    # 公開方法：預約提醒（Phase 2 補完）
    # ------------------------------------------------------------------

    def build_booking_reminder(self, booking, hours_before=24):
        """建構預約提醒 Flex Message

        :param booking: appointment.booking record
        :param hours_before: 提前幾小時提醒
        :return: Flex Message contents dict
        """
        shop_name = self._get_shop_name()
        date_str = str(booking.start_datetime or '')
        reminder_text = f'您的預約將在 {hours_before} 小時後開始'

        return {
            'type': 'bubble',
            'size': 'mega',
            'header': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': BRAND_PRIMARY,
                'paddingAll': '16px',
                'contents': [
                    {
                        'type': 'text',
                        'text': '預約提醒',
                        'color': '#FFFFFF',
                        'weight': 'bold',
                        'size': 'lg',
                        'align': 'center',
                    },
                ],
            },
            'body': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': BRAND_BG,
                'paddingAll': '20px',
                'spacing': 'md',
                'contents': [
                    {
                        'type': 'text',
                        'text': reminder_text,
                        'color': BRAND_TEXT,
                        'size': 'md',
                        'weight': 'bold',
                        'wrap': True,
                    },
                    {
                        'type': 'text',
                        'text': f'預約編號：{booking.name or ""}',
                        'color': BRAND_TEXT_SUB,
                        'size': 'sm',
                    },
                    {
                        'type': 'text',
                        'text': f'服務：{booking.appointment_type_id.name or ""}',
                        'color': BRAND_TEXT_SUB,
                        'size': 'sm',
                    },
                    {
                        'type': 'text',
                        'text': f'時間：{date_str}',
                        'color': BRAND_TEXT_SUB,
                        'size': 'sm',
                    },
                    {
                        'type': 'text',
                        'text': f'地點：{shop_name}',
                        'color': BRAND_TEXT_SUB,
                        'size': 'sm',
                    },
                ],
            },
        }
