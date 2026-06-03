/**
 * woow_line_bridge/static/src/js/liff_helper.js
 * LIFF 共用輔助函式
 * 提供 LIFF 初始化、ID Token 取得、API 呼叫等工具函式
 */
(function () {
    'use strict';

    window.WoowLiff = window.WoowLiff || {};

    /**
     * 初始化 LIFF SDK
     * @param {string} liffId - LIFF ID
     * @returns {Promise<void>}
     */
    WoowLiff.init = function (liffId) {
        if (!liffId) {
            console.error('[WoowLiff] LIFF ID 未提供');
            return Promise.reject(new Error('LIFF ID is required'));
        }

        if (typeof liff === 'undefined') {
            console.error('[WoowLiff] LIFF SDK 未載入');
            return Promise.reject(new Error('LIFF SDK not loaded'));
        }

        return liff.init({ liffId: liffId }).then(function () {
            console.log('[WoowLiff] LIFF 初始化成功');
        });
    };

    /**
     * 確保使用者已登入 LIFF
     * 若未登入則導向 LINE Login
     * @returns {boolean} 是否已登入
     */
    WoowLiff.ensureLogin = function () {
        if (typeof liff === 'undefined') return false;

        if (!liff.isLoggedIn()) {
            liff.login({ redirectUri: window.location.href });
            return false;
        }
        return true;
    };

    /**
     * 取得 ID Token
     * @returns {string|null}
     */
    WoowLiff.getIdToken = function () {
        if (typeof liff === 'undefined') return null;

        try {
            return liff.getIDToken();
        } catch (e) {
            console.error('[WoowLiff] 取得 ID Token 失敗', e);
            return null;
        }
    };

    /**
     * 取得使用者 Profile
     * @returns {Promise<Object>}
     */
    WoowLiff.getProfile = function () {
        if (typeof liff === 'undefined') {
            return Promise.reject(new Error('LIFF SDK not loaded'));
        }
        return liff.getProfile();
    };

    /**
     * 呼叫後端 API（附帶 ID Token）
     * @param {string} url - API URL
     * @param {Object} data - POST body 資料
     * @returns {Promise<Object>} API 回應
     */
    WoowLiff.apiCall = function (url, data) {
        var idToken = WoowLiff.getIdToken();
        if (!idToken) {
            return Promise.reject(new Error('No ID Token'));
        }

        var body = Object.assign({}, data || {}, { id_token: idToken });

        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + idToken,
            },
            body: JSON.stringify(body),
        }).then(function (resp) {
            if (!resp.ok) {
                throw new Error('API error: ' + resp.status);
            }
            return resp.json();
        });
    };

    /**
     * 導向 LIFF redirect endpoint（自動登入後跳轉）
     * @param {string} target - 目標（book / my-bookings / profile）
     */
    WoowLiff.redirectTo = function (target) {
        var idToken = WoowLiff.getIdToken();
        if (!idToken) {
            console.error('[WoowLiff] 無 ID Token，無法導向');
            return;
        }

        // 建立隱藏 form POST
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
    };

    /**
     * 關閉 LIFF 視窗
     */
    WoowLiff.close = function () {
        if (typeof liff !== 'undefined' && liff.isInClient()) {
            liff.closeWindow();
        }
    };

    /**
     * 是否在 LINE 內開啟
     * @returns {boolean}
     */
    WoowLiff.isInLine = function () {
        if (typeof liff === 'undefined') return false;
        return liff.isInClient();
    };

    /**
     * 是否為 LIFF 模式（URL 帶 ?liff=1）
     * @returns {boolean}
     */
    WoowLiff.isLiffMode = function () {
        var params = new URLSearchParams(window.location.search);
        return params.get('liff') === '1';
    };

})();
