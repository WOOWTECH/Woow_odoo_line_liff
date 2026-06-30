# -*- coding: utf-8 -*-
# woow_odoo_line_liff/models/mail_notification_line.py
# Hook mail.notification.create() to auto-push LINE Flex Messages
# When a notification targets a partner with bound LINE user(s),
# build a generic Flex from mail.message tracking data and push.
import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class MailNotificationLine(models.Model):
    _inherit = 'mail.notification'

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to trigger LINE push for partners with LINE users."""
        notifications = super().create(vals_list)

        # Skip if caller explicitly disabled LINE notifications
        if self.env.context.get('skip_line_notification'):
            return notifications

        # Check if auto-push is enabled
        auto_push = self.env['ir.config_parameter'].sudo().get_param(
            'woow_line_base.auto_line_notify', 'False'
        )
        if auto_push not in ('True', 'true', '1'):
            return notifications

        try:
            self._push_line_notifications(notifications)
        except Exception:
            _logger.exception('LINE auto-push top-level error (mail.notification.create unaffected)')
        return notifications

    def _push_line_notifications(self, notifications):
        """Push LINE notifications for eligible mail.notification records."""
        LineUser = self.env['line.user'].sudo()
        factory = self.env['line.flex.factory'].sudo()
        api_service = self.env['line.api.service'].sudo()

        seen_messages = set()

        for notif in notifications:
            try:
                # Process both inbox and email notifications
                # Portal users use 'email' type (Odoo 18 constraint)
                if notif.notification_type not in ('inbox', 'email'):
                    continue

                msg = notif.mail_message_id
                if not msg or msg.id in seen_messages:
                    continue

                partner = notif.res_partner_id
                if not partner:
                    continue

                line_users = LineUser.search([
                    ('partner_id', '=', partner.id),
                    ('is_follower', '=', True),
                    ('is_blocked', '=', False),
                ])
                if not line_users:
                    continue

                seen_messages.add(msg.id)

                flex, alt_text = factory.build_tracking_notification(msg, partner)
                if not flex:
                    continue

                messages = [{
                    'type': 'flex',
                    'altText': alt_text or 'Notification',
                    'contents': flex,
                }]

                api_service.push(line_users, messages)
                _logger.info(
                    'LINE auto-push: message %s → partner %s (%d LINE users)',
                    msg.id, partner.id, len(line_users),
                )
            except Exception:
                _logger.exception(
                    'LINE auto-push failed: notification %s', notif.id,
                )
