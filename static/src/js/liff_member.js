/**
 * woow_line_bridge/static/src/js/liff_member.js
 * 會員中心主入口頁 JavaScript
 * 流程：LIFF init → 取得 ID Token（快取）→ 按鈕 POST redirect
 * 重要：絕不呼叫 liff.login()，在 LINE 內 liff.init() 會自動登入
 */
(function () {
    'use strict';

    var liffId = window.__LIFF_ID__;
    if (!liffId) {
        console.warn('[LiffMember] LIFF ID 未設定');
        return;
    }

    // 直接跳轉對照表（無 ID Token 時 fallback）
    var DIRECT_URLS = {
        'book': '/appointment/1/schedule',
        'my-bookings': '/my/ext-bookings',
        'profile': '/my/account'
    };

    var liffReady = false;
    var cachedIdToken = null;
    var cachedAccessToken = null;

    function onReady(fn) {
        if (document.readyState !== 'loading') fn();
        else document.addEventListener('DOMContentLoaded', fn);
    }

    // 檢查是否有 auto-redirect target（從 Rich Menu 來的）
    // 如果有，立即隱藏主 UI 只顯示 loading，讓跳轉更流暢
    function getAutoTarget() {
        var params = new URLSearchParams(window.location.search);
        var t = params.get('target');
        if (t) return t;
        var liffState = params.get('liff.state');
        if (liffState) {
            var stateParams = new URLSearchParams(liffState.replace(/^\?/, ''));
            t = stateParams.get('target');
            if (t) return t;
        }
        return null;
    }
    var pendingTarget = getAutoTarget();

    onReady(function () {
        if (pendingTarget && DIRECT_URLS[pendingTarget]) {
            // 隱藏主 UI，顯示 loading spinner
            var grid = document.querySelector('.grid');
            var footer = document.querySelector('.footer');
            if (grid) grid.style.display = 'none';
            if (footer) footer.style.display = 'none';
            var greeting = document.getElementById('liff-user-greeting');
            if (greeting) greeting.textContent = '跳轉中...';
        }
        bindButtons();
        initLiff();
    });

    function initLiff() {
        if (typeof liff === 'undefined') {
            console.error('[LiffMember] LIFF SDK 未載入');
            liffReady = true;
            return;
        }

        liff.init({ liffId: liffId }).then(function () {
            var loggedIn = liff.isLoggedIn();
            var inClient = liff.isInClient();
            console.log('[LiffMember] init OK, loggedIn=' + loggedIn + ', inClient=' + inClient);

            if (loggedIn) {
                // 快取 ID Token（需要 openid scope）
                try {
                    cachedIdToken = liff.getIDToken();
                    console.log('[LiffMember] ID Token: ' + (cachedIdToken ? '有' : '無'));
                } catch (e) {
                    console.warn('[LiffMember] getIDToken error', e);
                }

                // 快取 Access Token（備援，不需要 openid scope）
                try {
                    cachedAccessToken = liff.getAccessToken();
                    console.log('[LiffMember] Access Token: ' + (cachedAccessToken ? '有' : '無'));
                } catch (e) {
                    console.warn('[LiffMember] getAccessToken error', e);
                }

                // 更新 UI（auto-redirect 時跳過，加速跳轉）
                if (!pendingTarget) {
                    liff.getProfile().then(updateUserUI).catch(function (e) {
                        console.warn('[LiffMember] getProfile error', e);
                    });
                }
            }
            // 不管有沒有登入都標記 ready，絕不呼叫 liff.login()
            liffReady = true;

            // Auto-redirect: 使用頁面載入時就解析好的 pendingTarget
            if (pendingTarget && DIRECT_URLS[pendingTarget]) {
                console.log('[LiffMember] Auto-redirect: target=' + pendingTarget);
                doRedirect(pendingTarget);
                return; // 不需要更新 UI，直接跳轉
            }
        }).catch(function (err) {
            console.error('[LiffMember] init failed', err);
            liffReady = true;
        });
    }

    function updateUserUI(profile) {
        var avatarEl = document.getElementById('liff-user-avatar');
        if (avatarEl && profile.pictureUrl) {
            avatarEl.innerHTML = '<img src="' + profile.pictureUrl + '" ' +
                'alt="' + (profile.displayName || '') + '" ' +
                'style="width:64px;height:64px;border-radius:50%;object-fit:cover;" />';
        }
        var greetingEl = document.getElementById('liff-user-greeting');
        if (greetingEl && profile.displayName) {
            greetingEl.textContent = profile.displayName + '，歡迎光臨';
        }
    }

    function bindButtons() {
        bindRedirectButton('btn-book', 'book');
        bindRedirectButton('btn-my-bookings', 'my-bookings');
        bindRedirectButton('btn-profile', 'profile');

        var contactBtn = document.getElementById('btn-contact');
        if (contactBtn) {
            contactBtn.addEventListener('click', function (e) {
                e.preventDefault();
                if (typeof liff !== 'undefined' && liff.isInClient()) {
                    liff.closeWindow();
                }
            });
        }
    }

    function bindRedirectButton(elementId, target) {
        var btn = document.getElementById(elementId);
        if (!btn) return;

        btn.addEventListener('click', function (e) {
            e.preventDefault();

            if (!liffReady) {
                // 等 LIFF init 完成（最多 3 秒）
                btn.style.opacity = '0.5';
                var waited = 0;
                var iv = setInterval(function () {
                    waited += 200;
                    if (liffReady || waited >= 3000) {
                        clearInterval(iv);
                        btn.style.opacity = '';
                        doRedirect(target);
                    }
                }, 200);
                return;
            }

            doRedirect(target);
        });
    }

    function doRedirect(target) {
        // 嘗試取得最新 token
        var idToken = cachedIdToken;
        var accessToken = cachedAccessToken;

        if (!idToken && typeof liff !== 'undefined' && liff.isLoggedIn()) {
            try { idToken = liff.getIDToken(); } catch (e) {}
        }
        if (!accessToken && typeof liff !== 'undefined' && liff.isLoggedIn()) {
            try { accessToken = liff.getAccessToken(); } catch (e) {}
        }

        if (idToken || accessToken) {
            // 有任一 token → POST 到 liff_redirect（自動登入 Odoo）
            console.log('[LiffMember] POST /liff/redirect/' + target +
                ' (idToken=' + (idToken ? '有' : '無') +
                ', accessToken=' + (accessToken ? '有' : '無') + ')');
            var form = document.createElement('form');
            form.method = 'POST';
            form.action = '/liff/redirect/' + target;

            if (idToken) {
                var input1 = document.createElement('input');
                input1.type = 'hidden';
                input1.name = 'id_token';
                input1.value = idToken;
                form.appendChild(input1);
            }
            if (accessToken) {
                var input2 = document.createElement('input');
                input2.type = 'hidden';
                input2.name = 'access_token';
                input2.value = accessToken;
                form.appendChild(input2);
            }

            document.body.appendChild(form);
            form.submit();
        } else {
            // 完全沒有 token → 直接跳轉目標頁面（不走自動登入）
            var directUrl = DIRECT_URLS[target] || '/appointment/1/schedule';
            console.log('[LiffMember] 無 token，直接導向 ' + directUrl);
            window.location.href = directUrl;
        }
    }

})();
