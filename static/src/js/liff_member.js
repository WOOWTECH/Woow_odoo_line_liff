/**
 * woow_line_bridge/static/src/js/liff_member.js
 * 會員中心主入口頁 JavaScript
 * 流程：等待 LIFF init 完成 → 取得 profile → 啟用按鈕
 * 按鈕點擊：從 LIFF 取得 ID Token → POST 到 /liff/redirect/<target>
 */
(function () {
    'use strict';

    var liffId = window.__LIFF_ID__;
    if (!liffId) {
        console.warn('[LiffMember] LIFF ID 未設定');
        return;
    }

    // LIFF 初始化狀態
    var liffReady = false;
    var cachedIdToken = null;

    function onReady(fn) {
        if (document.readyState !== 'loading') {
            fn();
        } else {
            document.addEventListener('DOMContentLoaded', fn);
        }
    }

    onReady(function () {
        // 先綁按鈕（會等 liffReady）
        bindButtons();
        // 再初始化 LIFF
        initLiff();
    });

    function initLiff() {
        if (typeof liff === 'undefined') {
            console.error('[LiffMember] LIFF SDK 未載入');
            return;
        }

        liff.init({ liffId: liffId }).then(function () {
            console.log('[LiffMember] LIFF init 成功, isLoggedIn=' + liff.isLoggedIn() + ', isInClient=' + liff.isInClient());

            if (!liff.isLoggedIn()) {
                if (liff.isInClient()) {
                    // 在 LINE 內但未登入（不應發生），嘗試 login
                    console.log('[LiffMember] LINE 內未登入，嘗試 login...');
                    liff.login();
                    return;
                }
                // 外部瀏覽器，不自動登入，按鈕走 GET 流程
                console.log('[LiffMember] 外部瀏覽器，未登入');
                liffReady = true;
                return;
            }

            // 已登入，快取 ID Token
            try {
                cachedIdToken = liff.getIDToken();
                console.log('[LiffMember] ID Token 取得成功');
            } catch (err) {
                console.error('[LiffMember] getIDToken 失敗', err);
            }

            liffReady = true;

            // 更新使用者資訊
            liff.getProfile().then(function (profile) {
                updateUserUI(profile);
            }).catch(function (err) {
                console.error('[LiffMember] getProfile 失敗', err);
            });
        }).catch(function (err) {
            console.error('[LiffMember] LIFF init 失敗', err);
            // init 失敗也標記 ready，讓按鈕可以走 fallback
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

    function postRedirect(target, idToken) {
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = '/liff/redirect/' + target;

        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'id_token';
        input.value = idToken;
        form.appendChild(input);

        document.body.appendChild(form);
        form.submit();
    }

    function bindRedirectButton(elementId, target) {
        var btn = document.getElementById(elementId);
        if (!btn) return;

        btn.addEventListener('click', function (e) {
            e.preventDefault();

            // 如果 LIFF 還沒 ready，等一下再試
            if (!liffReady) {
                console.log('[LiffMember] LIFF 尚未初始化，等待中...');
                btn.style.opacity = '0.5';
                btn.style.pointerEvents = 'none';

                var checkInterval = setInterval(function () {
                    if (liffReady) {
                        clearInterval(checkInterval);
                        btn.style.opacity = '';
                        btn.style.pointerEvents = '';
                        doRedirect(target);
                    }
                }, 200);

                // 3 秒超時，走 fallback
                setTimeout(function () {
                    clearInterval(checkInterval);
                    btn.style.opacity = '';
                    btn.style.pointerEvents = '';
                    if (!liffReady) {
                        console.warn('[LiffMember] LIFF init 超時，走 fallback');
                        window.location.href = '/liff/redirect/' + target;
                    }
                }, 3000);
                return;
            }

            doRedirect(target);
        });
    }

    function doRedirect(target) {
        // 優先用快取的 ID Token
        var idToken = cachedIdToken;

        // 嘗試即時取得（可能已更新）
        if (!idToken && typeof liff !== 'undefined' && liff.isLoggedIn()) {
            try {
                idToken = liff.getIDToken();
            } catch (err) {
                console.error('[LiffMember] getIDToken 失敗', err);
            }
        }

        if (idToken) {
            console.log('[LiffMember] POST redirect to ' + target);
            postRedirect(target, idToken);
        } else {
            // 無 ID Token（外部瀏覽器未登入），走 GET → bridge 頁面
            console.log('[LiffMember] 無 ID Token，走 GET redirect to ' + target);
            window.location.href = '/liff/redirect/' + target;
        }
    }

})();
