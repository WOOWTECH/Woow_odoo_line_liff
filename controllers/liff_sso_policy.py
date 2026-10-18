"""Small, fail-closed policy helpers. No Odoo access or authentication side effects.

站點專屬的值（內部 SSO 綁定、後台 target、預約草稿銜接）都由
ir.config_parameter 提供，預設為空；沒設定的站點行為與一般 portal 登入相同。
"""
import json
import math
import re
import secrets

BINDING_PARAM = 'woow_odoo_line_liff.internal_sso_bindings'
# JSON 物件 {"<target>": "<站內路徑>"}；只有內部 SSO 綁定的使用者會被直接帶到這些路徑，
# 其餘人一律走 Odoo 原生登入（redirect 參數帶同一個路徑）。
ADMIN_TARGETS_PARAM = 'woow_odoo_line_liff.internal_sso_admin_targets'
# 預約模組的「登入後繼續預約」路徑與它存放草稿的 session key；兩者都設定才啟用。
BOOKING_RESUME_PATH_PARAM = 'woow_odoo_line_liff.booking_resume_path'
BOOKING_INTENT_KEY_PARAM = 'woow_odoo_line_liff.booking_intent_session_key'
STATE_KEY = 'woow_line_liff.login_challenges'

_TARGET_RE = re.compile(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*')
_TARGET_NAME_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')
_SESSION_KEY_RE = re.compile(r'[A-Za-z0-9_.-]{1,128}')


def allowed_target(target):
    """target 只能是以 / 分隔的安全字元片段：不可有空片段、開頭結尾的 /，長度 64 內。

    不限定固定清單：各站 Rich Menu 會用 /liff/redirect/<自訂路徑>，
    實際跳轉位置由 controller 的 _get_redirect_url 決定。
    """
    return isinstance(target, str) and len(target) <= 64 and bool(_TARGET_RE.fullmatch(target))


def is_safe_local_path(path):
    """只接受站內絕對路徑：/ 開頭、非 //、無反斜線與控制字元。"""
    return (isinstance(path, str) and 0 < len(path) <= 512 and path.startswith('/')
            and not path.startswith('//') and '\\' not in path
            and not any(ord(c) < 32 or ord(c) == 127 for c in path))


def parse_admin_targets(raw):
    """解析後台 target 設定；格式不對時整份視為未設定（回傳空 dict）。"""
    try:
        data = json.loads(raw or '{}')
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    if not all(isinstance(k, str) and _TARGET_NAME_RE.fullmatch(k) and is_safe_local_path(v)
               for k, v in data.items()):
        return {}
    return dict(data)


def parse_booking_resume(path, session_key):
    """回傳 (path, session_key)；任一缺漏或不合法就回傳 (None, None)，停用預約銜接。"""
    if is_safe_local_path(path) and '?' not in path and '#' not in path \
            and isinstance(session_key, str) and _SESSION_KEY_RE.fullmatch(session_key):
        return path, session_key
    return None, None


def issue_challenge(session, target, booking_nonce, now, config_id):
    if not allowed_target(target):
        raise ValueError('Unsupported login destination')
    old = session.get(STATE_KEY, {})
    old = old if isinstance(old, dict) else {}
    keep = {k: v for k, v in old.items() if isinstance(v, dict) and isinstance(v.get('expires'), (int, float)) and v['expires'] > now}
    keep = dict(list(keep.items())[-4:])
    nonce = secrets.token_urlsafe(32)
    keep[nonce] = {'target': target, 'booking_nonce': booking_nonce, 'expires': now + 600, 'config_id': config_id}
    session[STATE_KEY] = keep
    return nonce


def consume_challenge(session, nonce, target, booking_nonce, now, config_id):
    if not isinstance(nonce, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', nonce):
        return False
    stored = session.get(STATE_KEY, {})
    stored = dict(stored) if isinstance(stored, dict) else {}
    challenge = stored.pop(nonce, None)
    session[STATE_KEY] = stored
    return bool(isinstance(challenge, dict) and challenge.get('target') == target
                and challenge.get('booking_nonce') == booking_nonce
                and challenge.get('config_id') == config_id
                and isinstance(challenge.get('expires'), (int, float))
                and now < challenge['expires'] <= now + 600)


def binding_for_claims(raw, payload, id_token_verified, config_id, channel_id, now):
    """Only claims returned by server-side LINE verification may call this helper.

    A matched but disabled/invalid binding is an error, never a portal fallback.
    Unregistered identities return None and cannot create internal sessions.
    """
    try:
        bindings = json.loads(raw or '[]')
    except (ValueError, TypeError):
        raise ValueError('Invalid SSO configuration') from None
    if not isinstance(bindings, list) or any(not isinstance(x, dict) for x in bindings):
        raise ValueError('Invalid SSO configuration')
    matches = [x for x in bindings if x.get('subject') == payload.get('sub')]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError('Ambiguous SSO binding')
    row = matches[0]
    exp = payload.get('exp')
    if not (row.get('enabled') is True and id_token_verified
            and type(config_id) is int and row.get('config_id') == config_id
            and isinstance(channel_id, str) and channel_id
            and row.get('login_channel_id') == channel_id
            and str(payload.get('aud')) == channel_id
            and payload.get('iss') == 'https://access.line.me'
            and type(exp) in (int, float) and math.isfinite(exp) and exp > now
            and isinstance(payload.get('sub'), str) and bool(re.fullmatch(r'U[0-9a-f]{32}', payload['sub']))
            and all(type(row.get(k)) is int and row[k] > 0 for k in ['line_user_id', 'partner_id', 'user_id'])):
        raise ValueError('SSO identity not authorized')
    return row
