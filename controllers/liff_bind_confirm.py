# -*- coding: utf-8 -*-
# woow_odoo_line_liff/controllers/liff_bind_confirm.py
# LINE email 對應到既有聯絡人時，收信者按確認後才綁定（見 models/line_user.py）
import logging

from odoo import SUPERUSER_ID, api, http
from odoo.http import request

_logger = logging.getLogger(__name__)

_NO_STORE = [
    ('Content-Type', 'text/html; charset=utf-8'),
    ('Cache-Control', 'no-store'),
    ('Referrer-Policy', 'no-referrer'),
    ('X-Frame-Options', 'DENY'),
]


def bind_page_env():
    """auth='none' 的路由（/liff/redirect）沒有 uid，QWeb 要用完整的 SUPERUSER 環境；
    auth='public' 的路由沿用 request.env。只用來 render 頁面。"""
    env = request.env
    return env if env.uid else api.Environment(env.cr, SUPERUSER_ID, {})


def render_bind_page(template, values, status=200):
    html = bind_page_env()['ir.qweb']._render(
        'woow_odoo_line_liff.%s' % template, values)
    return request.make_response(html, headers=_NO_STORE, status=status)


class LiffBindConfirmController(http.Controller):

    @http.route('/liff/bind/confirm', type='http', auth='public',
                methods=['GET', 'POST'], website=False, sitemap=False, csrf=True)
    def liff_bind_confirm(self, token=None, **kwargs):
        """GET 只顯示確認頁；POST（帶 CSRF token）才真的綁定。

        信件內的連結可能被郵件安全掃描器自動開啟，所以 GET 不能改任何資料，
        否則攻擊者觸發寄信後，受害者的信箱掃描器就會替他完成綁定。
        綁定完成後不在這個瀏覽器建立登入 session：要回到 LINE 重新開啟。
        """
        line_user, partner = request.env['line.user'].sudo()._check_bind_confirmation_token(token)
        if not line_user:
            return render_bind_page('liff_bind_result', {'ok': False}, status=400)
        if request.httprequest.method == 'GET':
            return render_bind_page('liff_bind_confirm_page', {
                'token': token,
                'csrf_token': request.csrf_token(),
                'line_name': line_user.display_name or 'LINE',
                'partner_name': partner.name or '',
            })
        if not line_user._confirm_pending_bind(partner):
            return render_bind_page('liff_bind_result', {'ok': False}, status=400)
        return render_bind_page('liff_bind_result', {'ok': True})
