# -*- coding: utf-8 -*-
# woow_line_bridge/models/line_bridge.py
# 業務事件 hook 中樞（AbstractModel）
# 業務模組統一透過 bridge 推 LINE，不直接呼叫 push
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class LineBridge(models.AbstractModel):
    """LINE Bridge - 業務事件 hook 中樞

    所有業務模組要推 LINE 通知，都透過這裡的語意化方法，
    不直接呼叫 line.api.service.push()。
    這樣可以集中管理推播邏輯、模板選擇、錯誤處理。
    """
    _name = 'line.bridge'
    _description = 'LINE 業務事件 Hook 中樞'

    # ------------------------------------------------------------------
    # 輔助方法
    # ------------------------------------------------------------------

    def _get_line_users_for_partner(self, partner):
        """取得 partner 綁定的 LINE 用戶

        :param partner: res.partner record
        :return: line.user recordset
        """
        if not partner:
            return self.env['line.user']
        return self.env['line.user'].sudo().search([
            ('partner_id', '=', partner.id),
            ('is_follower', '=', True),
            ('is_blocked', '=', False),
        ])

    def _get_line_users_for_booking(self, booking):
        """取得預約對應的 LINE 用戶

        :param booking: appointment.booking record
        :return: line.user recordset
        """
        partner = booking.partner_id
        if not partner:
            return self.env['line.user']
        return self._get_line_users_for_partner(partner)

    # ------------------------------------------------------------------
    # 預約相關 hook（從 appointment.booking 觸發）
    # Phase 2 補完具體推播邏輯，目前先定義 signature
    # ------------------------------------------------------------------

    def on_booking_confirmed(self, booking):
        """預約確認時推播

        :param booking: appointment.booking record
        """
        line_users = self._get_line_users_for_booking(booking)
        if not line_users:
            _logger.debug('on_booking_confirmed: partner %s 無綁定 LINE 用戶', booking.partner_id.id)
            return

        try:
            flex = self.env['line.flex.template'].build_booking_confirmed(booking)
            messages = [{
                'type': 'flex',
                'altText': f'預約確認 - {booking.name}',
                'contents': flex,
            }]
            self.env['line.api.service'].push(line_users, messages)
            _logger.info('on_booking_confirmed: 已推播 booking %s', booking.name)
        except Exception:
            _logger.exception('on_booking_confirmed 推播失敗: booking %s', booking.name)

    def on_booking_cancelled(self, booking):
        """預約取消時推播

        :param booking: appointment.booking record
        """
        line_users = self._get_line_users_for_booking(booking)
        if not line_users:
            _logger.debug('on_booking_cancelled: partner %s 無綁定 LINE 用戶', booking.partner_id.id)
            return

        try:
            flex = self.env['line.flex.template'].build_booking_cancelled(booking)
            messages = [{
                'type': 'flex',
                'altText': f'預約已取消 - {booking.name}',
                'contents': flex,
            }]
            self.env['line.api.service'].push(line_users, messages)
            _logger.info('on_booking_cancelled: 已推播 booking %s', booking.name)
        except Exception:
            _logger.exception('on_booking_cancelled 推播失敗: booking %s', booking.name)

    def on_booking_reminded_24h(self, booking):
        """預約前 24 小時提醒

        :param booking: appointment.booking record
        """
        line_users = self._get_line_users_for_booking(booking)
        if not line_users:
            return

        try:
            flex = self.env['line.flex.template'].build_booking_reminder(booking, hours_before=24)
            messages = [{
                'type': 'flex',
                'altText': f'預約提醒 - {booking.name}（24小時前）',
                'contents': flex,
            }]
            self.env['line.api.service'].push(line_users, messages)
            _logger.info('on_booking_reminded_24h: 已推播 booking %s', booking.name)
        except Exception:
            _logger.exception('on_booking_reminded_24h 推播失敗: booking %s', booking.name)

    def on_booking_reminded_2h(self, booking):
        """預約前 2 小時提醒

        :param booking: appointment.booking record
        """
        line_users = self._get_line_users_for_booking(booking)
        if not line_users:
            return

        try:
            flex = self.env['line.flex.template'].build_booking_reminder(booking, hours_before=2)
            messages = [{
                'type': 'flex',
                'altText': f'預約提醒 - {booking.name}（2小時前）',
                'contents': flex,
            }]
            self.env['line.api.service'].push(line_users, messages)
            _logger.info('on_booking_reminded_2h: 已推播 booking %s', booking.name)
        except Exception:
            _logger.exception('on_booking_reminded_2h 推播失敗: booking %s', booking.name)

    def on_booking_payment_required(self, booking, payment_url=''):
        """預約需付款時推播

        :param booking: appointment.booking record
        :param payment_url: 付款連結
        """
        line_users = self._get_line_users_for_booking(booking)
        if not line_users:
            return

        try:
            flex = self.env['line.flex.template'].build_booking_payment_required(
                booking, payment_url=payment_url,
            )
            messages = [{
                'type': 'flex',
                'altText': f'待付款 - {booking.name}',
                'contents': flex,
            }]
            self.env['line.api.service'].push(line_users, messages)
            _logger.info('on_booking_payment_required: 已推播 booking %s', booking.name)
        except Exception:
            _logger.exception('on_booking_payment_required 推播失敗: booking %s', booking.name)

    def on_booking_meeting_link_ready(self, booking, meeting_url=''):
        """預約會議連結準備好時推播

        :param booking: appointment.booking record
        :param meeting_url: 會議連結
        """
        line_users = self._get_line_users_for_booking(booking)
        if not line_users:
            return

        try:
            shop_name = self.env['line.flex.template']._get_shop_name()
            text = f'{shop_name} 會議連結已準備好\n\n預約編號：{booking.name}\n會議連結：{meeting_url}'
            messages = [{'type': 'text', 'text': text}]
            self.env['line.api.service'].push(line_users, messages)
            _logger.info('on_booking_meeting_link_ready: 已推播 booking %s', booking.name)
        except Exception:
            _logger.exception('on_booking_meeting_link_ready 推播失敗: booking %s', booking.name)

    # ------------------------------------------------------------------
    # 通用入口
    # ------------------------------------------------------------------

    def notify_partner(self, partner, msg_or_flex):
        """推播通知給指定 partner

        :param partner: res.partner record
        :param msg_or_flex: 字串（純文字）或 dict（Flex Message contents）
        """
        line_users = self._get_line_users_for_partner(partner)
        if not line_users:
            _logger.debug('notify_partner: partner %s 無綁定 LINE 用戶', partner.id)
            return False

        if isinstance(msg_or_flex, str):
            messages = [{'type': 'text', 'text': msg_or_flex}]
        elif isinstance(msg_or_flex, dict):
            messages = [{
                'type': 'flex',
                'altText': msg_or_flex.get('altText', '通知'),
                'contents': msg_or_flex.get('contents', msg_or_flex),
            }]
        else:
            messages = msg_or_flex if isinstance(msg_or_flex, list) else []

        if not messages:
            return False

        try:
            sent = self.env['line.api.service'].push(line_users, messages)
            return bool(sent)
        except Exception:
            _logger.exception('notify_partner 推播失敗: partner %s', partner.id)
            return False

    def notify_group(self, xml_id, msg_or_flex):
        """推播通知給指定群組（用 XML ID 識別的 partner 群組）

        :param xml_id: 群組的 XML ID（例如 base.group_user）
        :param msg_or_flex: 字串或 Flex dict
        """
        try:
            group = self.env.ref(xml_id, raise_if_not_found=False)
            if not group:
                _logger.warning('notify_group: 找不到群組 %s', xml_id)
                return False

            partners = group.users.mapped('partner_id') if hasattr(group, 'users') else self.env['res.partner']
            result = True
            for partner in partners:
                if not self.notify_partner(partner, msg_or_flex):
                    result = False
            return result
        except Exception:
            _logger.exception('notify_group 推播失敗: xml_id=%s', xml_id)
            return False
