# -*- coding: utf-8 -*-
# woow_line_bridge/controllers/liff_pages.py
# 自建 LIFF 頁面 Controller
# 渲染：會員中心 /liff/member、最新消息 /liff/news、店家位置 /liff/locations
# Config keys: woow_line_bridge.* → woow_line_liff.*
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

    @http.route('/liff/member', type='http', auth='none', website=False, csrf=False)
    def liff_member(self, **kwargs):
        """會員中心主入口頁

        使用 auth='none' 避免壞 session 導致 403。
        自己清除壞 session + 渲染頁面。
        """
        # 清除壞 session（不會再 crash）
        try:
            if request.session.uid:
                request.session.uid = False
                request.session.login = None
        except Exception:
            pass

        ICP = request.env['ir.config_parameter'].sudo()
        liff_id = ICP.get_param('woow_line_liff.liff_id_member', '')
        shop_name = ICP.get_param('woow_line_liff.shop_name', 'Mark Studio 馬克健身')
        error = kwargs.get('error', '')

        # auth='none' 不能用 request.render()，用 inline HTML
        return request.make_response(
            self._build_member_html(liff_id, shop_name, error),
            headers=[('Content-Type', 'text/html; charset=utf-8')],
        )

    def _build_member_html(self, liff_id, shop_name, error=''):
        """產生會員中心 HTML（Retrodandy 黑白極簡風格，與網站一致）"""
        error_html = ''
        if error:
            error_msgs = {
                'no_token': '登入失敗：缺少驗證資訊',
                'invalid_token': '登入失敗：驗證過期，請重新開啟',
                'login_failed': '登入失敗：請稍後再試',
                'user_creation_failed': '帳號建立失敗，請聯繫客服',
            }
            error_html = f'<div class="liff-member-error"><p>{error_msgs.get(error, error)}</p></div>'

        return f"""<!DOCTYPE html>
<html lang="zh-TW"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LIFF Member Page | {shop_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@400;700&family=Noto+Sans+TC:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Noto Sans TC','Helvetica Neue',sans-serif;background:#000;min-height:100vh;color:#fff;}}
.hdr{{background:#000;padding:36px 20px 28px;text-align:center;border-bottom:1px solid rgba(255,255,255,.1);}}
.hdr h1{{font-family:'Noto Serif TC',Georgia,serif;font-size:24px;font-weight:700;letter-spacing:1px;margin-bottom:4px;}}
.hdr p{{font-size:14px;color:rgba(255,255,255,.6);font-weight:300;}}
.avatar{{width:64px;height:64px;border-radius:50%;border:1px solid rgba(255,255,255,.2);margin:0 auto 14px;display:flex;align-items:center;justify-content:center;overflow:hidden;}}
.avatar img{{width:64px;height:64px;border-radius:50%;object-fit:cover;filter:grayscale(1);}}
.avatar svg{{width:48px;height:48px;}}
.liff-member-error{{margin:12px 16px;padding:12px 16px;background:rgba(192,57,43,.15);border-left:3px solid #c0392b;color:#ff6b6b;font-size:13px;}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;padding:24px 16px;background:transparent;}}
.card{{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:24px 8px;background:#1a1a1a;border:1px solid rgba(255,255,255,.08);text-decoration:none;color:#fff;min-height:110px;transition:background .2s,border-color .2s;}}
.card:active,.card:hover{{background:#222;border-color:rgba(255,255,255,.2);}}
.card-icon{{width:48px;height:48px;display:flex;align-items:center;justify-content:center;margin-bottom:10px;}}
.card-label{{font-size:13px;font-weight:500;letter-spacing:.5px;text-align:center;}}
.footer{{text-align:center;padding:24px;color:rgba(255,255,255,.3);font-size:11px;font-weight:300;letter-spacing:1px;}}
@media(max-width:380px){{.grid{{grid-template-columns:repeat(2,1fr);}}}}
</style></head><body>
<div class="hdr">
  <div class="avatar" id="liff-user-avatar">
    <svg viewBox="0 0 48 48" fill="none"><circle cx="24" cy="24" r="24" fill="#1a1a1a"/><circle cx="24" cy="18" r="8" fill="#333"/><ellipse cx="24" cy="38" rx="14" ry="10" fill="#333"/></svg>
  </div>
  <h1>{shop_name}</h1>
  <p id="liff-user-greeting">歡迎光臨</p>
</div>
{error_html}
<div class="grid">
  <a class="card" id="btn-book" href="#">
    <div class="card-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.5"><rect x="3" y="4" width="18" height="18" rx="0"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="12" y1="14" x2="12" y2="18"/><line x1="10" y1="16" x2="14" y2="16"/></svg></div>
    <span class="card-label">立即預約</span>
  </a>
  <a class="card" id="btn-my-bookings" href="#">
    <div class="card-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="15" y2="17"/></svg></div>
    <span class="card-label">我的預約</span>
  </a>
  <a class="card" id="btn-profile" href="#">
    <div class="card-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.5"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg></div>
    <span class="card-label">個人資料</span>
  </a>
  <a class="card" href="/#news">
    <div class="card-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.5"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg></div>
    <span class="card-label">最新消息</span>
  </a>
  <a class="card" href="/liff/locations">
    <div class="card-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.5"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg></div>
    <span class="card-label">店家位置</span>
  </a>
  <a class="card" id="btn-contact" href="#">
    <div class="card-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.5"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg></div>
    <span class="card-label">聯絡我們</span>
  </a>
</div>
<div class="footer"><p>MARK STUDIO</p></div>
<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<script>window.__LIFF_ID__='{liff_id}';</script>
<script src="/woow_line_bridge/static/src/js/liff_member.js?v=5"></script>
</body></html>"""

    @http.route('/liff/news', type='http', auth='public', website=True)
    def liff_news(self, **kwargs):
        """最新消息頁（Phase 3 補完內容）"""
        ICP = request.env['ir.config_parameter'].sudo()
        shop_name = ICP.get_param('woow_line_liff.shop_name', 'Mark Studio 馬克健身')

        values = {
            'shop_name': shop_name,
        }
        return request.render('woow_line_bridge.liff_news_page', values)

    @http.route('/liff/locations', type='http', auth='public', website=True)
    def liff_locations(self, **kwargs):
        """店家位置頁（Phase 3 補完地圖）"""
        ICP = request.env['ir.config_parameter'].sudo()
        shop_name = ICP.get_param('woow_line_liff.shop_name', 'Mark Studio 馬克健身')
        shop_address = ICP.get_param('woow_line_liff.shop_address', '')
        shop_phone = ICP.get_param('woow_line_liff.shop_phone', '')
        shop_lat = ICP.get_param('woow_line_liff.shop_latitude', '')
        shop_lng = ICP.get_param('woow_line_liff.shop_longitude', '')
        shop_hours = ICP.get_param('woow_line_liff.shop_opening_hours', '')

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
        """LIFF 診斷頁面 -- 在 LINE 內開啟看 LIFF SDK 狀態"""
        ICP = request.env['ir.config_parameter'].sudo()
        liff_id = ICP.get_param('woow_line_liff.liff_id_member', '')

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
