# -*- coding: utf-8 -*-
# woow_line_bridge/models/appointment_booking.py
# 擴充 appointment.booking：加入 LINE 通知 hook
# 不修改 reservation_module 原始檔案，全用 _inherit
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AppointmentBooking(models.Model):
    """擴充 appointment.booking

    新增 LINE 通知相關欄位與 hook：
    - line_notification_sent: 標記是否已發送 LINE 通知
    - 覆寫 action_confirm / action_cancel，在原本邏輯後觸發 LINE 推播
    - action_resend_line_notification: 後台手動重發 LINE 通知按鈕
    """
    _inherit = 'appointment.booking'

    # ------------------------------------------------------------------
    # LINE 通知欄位
    # ------------------------------------------------------------------
    line_notification_sent = fields.Boolean(
        string='已發送 LINE 通知',
        default=False,
        help='預約確認時是否已發送 LINE 通知',
    )
    line_reminder_24h_sent = fields.Boolean(
        string='已發送 24h 提醒',
        default=False,
        help='是否已發送預約前 24 小時提醒',
    )
    line_reminder_2h_sent = fields.Boolean(
        string='已發送 2h 提醒',
        default=False,
        help='是否已發送預約前 2 小時提醒',
    )

    # ------------------------------------------------------------------
    # 覆寫 action_confirm：在原邏輯後推 LINE 通知
    # ------------------------------------------------------------------

    def action_confirm(self):
        """覆寫預約確認，加入 LINE 推播 hook"""
        result = super().action_confirm()

        for booking in self:
            if booking.state == 'confirmed' and not booking.line_notification_sent:
                try:
                    self.env['line.bridge'].on_booking_confirmed(booking)
                    booking.sudo().write({'line_notification_sent': True})
                except Exception:
                    _logger.exception(
                        'LINE 通知發送失敗（不影響預約確認）: booking %s',
                        booking.name,
                    )

        return result

    # ------------------------------------------------------------------
    # 覆寫 action_cancel：在原邏輯後推 LINE 通知
    # ------------------------------------------------------------------

    def action_cancel(self):
        """覆寫預約取消，加入 LINE 推播 hook"""
        result = super().action_cancel()

        for booking in self:
            if booking.state == 'cancelled':
                try:
                    self.env['line.bridge'].on_booking_cancelled(booking)
                except Exception:
                    _logger.exception(
                        'LINE 取消通知發送失敗: booking %s',
                        booking.name,
                    )

        return result

    # ------------------------------------------------------------------
    # 手動重發 LINE 通知
    # ------------------------------------------------------------------

    def action_resend_line_notification(self):
        """後台按鈕：手動重發 LINE 通知"""
        self.ensure_one()
        if self.state == 'confirmed':
            try:
                self.env['line.bridge'].on_booking_confirmed(self)
                self.sudo().write({'line_notification_sent': True})
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'LINE 通知',
                        'message': '已重新發送 LINE 預約確認通知',
                        'type': 'success',
                        'sticky': False,
                    },
                }
            except Exception:
                _logger.exception('手動重發 LINE 通知失敗: booking %s', self.name)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'LINE 通知',
                        'message': 'LINE 通知發送失敗，請查看系統日誌',
                        'type': 'danger',
                        'sticky': False,
                    },
                }
        return False

    # ------------------------------------------------------------------
    # 排程任務：LINE 提醒
    # ------------------------------------------------------------------

    @api.model
    def _cron_send_line_reminder_24h(self):
        """排程：發送預約前 24 小時 LINE 提醒"""
        now = fields.Datetime.now()
        target_start = now + timedelta(hours=24)
        target_end = now + timedelta(hours=25)

        bookings = self.sudo().search([
            ('state', '=', 'confirmed'),
            ('start_datetime', '>=', target_start),
            ('start_datetime', '<', target_end),
            ('line_reminder_24h_sent', '=', False),
        ])

        bridge = self.env['line.bridge']
        for booking in bookings:
            try:
                bridge.on_booking_reminded_24h(booking)
                booking.write({'line_reminder_24h_sent': True})
            except Exception:
                _logger.exception('24h LINE 提醒發送失敗: booking %s', booking.name)

        if bookings:
            _logger.info('24h LINE 提醒：已處理 %d 筆預約', len(bookings))

    @api.model
    def _cron_send_line_reminder_2h(self):
        """排程：發送預約前 2 小時 LINE 提醒"""
        now = fields.Datetime.now()
        target_start = now + timedelta(hours=2)
        target_end = now + timedelta(hours=2, minutes=30)

        bookings = self.sudo().search([
            ('state', '=', 'confirmed'),
            ('start_datetime', '>=', target_start),
            ('start_datetime', '<', target_end),
            ('line_reminder_2h_sent', '=', False),
        ])

        bridge = self.env['line.bridge']
        for booking in bookings:
            try:
                bridge.on_booking_reminded_2h(booking)
                booking.write({'line_reminder_2h_sent': True})
            except Exception:
                _logger.exception('2h LINE 提醒發送失敗: booking %s', booking.name)

        if bookings:
            _logger.info('2h LINE 提醒：已處理 %d 筆預約', len(bookings))
