# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_flex_template.py
# LINE Flex Message 模板工廠（AbstractModel）
# 集中管理所有 Flex Message 版型，方便維護與擴充
import logging
import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Grayscale palette (matches line.flex.factory in woow_line_base)
CLR_BLACK = '#1A1A1A'
CLR_DARK = '#333333'
CLR_MID = '#666666'
CLR_LABEL = '#999999'
CLR_BORDER = '#E5E5E5'
CLR_BG = '#F5F5F5'
CLR_WHITE = '#FFFFFF'

# Semantic status colors (header accent strip only)
STATUS_SUCCESS = '#22C55E'
STATUS_ERROR = '#EF4444'
STATUS_WARNING = '#F59E0B'
STATUS_INFO = '#3B82F6'

# 星期中文對照
WEEKDAY_ZH = ['一', '二', '三', '四', '五', '六', '日']


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
            'woow_line_bridge.shop_name', '',
        )

    def _get_config(self, key, default=''):
        """取得 ir.config_parameter 值"""
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    def _liff_redirect_url(self, target):
        """組合 LIFF redirect URL（在 LINE 內開啟可自動登入）

        優先使用 liff.line.me URL（LIFF 環境），備援直接 URL。
        :param target: redirect target (book, my-bookings, profile, home)
        :return: URL string
        """
        liff_id = self._get_config('woow_line_bridge.liff_id_member', '')
        if liff_id:
            return f'https://liff.line.me/{liff_id}/{target}'
        return f'{self._get_base_url()}/liff/redirect/{target}'

    def _get_liff_id(self, page):
        """取得指定頁面的 LIFF ID

        :param page: 頁面名稱（member / news / locations）
        """
        key = f'woow_line_bridge.liff_id_{page}'
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

    def _format_booking_dt(self, booking):
        """格式化預約時間為台灣時區顯示

        :return: (date_str, time_str) 例如 ('2026/06/05 (四)', '14:30')
        """
        if not booking.start_datetime:
            return '(未指定)', ''
        tz = pytz.timezone('Asia/Taipei')
        local_dt = pytz.utc.localize(booking.start_datetime).astimezone(tz)
        weekday = WEEKDAY_ZH[local_dt.weekday()]
        date_str = local_dt.strftime(f'%Y/%m/%d ({weekday})')
        time_str = local_dt.strftime('%H:%M')
        return date_str, time_str

    @staticmethod
    def _info_row(label, value):
        """建構 info row（標籤+值 水平排列）"""
        return {
            'type': 'box',
            'layout': 'horizontal',
            'contents': [
                {
                    'type': 'text',
                    'text': label,
                    'color': CLR_LABEL,
                    'size': 'sm',
                    'flex': 0,
                },
                {
                    'type': 'text',
                    'text': str(value) if value else '-',
                    'color': CLR_DARK,
                    'size': 'sm',
                    'flex': 1,
                    'align': 'end',
                },
            ],
        }

    def _booking_header(self, title, status_color=None):
        """建構預約相關 Flex header"""
        return {
            'type': 'box',
            'layout': 'vertical',
            'paddingAll': '0px',
            'contents': [
                {
                    'type': 'box',
                    'layout': 'vertical',
                    'backgroundColor': status_color or STATUS_INFO,
                    'height': '4px',
                    'contents': [],
                },
                {
                    'type': 'box',
                    'layout': 'vertical',
                    'backgroundColor': CLR_BG,
                    'paddingAll': '16px',
                    'contents': [
                        {
                            'type': 'text',
                            'text': title,
                            'color': CLR_BLACK,
                            'weight': 'bold',
                            'size': 'lg',
                            'align': 'center',
                        },
                    ],
                },
            ],
        }

    # ------------------------------------------------------------------
    # 公開方法：歡迎訊息
    # ------------------------------------------------------------------

    def build_welcome(self, display_name=''):
        """建構歡迎 Flex Message（加好友時推送）

        :param display_name: LINE 用戶顯示名稱
        :return: Flex Message contents dict
        """
        shop_name = self._get_shop_name()
        book_url = self._liff_redirect_url('book')
        greeting = f'{display_name} 您好！' if display_name else '您好！'

        return {
            'type': 'bubble',
            'size': 'mega',
            'header': self._booking_header(f'歡迎來到{shop_name}', STATUS_INFO),
            'body': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': CLR_WHITE,
                'paddingAll': '20px',
                'spacing': 'md',
                'contents': [
                    {
                        'type': 'text',
                        'text': greeting,
                        'color': CLR_DARK,
                        'size': 'md',
                        'weight': 'bold',
                    },
                    {
                        'type': 'text',
                        'text': '感謝您加入我們的 LINE 好友！\n點擊下方按鈕開始使用服務。',
                        'color': CLR_LABEL,
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
                                    'uri': book_url,
                                },
                                'style': 'primary',
                                'color': CLR_DARK,
                                'height': 'md',
                            },
                            {
                                'type': 'button',
                                'action': {
                                    'type': 'uri',
                                    'label': '我的帳戶',
                                    'uri': self._liff_redirect_url('home'),
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
    # 公開方法：預約確認
    # ------------------------------------------------------------------

    def build_booking_confirmed(self, booking):
        """建構預約確認 Flex Message（通用基本版）"""
        return self._build_generic_booking_card(
            title='預約確認',
            status_color=STATUS_SUCCESS,
            booking=booking,
            old_state='草稿',
            new_state='已確認',
        )

    def _build_generic_booking_card(self, title, status_color, booking,
                                     old_state='', new_state='',
                                     extra_rows=None, buttons=None):
        """通用預約卡片 — bridge 層統一使用此方法

        顯示：表單類型、編號、階段變更、時間 + 查看按鈕
        """
        # 時間戳
        timestamp = ''
        if booking.write_date:
            tz = pytz.timezone('Asia/Taipei')
            local_dt = pytz.utc.localize(booking.write_date).astimezone(tz)
            timestamp = local_dt.strftime('%Y/%m/%d %H:%M')

        # 表單類型
        model_name = '預約'
        if booking.appointment_type_id:
            model_name = booking.appointment_type_id.name or '預約'

        body_contents = [
            {
                'type': 'text',
                'text': booking.name or '',
                'color': CLR_LABEL,
                'size': 'sm',
            },
            {'type': 'separator', 'margin': 'md', 'color': CLR_BORDER},
            self._info_row('表單', model_name),
        ]
        if old_state and new_state:
            body_contents.append(self._info_row('階段', f'{old_state} → {new_state}'))
        elif new_state:
            body_contents.append(self._info_row('狀態', new_state))
        if timestamp:
            body_contents.append(self._info_row('時間', timestamp))
        for label, value in (extra_rows or []):
            body_contents.append(self._info_row(label, value))

        # Default button: 查看詳情 → portal home
        if not buttons:
            buttons = [
                {'type': 'uri', 'label': '查看詳情', 'uri': self._liff_redirect_url('home')},
            ]

        footer_buttons = []
        for btn in buttons:
            btn_comp = {
                'type': 'button',
                'action': {
                    'type': btn.get('type', 'uri'),
                    'label': btn['label'],
                },
                'style': 'primary' if not footer_buttons else 'secondary',
                'height': 'sm',
            }
            if btn.get('type', 'uri') == 'uri':
                btn_comp['action']['uri'] = btn.get('uri', '')
                if not footer_buttons:
                    btn_comp['color'] = CLR_DARK
            elif btn.get('type') == 'postback':
                btn_comp['action']['data'] = btn.get('data', '')
            footer_buttons.append(btn_comp)

        return {
            'type': 'bubble',
            'size': 'mega',
            'header': self._booking_header(title, status_color),
            'body': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': CLR_WHITE,
                'paddingAll': '20px',
                'spacing': 'md',
                'contents': body_contents,
            },
            'footer': {
                'type': 'box',
                'layout': 'vertical',
                'spacing': 'sm',
                'paddingAll': '16px',
                'contents': footer_buttons,
            },
        }

    # ------------------------------------------------------------------
    # 公開方法：預約取消
    # ------------------------------------------------------------------

    def build_booking_cancelled(self, booking, reason=''):
        """建構預約取消 Flex Message（通用基本版）

        :param booking: appointment.booking record
        :param reason: 取消原因（可選）
        :return: Flex Message contents dict
        """
        extra = []
        if reason:
            extra.append(('原因', reason))
        return self._build_generic_booking_card(
            title='預約已取消',
            status_color=STATUS_ERROR,
            booking=booking,
            old_state='已確認',
            new_state='已取消',
            extra_rows=extra,
        )

    # ------------------------------------------------------------------
    # 公開方法：預約提醒
    # ------------------------------------------------------------------

    def build_booking_reminder(self, booking, hours_before=24):
        """建構預約提醒 Flex Message

        :param booking: appointment.booking record
        :param hours_before: 提前幾小時提醒
        :return: Flex Message contents dict
        """
        shop_name = self._get_shop_name()
        date_str, time_str = self._format_booking_dt(booking)
        service_name = booking.appointment_type_id.name or ''
        reminder_text = f'您的預約將在 {hours_before} 小時後開始'

        body_contents = [
            {
                'type': 'text',
                'text': reminder_text,
                'color': CLR_DARK,
                'size': 'md',
                'weight': 'bold',
                'wrap': True,
            },
            {'type': 'separator', 'margin': 'md'},
            self._info_row('預約編號', booking.name or ''),
            self._info_row('服務', service_name),
            self._info_row('時間', f'{date_str} {time_str}'),
            self._info_row('地點', shop_name),
        ]

        footer_buttons = []
        shop_lat = self._get_config('woow_line_bridge.shop_latitude')
        shop_lng = self._get_config('woow_line_bridge.shop_longitude')
        if shop_lat and shop_lng:
            footer_buttons.append({
                'type': 'button',
                'action': {
                    'type': 'uri',
                    'label': 'Google 地圖導航',
                    'uri': f'https://www.google.com/maps/dir/?api=1&destination={shop_lat},{shop_lng}',
                },
                'style': 'primary',
                'color': CLR_DARK,
            })
        footer_buttons.append({
            'type': 'button',
            'action': {
                'type': 'postback',
                'label': '取消預約',
                'data': f'action=cancel_booking&booking_id={booking.id}',
            },
            'style': 'secondary',
        })

        result = {
            'type': 'bubble',
            'size': 'mega',
            'header': self._booking_header('預約提醒', STATUS_INFO),
            'body': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': CLR_WHITE,
                'paddingAll': '20px',
                'spacing': 'md',
                'contents': body_contents,
            },
            'footer': {
                'type': 'box',
                'layout': 'vertical',
                'spacing': 'sm',
                'paddingAll': '16px',
                'contents': footer_buttons,
            },
        }
        return result

    # ------------------------------------------------------------------
    # 公開方法：待付款通知
    # ------------------------------------------------------------------

    def build_booking_payment_required(self, booking, payment_url=''):
        """建構待付款通知 Flex Message

        :param booking: appointment.booking record
        :param payment_url: 付款連結
        :return: Flex Message contents dict
        """
        date_str, time_str = self._format_booking_dt(booking)
        service_name = booking.appointment_type_id.name or ''

        body_contents = [
            {
                'type': 'text',
                'text': '您的預約需要完成付款',
                'color': CLR_DARK,
                'size': 'md',
                'weight': 'bold',
                'wrap': True,
            },
            {'type': 'separator', 'margin': 'md'},
            self._info_row('預約編號', booking.name or ''),
            self._info_row('服務', service_name),
            self._info_row('時間', f'{date_str} {time_str}'),
        ]

        footer_buttons = []
        if payment_url:
            footer_buttons.append({
                'type': 'button',
                'action': {
                    'type': 'uri',
                    'label': '立即付款',
                    'uri': payment_url,
                },
                'style': 'primary',
                'color': STATUS_SUCCESS,
            })
        footer_buttons.append({
            'type': 'button',
            'action': {
                'type': 'postback',
                'label': '取消預約',
                'data': f'action=cancel_booking&booking_id={booking.id}',
            },
            'style': 'secondary',
        })

        return {
            'type': 'bubble',
            'size': 'mega',
            'header': self._booking_header('待付款通知', STATUS_WARNING),
            'body': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': CLR_WHITE,
                'paddingAll': '20px',
                'spacing': 'md',
                'contents': body_contents,
            },
            'footer': {
                'type': 'box',
                'layout': 'vertical',
                'spacing': 'sm',
                'paddingAll': '16px',
                'contents': footer_buttons,
            },
        }

    # ------------------------------------------------------------------
    # 公開方法：新聞推播卡片
    # ------------------------------------------------------------------

    def build_news_card(self, news):
        """建構新聞推播 Flex Message

        :param news: line.news record
        :return: Flex Message contents dict
        """
        base_url = self._get_base_url()
        news_url = self._liff_url('news')
        shop_name = self._get_shop_name()

        body_contents = [
            {
                'type': 'text',
                'text': news.title or '',
                'color': CLR_DARK,
                'size': 'lg',
                'weight': 'bold',
                'wrap': True,
            },
        ]
        if news.summary:
            body_contents.append({
                'type': 'text',
                'text': news.summary,
                'color': CLR_LABEL,
                'size': 'sm',
                'wrap': True,
                'margin': 'md',
            })
        body_contents.append({
            'type': 'text',
            'text': shop_name,
            'color': CLR_LABEL,
            'size': 'xs',
            'margin': 'lg',
        })

        result = {
            'type': 'bubble',
            'size': 'mega',
            'header': self._booking_header('最新消息', STATUS_INFO),
            'body': {
                'type': 'box',
                'layout': 'vertical',
                'backgroundColor': CLR_WHITE,
                'paddingAll': '20px',
                'spacing': 'sm',
                'contents': body_contents,
            },
            'footer': {
                'type': 'box',
                'layout': 'vertical',
                'spacing': 'sm',
                'paddingAll': '16px',
                'contents': [
                    {
                        'type': 'button',
                        'action': {
                            'type': 'uri',
                            'label': '閱讀全文',
                            'uri': f'{news_url}?article_id={news.id}' if hasattr(news, 'id') else news_url,
                        },
                        'style': 'primary',
                        'color': CLR_DARK,
                    },
                ],
            },
        }

        # 如果有圖片 URL，加 hero image
        image_url = getattr(news, 'image_url', '') or ''
        if not image_url and getattr(news, 'image', None):
            image_url = f'{base_url}/web/image/line.news/{news.id}/image'
        if image_url:
            result['hero'] = {
                'type': 'image',
                'url': image_url,
                'size': 'full',
                'aspectRatio': '20:13',
                'aspectMode': 'cover',
            }

        return result
