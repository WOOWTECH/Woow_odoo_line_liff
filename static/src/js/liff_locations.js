/**
 * woow_line_bridge/static/src/js/liff_locations.js
 * 店家位置頁 JavaScript — Leaflet + OpenStreetMap 地圖整合
 */
(function () {
    'use strict';

    function onReady(fn) {
        if (document.readyState !== 'loading') {
            fn();
        } else {
            document.addEventListener('DOMContentLoaded', fn);
        }
    }

    onReady(function () {
        var mapEl = document.getElementById('liff-map');
        if (!mapEl) return;

        var lat = parseFloat(mapEl.getAttribute('data-lat'));
        var lng = parseFloat(mapEl.getAttribute('data-lng'));
        var name = mapEl.getAttribute('data-name') || '';

        if (isNaN(lat) || isNaN(lng)) return;

        // 檢查 Leaflet 是否已載入
        if (typeof L === 'undefined') {
            mapEl.innerHTML = '<p style="text-align:center;padding:40px 0;color:#6B5B4E;">' +
                '地圖載入失敗<br><a href="https://www.google.com/maps?q=' + lat + ',' + lng +
                '" target="_blank" style="color:#B8956A;">在 Google 地圖中開啟</a></p>';
            return;
        }

        // 初始化 Leaflet 地圖
        var map = L.map('liff-map', {
            scrollWheelZoom: false,
            zoomControl: true,
        }).setView([lat, lng], 16);

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
            maxZoom: 19,
        }).addTo(map);

        // 自定義品牌色 marker icon
        var markerIcon = L.divIcon({
            className: 'liff-map-marker',
            html: '<svg width="32" height="42" viewBox="0 0 32 42" fill="none" xmlns="http://www.w3.org/2000/svg">' +
                '<path d="M16 0C7.16 0 0 7.16 0 16c0 12 16 26 16 26s16-14 16-26C32 7.16 24.84 0 16 0z" fill="#B8956A"/>' +
                '<circle cx="16" cy="16" r="6" fill="white"/></svg>',
            iconSize: [32, 42],
            iconAnchor: [16, 42],
            popupAnchor: [0, -42],
        });

        L.marker([lat, lng], { icon: markerIcon })
            .addTo(map)
            .bindPopup('<strong>' + name + '</strong>')
            .openPopup();

        // 修正 Leaflet 在動態容器中的 resize 問題
        setTimeout(function () { map.invalidateSize(); }, 300);
    });

})();
