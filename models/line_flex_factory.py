# woow_odoo_line_liff/models/line_flex_factory.py
# Generic LINE Flex Message factory — grayscale + semantic status colors
# Any module can call env['line.flex.factory'].build_notification(...)
import logging
import re
import pytz

from odoo import api, models
from odoo.tools.misc import format_amount

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

    # 星期幾，週一 = 0
    _WEEKDAYS = '一二三四五六日'

    def build_tracking_notification(self, message, partner=None):
        """Build the automatic LINE notification card for a mail.message.

        H-17：卡片一律由單據本身的資料組成——依類型的中文標題、重點欄位、狀態
        變更，加上「查看詳情」按鈕。**不再**把 message.body（Odoo 剛寄出的整封
        email）剝掉標籤後塞進卡片：那會把範本的英文句子（「Hello … invited you
        for the … meeting. View」、「Your quotation … is ready for review. Do not
        hesitate to contact」）截斷在句中推給客人（2026-09-12 komibright 實測，
        2026-09-06 markstudio 真實客人收到過）。

        :param message: mail.message record
        :param partner: 這張卡片要給的 res.partner（時區、行事曆出席狀態）
        :return: (flex_contents, alt_text)，沒有訊息時回 (None, None)
        """
        if not message:
            return None, None

        record = self._notification_record(message)
        record_name = (record.display_name if record else '') or message.record_name or ''
        title, subtitle, info_rows, event_type = self._summarize_record(record, record_name, partner)

        tracking_rows, tracking_type = self._tracking_rows(message)
        info_rows = list(info_rows) + tracking_rows
        event_type = tracking_type or event_type
        if not info_rows:
            info_rows = [('', '您有一則新訊息，請點「查看詳情」查看內容')]

        buttons = []
        doc_url = self._get_document_url(message.model or '', message.res_id)
        if doc_url:
            buttons.append({'label': '查看詳情', 'uri': doc_url})

        timestamp = ''
        if message.date:
            local_dt = pytz.utc.localize(message.date).astimezone(pytz.timezone('Asia/Taipei'))
            timestamp = local_dt.strftime('%Y/%m/%d %H:%M')

        flex = self.build_notification(
            event_type=event_type,
            title=title,
            subtitle=subtitle,
            info_rows=info_rows,
            buttons=buttons,
            timestamp=timestamp,
        )
        alt_text = title if not subtitle or subtitle in title else f'{title} - {subtitle}'
        return flex, alt_text[:400]

    def _notification_record(self, message):
        """通知所屬的單據（sudo：卡片是替客人組的），找不到回 None"""
        if not message.model or not message.res_id or message.model not in self.env:
            return None
        record = self.env[message.model].sudo().browse(message.res_id)
        return record if record.exists() else None

    def _tracking_rows(self, message):
        """追蹤欄位的變更 → [(欄位, '舊 → 新')]，以及對應的狀態顏色（沒有則 None）"""
        rows, event_type = [], None
        for tv in message.sudo().tracking_value_ids:
            old_val = tv.old_value_char or tv.old_value_text or str(tv.old_value_integer or tv.old_value_float or '')
            new_val = tv.new_value_char or tv.new_value_text or str(tv.new_value_integer or tv.new_value_float or '')
            field_desc = getattr(tv, 'field_info', '') or getattr(tv, 'field_desc', '') or tv.field_id.field_description or ''
            if old_val or new_val:
                rows.append((field_desc, f'{old_val} → {new_val}'))
            new_lower = (new_val or '').lower()
            if new_lower in ('done', 'confirmed', 'paid', 'approved', 'completed'):
                event_type = 'success'
            elif new_lower in ('cancelled', 'cancel', 'rejected', 'failed', 'refused'):
                event_type = 'error'
            elif new_lower in ('pending', 'waiting', 'draft', 'to_approve'):
                event_type = 'warning'
        return rows, event_type

    def _summarize_record(self, record, record_name, partner):
        """(標題, 副標題, 資訊列, 狀態) —— 單據的中文摘要"""
        summarizers = {
            'calendar.event': self._summarize_calendar_event,
            'sale.order': self._summarize_sale_order,
            'account.move': self._summarize_invoice,
        }
        if record is not None and record._name in summarizers:
            summary = summarizers[record._name](record, partner)
            if summary:
                return summary
        model_display = ''
        if record is not None:
            # 中文沒啟用的資料庫不能指定 lang='zh_TW'（Odoo 直接 raise Invalid language
            # code，推播就整個被吞掉）——這時退回資料庫目前的語言
            lang = 'zh_TW' if self.env['res.lang']._lang_get('zh_TW') else self.env.lang
            model_display = self.env['ir.model'].with_context(lang=lang)._get(record._name).name or ''
        subtitle = f'{model_display} - {record_name}' if model_display and record_name else record_name
        return '您有一則新通知', subtitle, [], 'info'

    def _local_tz(self, *candidates):
        for name in candidates:
            if name:
                try:
                    return pytz.timezone(name)
                except pytz.UnknownTimeZoneError:
                    continue
        return pytz.timezone('Asia/Taipei')

    def _summarize_calendar_event(self, event, partner):
        if event.allday and event.start_date:
            day = event.start_date
            when_short = f'{day.month}/{day.day}（{self._WEEKDAYS[day.weekday()]}）'
            when = f'{when_short} 全天'
        else:
            tz = self._local_tz(event.event_tz, partner.tz if partner else False)
            start = pytz.utc.localize(event.start).astimezone(tz)
            stop = pytz.utc.localize(event.stop).astimezone(tz)
            when_short = f'{start.month}/{start.day}（{self._WEEKDAYS[start.weekday()]}）{start:%H:%M}'
            when = f'{when_short}–{stop:%H:%M}'
        if not event.active:
            kind, event_type = '活動已取消', 'error'
        else:
            attendee = event.attendee_ids.filtered(lambda a: partner and a.partner_id == partner)[:1]
            kind = '活動提醒' if attendee.state in ('accepted', 'tentative') else '活動邀請'
            event_type = 'info'
        rows = [('時間', when)]
        if event.location:
            rows.append(('地點', event.location))
        return f'{kind} {when_short}', event.name or '', rows, event_type

    def _summarize_sale_order(self, order, partner):
        kind = '報價單' if order.state in ('draft', 'sent') else '銷售訂單'
        rows = [('金額', format_amount(self.env, order.amount_total, order.currency_id))]
        if order.state in ('draft', 'sent') and order.validity_date:
            rows.append(('有效期限', order.validity_date.strftime('%Y/%m/%d')))
        return f'{kind} {order.name}', order.company_id.name or '', rows, 'info'

    def _summarize_invoice(self, move, partner):
        if move.move_type not in ('out_invoice', 'out_refund'):
            return None
        kind = '發票' if move.move_type == 'out_invoice' else '折讓單'
        rows = [('金額', format_amount(self.env, move.amount_total, move.currency_id))]
        if move.move_type == 'out_invoice' and move.invoice_date_due:
            rows.append(('付款期限', move.invoice_date_due.strftime('%Y/%m/%d')))
        return f'{kind} {move.name}', move.company_id.name or '', rows, 'info'

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
            'woow_odoo_line_liff.liff_id_member', '')
        if liff_id:
            return 'https://liff.line.me/%s/home' % liff_id
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        return '%s/liff/redirect/home' % base_url if base_url else ''
