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
                request.session.uid = None
                request.session.login = None
            except Exception:
                pass

    @http.route('/liff/clear-session', type='http', auth='none', csrf=False,
                save_session=False)
    def liff_clear_session(self, **kwargs):
        """清除壞掉的 session 並重導回目標頁面

        當 LIFF 登入產生壞 session 時，所有頁面都會 403。
        save_session=False 讓 Odoo 不讀取 session，
        然後回傳 Set-Cookie 清除壞 cookie。
        """
        redirect_to = kwargs.get('r', '/liff/member')
        resp = request.redirect(redirect_to)
        # 強制清除 session cookie — 讓下一次請求不帶壞 cookie
        resp.delete_cookie('session_id')
        return resp

    @http.route('/liff/member', type='http', auth='none', website=False,
                csrf=False, save_session=False)
    def liff_member(self, **kwargs):
        """會員中心主入口頁

        save_session=False 防止 Odoo 載入壞 session cookie。
        如果之前的 LIFF 登入留下 uid=False 的壞 cookie，
        Odoo middleware 會在 session 驗證時 crash (integer = boolean SQL error)。
        加上 save_session=False 繞過這個問題。
        """
        ICP = request.env['ir.config_parameter'].sudo()
        liff_id = ICP.get_param('woow_line_liff.liff_id_member', '')
        shop_name = ICP.get_param('woow_line_liff.shop_name', 'Mark Studio 馬克健身')
        error = kwargs.get('error', '')

        resp = request.make_response(
            self._build_member_html(liff_id, shop_name, error),
            headers=[('Content-Type', 'text/html; charset=utf-8')],
        )
        # 清除可能的壞 session cookie
        resp.delete_cookie('session_id')
        return resp

    def _build_member_html(self, liff_id, shop_name, error=''):
        """LIFF 入口頁 — 雙模式：認證橋 + fallback

        模式 1（有 ?target= 或 ?liff.state=?target%3D）：
          純認證橋 — spinner → LIFF init → 取 token → POST /liff/redirect/{target}
          用戶只看到短暫 loading，然後直達 portal 頁面

        模式 2（無 target 或認證失敗）：
          fallback — 顯示店名 + 「返回聊天室」按鈕 + 自動 closeWindow
        """
        import json as _json

        error_html = ''
        if error:
            error_msgs = {
                'no_token': '登入逾時，請從選單重新操作',
                'invalid_token': '驗證過期，請重新開啟',
                'login_failed': '登入失敗，請稍後再試',
                'user_creation_failed': '帳號建立失敗，請聯繫客服',
            }
            error_html = f'<div class="err"><p>{error_msgs.get(error, error)}</p></div>'

        # 認證橋的 fallback URL 對照表
        direct_urls = {
            'book': '/appointment/1/schedule',
            'my-bookings': '/my/ext-bookings',
            'profile': '/my/account',
        }

        return f"""<!DOCTYPE html>
<html lang="zh-TW"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{shop_name}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Noto Sans TC',sans-serif;background:#FAF6F2;min-height:100vh;display:flex;align-items:center;justify-content:center;color:#2D2620;}}
.loading{{text-align:center;}}
.spinner{{width:36px;height:36px;border:3px solid #E0D5C8;border-top-color:#B8956A;border-radius:50%;animation:r .7s linear infinite;margin:0 auto 14px;}}
@keyframes r{{to{{transform:rotate(360deg)}}}}
.loading-text{{font-size:14px;color:#6B5B4E;}}
.fallback{{text-align:center;padding:40px 24px;display:none;}}
.shop{{font-size:20px;font-weight:700;margin-bottom:8px;}}
.msg{{font-size:14px;color:#6B5B4E;margin-bottom:24px;}}
.err{{margin:0 24px 16px;padding:12px 16px;background:#FEF2F2;border:1px solid #FECACA;border-radius:8px;color:#991B1B;font-size:13px;text-align:center;}}
.btn{{display:inline-flex;align-items:center;gap:8px;padding:14px 32px;background:#06C755;color:#fff;border:none;border-radius:8px;font-size:16px;font-weight:600;cursor:pointer;text-decoration:none;}}
.btn:active{{opacity:.85;}}
.sub{{margin-top:16px;font-size:12px;color:#9B8E82;}}
</style></head><body>
{error_html}
<div class="loading" id="loading-ui">
  <div class="spinner"></div>
  <p class="loading-text" id="status-text">載入中...</p>
</div>
<div class="fallback" id="fallback-ui">
  <p class="shop">{shop_name}</p>
  <p class="msg">請使用下方選單操作</p>
  <a class="btn" id="btn-close" href="#">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
    返回聊天室
  </a>
  <p class="sub">或從 Rich Menu 選擇功能</p>
</div>
<script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
<script>
(function(){{
  var liffId='{liff_id}';
  var fallbacks={_json.dumps(direct_urls)};
  var loadingEl=document.getElementById('loading-ui');
  var fallbackEl=document.getElementById('fallback-ui');
  var statusEl=document.getElementById('status-text');

  // 解析 target：?target=X 或 LIFF 改寫的 ?liff.state=?target%3DX
  function getTarget(){{
    var p=new URLSearchParams(window.location.search);
    var t=p.get('target');
    if(t) return t;
    var s=p.get('liff.state');
    if(s){{var sp=new URLSearchParams(s.replace(/^\\?/,''));t=sp.get('target');if(t) return t;}}
    return null;
  }}

  var target=getTarget();

  // 模式 2：無 target → 顯示 fallback（返回聊天室）
  if(!target){{
    loadingEl.style.display='none';
    fallbackEl.style.display='block';
    // 嘗試自動關閉
    if(liffId && typeof liff!=='undefined'){{
      liff.init({{liffId:liffId}}).then(function(){{
        if(liff.isInClient()) liff.closeWindow();
      }}).catch(function(){{}});
    }}
    var btn=document.getElementById('btn-close');
    if(btn) btn.addEventListener('click',function(e){{
      e.preventDefault();
      if(typeof liff!=='undefined'&&liff.isInClient&&liff.isInClient()) liff.closeWindow();
      else window.close();
    }});
    return;
  }}

  // 模式 1：有 target → 認證橋
  statusEl.textContent='正在登入中...';

  function goFallback(){{
    var u=fallbacks[target];
    if(u){{statusEl.textContent='正在跳轉...';window.location.href=u;}}
    else{{loadingEl.style.display='none';fallbackEl.style.display='block';}}
  }}

  if(!liffId||typeof liff==='undefined'){{goFallback();return;}}

  liff.init({{liffId:liffId}}).then(function(){{
    if(!liff.isLoggedIn()){{goFallback();return;}}
    var idToken=null,accessToken=null;
    try{{idToken=liff.getIDToken();}}catch(e){{}}
    try{{accessToken=liff.getAccessToken();}}catch(e){{}}
    if(!idToken&&!accessToken){{goFallback();return;}}

    // POST 到認證橋
    statusEl.textContent='登入成功，跳轉中...';
    var f=document.createElement('form');f.method='POST';f.action='/liff/redirect/'+target;
    if(idToken){{var i=document.createElement('input');i.type='hidden';i.name='id_token';i.value=idToken;f.appendChild(i);}}
    if(accessToken){{var a=document.createElement('input');a.type='hidden';a.name='access_token';a.value=accessToken;f.appendChild(a);}}
    document.body.appendChild(f);f.submit();
  }}).catch(function(){{goFallback();}});
}})();
</script>
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
