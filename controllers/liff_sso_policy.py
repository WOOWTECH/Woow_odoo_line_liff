"""Small, fail-closed policy helpers. No Odoo access or authentication side effects."""
import json
import math
import re
import secrets

BINDING_PARAM = 'woow_odoo_line_liff.internal_sso_bindings'
STATE_KEY = 'woow_line_liff.login_challenges'
BOOKING_KEY = 'reservation_module.booking_intents'
ADMIN_TARGETS = {
    'admin-bookings': '/odoo/action-813',
    'admin-conversations': '/odoo/livechat/2/action-870',
    'admin-service-60': '/odoo/action-812/1',
    'admin-service-90': '/odoo/action-812/2',
}
PORTAL_TARGETS = {'book', 'my-bookings', 'profile', 'home', 'orders', 'invoices'}


def allowed_target(target):
    return isinstance(target, str) and (target in PORTAL_TARGETS or target in ADMIN_TARGETS or bool(re.fullmatch(r'booking/[1-9][0-9]{0,9}', target)))


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
