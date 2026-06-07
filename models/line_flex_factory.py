# woow_line_bridge/models/line_flex_factory.py
# Generic LINE Flex Message factory — grayscale + semantic status colors
# Any module can call env['line.flex.factory'].build_notification(...)
import logging
import re
import pytz

from odoo import api, models

_logger = logging.getLogger(__name__)

# ── Grayscale palette ───────────────────────────────────────────
CLR_BLACK = '#1A1A1A'
CLR_DARK = '#333333'
CLR_MID = '#666666'
CLR_LABEL = '#999999'
CLR_BORDER = '#E5E5E5'
CLR_BG = '#F5F5F5'
CLR_WHITE = '#FFFFFF'

# ── Semantic status (header accent strip only) ──────────────────
STATUS_COLORS = {
    'success': '#22C55E',
    'error':   '#EF4444',
    'warning': '#F59E0B',
    'info':    '#3B82F6',
}
DEFAULT_STATUS = 'info'


class LineFlexFactory(models.AbstractModel):
    """Generic LINE Flex Message factory — grayscale design.

    Usage from any Odoo module:
        factory = self.env['line.flex.factory']
        flex = factory.build_notification(
            event_type='success',
            title='預約確認',
            subtitle='APT00003',
            info_rows=[('服務', '專業按摩'), ('時間', '2026/06/07 14:30')],
            buttons=[{'label': '查看詳情', 'uri': 'https://...'}],
        )
    """
    _name = 'line.flex.factory'
    _description = 'Generic LINE Flex Message Factory'

    # ── Public API ──────────────────────────────────────────────

    def build_notification(self, event_type, title, subtitle='',
                           info_rows=None, buttons=None, timestamp=''):
        """Build a generic grayscale Flex bubble.

        :param event_type: 'success' | 'error' | 'warning' | 'info'
        :param title: Main title text (e.g. '預約確認', '設備已借出')
        :param subtitle: Secondary text (e.g. record reference 'APT00003')
        :param info_rows: list of (label, value) tuples
        :param buttons: list of dicts with 'label' and 'uri' or 'postback'
        :param timestamp: Optional timestamp string
        :return: Flex Message contents dict (bubble)
        """
        info_rows = info_rows or []
        buttons = buttons or []
        status_color = STATUS_COLORS.get(event_type, STATUS_COLORS[DEFAULT_STATUS])

        header = self._build_header(title, status_color)

        body_contents = []
        if subtitle:
            body_contents.append({
                'type': 'text',
                'text': subtitle,
                'color': CLR_LABEL,
                'size': 'sm',
            })
        if info_rows:
            body_contents.append({'type': 'separator', 'margin': 'md', 'color': CLR_BORDER})
            for label, value in info_rows:
                body_contents.append(self._build_info_row(label, value))
        if timestamp:
            body_contents.append({'type': 'separator', 'margin': 'md', 'color': CLR_BORDER})
            body_contents.append({
                'type': 'text',
                'text': timestamp,
                'color': CLR_LABEL,
                'size': 'xs',
                'margin': 'md',
            })

        body = {
            'type': 'box',
            'layout': 'vertical',
            'backgroundColor': CLR_WHITE,
            'paddingAll': '20px',
            'spacing': 'md',
            'contents': body_contents,
        }

        bubble = {
            'type': 'bubble',
            'size': 'mega',
            'header': header,
            'body': body,
        }

        if buttons:
            bubble['footer'] = self._build_footer(buttons)

        return bubble

    def build_tracking_notification(self, message, partner=None):
        """Build a Flex bubble from a mail.message with tracking values.

        :param message: mail.message record
        :param partner: res.partner record (optional, for context)
        :return: (flex_contents, alt_text) tuple, or (None, None) if no content
        """
        if not message:
            return None, None

        record_name = message.record_name or ''
        model_name = message.model or ''
        subject = message.subject or record_name or 'Notification'

        event_type = 'info'
        info_rows = []

        tracking_values = message.tracking_value_ids if hasattr(message, 'tracking_value_ids') else []
        for tv in tracking_values:
            old_val = tv.old_value_char or tv.old_value_text or str(tv.old_value_integer or tv.old_value_float or tv.old_value_monetary or '')
            new_val = tv.new_value_char or tv.new_value_text or str(tv.new_value_integer or tv.new_value_float or tv.new_value_monetary or '')
            field_desc = tv.field_desc or tv.field_id.field_description or ''

            if old_val or new_val:
                info_rows.append((field_desc, f'{old_val} → {new_val}'))

            new_lower = (new_val or '').lower()
            if new_lower in ('done', 'confirmed', 'paid', 'approved', 'completed'):
                event_type = 'success'
            elif new_lower in ('cancelled', 'cancel', 'rejected', 'failed', 'refused'):
                event_type = 'error'
            elif new_lower in ('pending', 'waiting', 'draft', 'to_approve'):
                event_type = 'warning'

        if not info_rows:
            body_text = message.body or ''
            if body_text:
                clean = re.sub(r'<[^>]+>', '', body_text).strip()
                if clean:
                    info_rows.append(('', clean[:100]))

        if not info_rows:
            return None, None

        buttons = []
        doc_url = self._get_document_url(model_name, message.res_id)
        if doc_url:
            buttons.append({'label': '查看詳情', 'uri': doc_url})

        timestamp = ''
        if message.date:
            tz = pytz.timezone('Asia/Taipei')
            local_dt = pytz.utc.localize(message.date).astimezone(tz)
            timestamp = local_dt.strftime('%Y/%m/%d %H:%M')

        model_display = ''
        if model_name:
            try:
                model_display = self.env['ir.model'].sudo().search(
                    [('model', '=', model_name)], limit=1
                ).name or ''
            except Exception:
                pass
        subtitle = record_name
        if model_display and record_name:
            subtitle = f'{model_display} - {record_name}'

        flex = self.build_notification(
            event_type=event_type,
            title=subject,
            subtitle=subtitle,
            info_rows=info_rows,
            buttons=buttons,
            timestamp=timestamp,
        )

        alt_text = f'{subject} - {record_name}' if record_name else subject
        return flex, alt_text

    # ── Private helpers ─────────────────────────────────────────

    def _build_header(self, title, status_color):
        """Header with 4px semantic color accent strip on top."""
        return {
            'type': 'box',
            'layout': 'vertical',
            'paddingAll': '0px',
            'contents': [
                {
                    'type': 'box',
                    'layout': 'vertical',
                    'backgroundColor': status_color,
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

    @staticmethod
    def _build_info_row(label, value):
        """Horizontal label-value row in grayscale."""
        if not label:
            return {
                'type': 'text',
                'text': str(value) if value else '-',
                'color': CLR_DARK,
                'size': 'sm',
                'wrap': True,
            }
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
                    'wrap': True,
                },
            ],
        }

    @staticmethod
    def _build_footer(buttons):
        """Footer with grayscale action buttons."""
        btn_components = []
        for i, btn in enumerate(buttons):
            if 'uri' in btn:
                action = {'type': 'uri', 'label': btn['label'], 'uri': btn['uri']}
            elif 'postback' in btn:
                action = {'type': 'postback', 'label': btn['label'], 'data': btn['postback']}
            else:
                continue

            style = 'primary' if i == 0 else 'secondary'
            btn_comp = {
                'type': 'button',
                'action': action,
                'style': style,
                'height': 'sm',
            }
            if style == 'primary':
                btn_comp['color'] = CLR_DARK
            btn_components.append(btn_comp)

        return {
            'type': 'box',
            'layout': 'vertical',
            'spacing': 'sm',
            'paddingAll': '16px',
            'contents': btn_components,
        }

    def _get_document_url(self, model, res_id):
        """Return portal home URL via LIFF for authenticated access in LINE."""
        liff_id = self.env['ir.config_parameter'].sudo().get_param(
            'woow_line_bridge.liff_id_member', '') or self.env[
            'ir.config_parameter'].sudo().get_param('woow_line_base.liff_id', '')
        if liff_id:
            return 'https://liff.line.me/%s/home' % liff_id
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        return '%s/liff/redirect/home' % base_url if base_url else ''
