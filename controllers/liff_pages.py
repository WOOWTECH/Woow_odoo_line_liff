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

    def _heal_session(self):
        """清除可能壞掉的 session

        LIFF 頁面不需要 Odoo session（auth=public），
        如果帶著壞 session cookie 來會導致 403。
        直接 logout 清掉，讓頁面正常渲染。
        """
        try:
            if request.session.uid:
                request.session.logout(keep_db=True)
        except Exception:
            try:
                request.session.uid = False
                request.session.login = None
            except Exception:
                pass

    @http.route('/liff/clear-session', type='http', auth='none', csrf=False,
                save_session=False)
    def liff_clear_session(self, **kwargs):
        """清除壞掉的 session 並重導回 LIFF member 頁面

        當 LIFF 登入產生壞 session 時，所有頁面都會 403。
        這個 auth='none' 的端點不會觸發 session 驗證，
        所以可以安全地清除 session 後重導。
        """
        redirect_to = kwargs.get('r', '/liff/member')
        # 清除 session
        request.session.uid = False
        request.session.login = None
        _logger.info('已清除壞 session，重導到 %s', redirect_to)
        return request.redirect(redirect_to)

    @http.route('/liff/member', type='http', auth='public', website=True)
    def liff_member(self, **kwargs):
        """會員中心主入口頁

        6 宮格功能列表，品牌色。
        """
        self._heal_session()

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

    @http.route('/liff/debug', type='http', auth='public', website=False, csrf=False)
    def liff_debug(self, **kwargs):
        """LIFF 診斷頁面 — 在 LINE 內開啟看 LIFF SDK 狀態"""
        ICP = request.env['ir.config_parameter'].sudo()
        liff_id = ICP.get_param('woow_line_bridge.liff_id_member', '')

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LIFF Debug</title>
<style>body{{font-family:monospace;padding:16px;background:#FAF6F2;font-size:13px;}}
pre{{background:#fff;padding:12px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;}}
.ok{{color:green;}} .fail{{color:red;}} .warn{{color:orange;}}</style>
</head><body>
<h2>LIFF Debug</h2>
<pre id="log">Loading LIFF SDK...</pre>
<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<script>
var log = document.getElementById('log');
function L(msg) {{ log.textContent += '\\n' + msg; }}
function S(label, val, cls) {{ L('[' + (cls||'') + '] ' + label + ': ' + val); }}

L('LIFF ID: {liff_id}');
L('URL: ' + window.location.href);
L('UserAgent: ' + navigator.userAgent.substring(0, 80));
L('');

if (typeof liff === 'undefined') {{
    S('SDK', 'NOT LOADED', 'fail');
}} else {{
    S('SDK', 'loaded', 'ok');
    L('Calling liff.init()...');

    liff.init({{ liffId: '{liff_id}' }}).then(function() {{
        S('init', 'SUCCESS', 'ok');
        S('isLoggedIn', liff.isLoggedIn());
        S('isInClient', liff.isInClient());

        var os = liff.getOS();
        S('getOS', os);

        var lang = liff.getLanguage();
        S('getLanguage', lang);

        var ver = liff.getVersion();
        S('getVersion', ver);

        var ctx = liff.getContext();
        S('getContext', JSON.stringify(ctx));

        // ID Token
        try {{
            var idToken = liff.getIDToken();
            S('getIDToken', idToken ? idToken.substring(0, 30) + '...' : 'null', idToken ? 'ok' : 'warn');
        }} catch(e) {{
            S('getIDToken', 'ERROR: ' + e.message, 'fail');
        }}

        // Access Token
        try {{
            var accessToken = liff.getAccessToken();
            S('getAccessToken', accessToken ? accessToken.substring(0, 30) + '...' : 'null', accessToken ? 'ok' : 'warn');
        }} catch(e) {{
            S('getAccessToken', 'ERROR: ' + e.message, 'fail');
        }}

        // Profile
        if (liff.isLoggedIn()) {{
            liff.getProfile().then(function(p) {{
                S('profile.userId', p.userId, 'ok');
                S('profile.displayName', p.displayName);
                S('profile.pictureUrl', p.pictureUrl ? 'yes' : 'no');
            }}).catch(function(e) {{
                S('getProfile', 'ERROR: ' + e.message, 'fail');
            }});
        }}
    }}).catch(function(err) {{
        S('init', 'FAILED: ' + err.message, 'fail');
        L('');
        L('Full error: ' + JSON.stringify(err));
    }});
}}
</script></body></html>"""
        return request.make_response(html, headers=[('Content-Type', 'text/html')])
