# -*- coding: utf-8 -*-
# woow_line_bridge/controllers/liff_pages.py
# 自建 LIFF 頁面 Controller
# 渲染：最新消息 /liff/news、店家位置 /liff/locations
import base64
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class LiffPagesController(http.Controller):
    """LIFF 自建頁面 Controller

    這些頁面直接在 LIFF 內顯示，不需要跳轉到 portal。
    auth='public' 因為初次打開時用戶尚未登入 Odoo。
    """

    @http.route('/liff/clear-session', type='http', auth='none', csrf=False,
                save_session=False)
    def liff_clear_session(self, **kwargs):
        """清除壞掉的 session 並重導回登入頁

        當 LIFF 登入產生壞 session 時，所有頁面都會 403。
        這個 auth='none' 的端點不會觸發 session 驗證，
        所以可以安全地清除 session 後重導。
        """
        redirect_to = kwargs.get('r', '/web/login')
        # 清除 session
        request.session.uid = False
        request.session.login = None
        _logger.info('已清除壞 session，重導到 %s', redirect_to)
        return request.redirect(redirect_to)

    @http.route('/liff/news/image/<int:news_id>', type='http', auth='none',
                csrf=False)
    def liff_news_image(self, news_id, **kwargs):
        """公開存取新聞封面圖片（LINE Flex Message 規格）

        LINE 要求: HTTPS, JPEG/PNG, max 1024×1024 px, max 10 MB
        """
        from odoo.tools.image import image_process

        news = request.env['line.news'].sudo().browse(news_id)
        if not news.exists() or not news.image:
            return request.not_found()
        # 縮放到 LINE 規格上限 1024×1024，輸出 PNG（保留透明度）
        processed = image_process(
            news.image, size=(1024, 1024), output_format='PNG',
        )
        image_data = base64.b64decode(processed)
        # 偵測實際格式：PNG 以 \x89PNG 開頭
        content_type = 'image/png' if image_data[:4] == b'\x89PNG' else 'image/jpeg'
        return request.make_response(image_data, headers=[
            ('Content-Type', content_type),
            ('Cache-Control', 'public, max-age=86400'),
        ])

    @http.route('/liff/news', type='http', auth='none', csrf=False)
    def liff_news(self, **kwargs):
        """最新消息頁（inline HTML，不依賴 website 模板）"""
        ICP = request.env['ir.config_parameter'].sudo()
        shop_name = ICP.get_param('woow_line_bridge.shop_name', '')

        news_list = request.env['line.news'].sudo().search([
            ('is_published', '=', True),
        ], order='published_date desc', limit=20)

        article_id = kwargs.get('article_id')
        article = None
        if article_id:
            try:
                a = request.env['line.news'].sudo().browse(int(article_id))
                if a.exists() and a.is_published:
                    article = a
            except (ValueError, TypeError):
                pass

        cards_html = ''
        if article:
            body = article.body or article.summary or ''
            cards_html = f'''
            <div style="padding:16px;">
                <a href="/liff/news" style="color:#666;text-decoration:none;">&larr; 返回列表</a>
                <h2 style="margin:16px 0 8px;color:#1A1A1A;">{article.title or ""}</h2>
                <p style="color:#999;font-size:12px;">{str(article.published_date or "")[:10]}</p>
                <div style="color:#333;line-height:1.8;margin-top:16px;">{body}</div>
            </div>'''
        elif news_list:
            items = []
            for n in news_list:
                date = str(n.published_date or '')[:10]
                items.append(f'''
                <a href="/liff/news?article_id={n.id}" style="display:block;padding:16px;border-bottom:1px solid #E5E5E5;text-decoration:none;color:#333;">
                    <div style="font-weight:bold;margin-bottom:4px;">{n.title or ""}</div>
                    <div style="color:#999;font-size:12px;">{date}</div>
                    {f'<div style="color:#666;font-size:13px;margin-top:4px;">{n.summary}</div>' if n.summary else ''}
                </a>''')
            cards_html = ''.join(items)
        else:
            cards_html = '<div style="text-align:center;padding:40px;color:#999;">目前沒有最新消息</div>'

        html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>最新消息 | {shop_name}</title>
<style>body{{margin:0;font-family:'Noto Sans TC',sans-serif;background:#F5F5F5;color:#333;}}
.hdr{{background:#1A1A1A;color:#fff;padding:16px 20px;font-size:16px;font-weight:bold;}}</style>
</head><body>
<div class="hdr">{shop_name} — 最新消息</div>
<div style="background:#fff;max-width:600px;margin:0 auto;">{cards_html}</div>
</body></html>'''
        return request.make_response(html, headers=[('Content-Type', 'text/html')])

    @http.route('/liff/locations', type='http', auth='none', csrf=False)
    def liff_locations(self, **kwargs):
        """店家位置頁（inline HTML，不依賴 website 模板）"""
        ICP = request.env['ir.config_parameter'].sudo()
        shop_name = ICP.get_param('woow_line_bridge.shop_name', '')
        shop_address = ICP.get_param('woow_line_bridge.shop_address', '')
        shop_phone = ICP.get_param('woow_line_bridge.shop_phone', '')
        shop_lat = ICP.get_param('woow_line_bridge.shop_latitude', '')
        shop_lng = ICP.get_param('woow_line_bridge.shop_longitude', '')
        shop_hours = ICP.get_param('woow_line_bridge.shop_opening_hours', '')

        map_html = ''
        if shop_lat and shop_lng:
            map_html = f'''
            <div id="map" style="height:300px;background:#E5E5E5;"></div>
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
            <script>
            var m=L.map('map').setView([{shop_lat},{shop_lng}],16);
            L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}).addTo(m);
            L.marker([{shop_lat},{shop_lng}]).addTo(m).bindPopup('{shop_name}').openPopup();
            </script>'''
        nav_url = f'https://www.google.com/maps/dir/?api=1&destination={shop_lat},{shop_lng}' if shop_lat and shop_lng else '#'

        html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>店家位置 | {shop_name}</title>
<style>body{{margin:0;font-family:'Noto Sans TC',sans-serif;background:#F5F5F5;color:#333;}}
.hdr{{background:#1A1A1A;color:#fff;padding:16px 20px;font-size:16px;font-weight:bold;}}
.info{{padding:16px 20px;background:#fff;margin:8px 0;}}
.row{{display:flex;padding:8px 0;border-bottom:1px solid #E5E5E5;}}
.label{{color:#999;width:80px;flex-shrink:0;}} .val{{color:#333;}}
.btn{{display:block;text-align:center;background:#333;color:#fff;padding:12px;margin:16px 20px;text-decoration:none;border-radius:4px;}}</style>
</head><body>
<div class="hdr">{shop_name} — 店家位置</div>
{map_html}
<div class="info">
    <div class="row"><span class="label">地址</span><span class="val">{shop_address or '-'}</span></div>
    <div class="row"><span class="label">電話</span><span class="val">{shop_phone or '-'}</span></div>
    <div class="row"><span class="label">營業時間</span><span class="val">{shop_hours or '-'}</span></div>
</div>
<a class="btn" href="{nav_url}">Google 地圖導航</a>
</body></html>'''
        return request.make_response(html, headers=[('Content-Type', 'text/html')])

    @http.route('/liff/debug', type='http', auth='public', website=False, csrf=False)
    def liff_debug(self, **kwargs):
        """LIFF 診斷頁面 — 在 LINE 內開啟看 LIFF SDK 狀態"""
        ICP = request.env['ir.config_parameter'].sudo()
        liff_id = ICP.get_param('woow_line_bridge.liff_id_member', '')

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LIFF Debug</title>
<style>body{{font-family:monospace;padding:16px;background:#F5F5F5;font-size:13px;}}
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
