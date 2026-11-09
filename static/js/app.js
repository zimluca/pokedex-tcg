/* ==========================================================================
   PokéDex TCG · Market Dashboard - logica client
   ========================================================================== */
(function () {
    'use strict';

    /* ---------- configurazione iniettata dal template ---------- */
    var config = { authenticated: false, isAdmin: false, language: 'en', urls: {} };
    var configEl = document.getElementById('app-config');
    if (configEl) {
        try { config = Object.assign(config, JSON.parse(configEl.textContent)); } catch (e) { console.error('Config non valida', e); }
    }

    var state = { filter: 'all', chart: null, currentCardId: null, scanStream: null, scanBusy: false };

    /* ---------- helper ---------- */
    function qs(sel, root) { return (root || document).querySelector(sel); }
    function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

    function escapeHtml(value) {
        return String(value === undefined || value === null ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function money(value) {
        return '€' + Number(value || 0).toFixed(2);
    }

    function getLanguage() {
        var sel = qs('#language-selector');
        return sel ? sel.value : (config.language || 'en');
    }

    function cardUrl(cardId) {
        return String(config.urls.card || '/api/card/CARD_ID').replace('CARD_ID', encodeURIComponent(cardId));
    }

    /* ---------- notifiche (toast) ---------- */
    function showToast(message, type) {
        var stack = qs('#toast-stack');
        if (!stack) { console.log('[toast]', message); return; }
        var el = document.createElement('div');
        el.className = 'app-toast ' + (type || 'info');
        el.textContent = message;
        stack.appendChild(el);
        setTimeout(function () {
            el.style.transition = 'opacity .25s ease, transform .25s ease';
            el.style.opacity = '0';
            el.style.transform = 'translateY(8px)';
            setTimeout(function () { el.remove(); }, 280);
        }, 3200);
    }

    /* ---------- overlay di caricamento ---------- */
    function showLoading(text) {
        var loader = qs('#app-loader');
        if (!loader) return;
        var label = qs('#app-loader-text', loader);
        if (label && text) label.textContent = text;
        loader.classList.add('show');
    }
    function hideLoading() {
        var loader = qs('#app-loader');
        if (loader) loader.classList.remove('show');
    }

    /* ---------- POST JSON con gestione 401 ---------- */
    function postJson(url, payload) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {})
        }).then(function (response) {
            if (response.status === 401) {
                return response.json().catch(function () { return {}; }).then(function (data) {
                    showToast('Devi effettuare il login', 'error');
                    if (data.redirect) setTimeout(function () { window.location.href = data.redirect; }, 1400);
                    throw new Error('Non autenticato');
                });
            }
            return response.json().catch(function () { return {}; }).then(function (data) {
                if (!response.ok) throw new Error(data.error || 'Errore nella richiesta');
                return data;
            });
        });
    }

    /* ======================================================================
       COLLEZIONE
       ====================================================================== */
    function loadCollectionState() {
        if (!config.authenticated) return;
        fetch(config.urls.collection + '?language=' + encodeURIComponent(getLanguage()))
            .then(function (response) {
                if (!response.ok) throw new Error('Errore nel caricamento della collezione');
                return response.json();
            })
            .then(function (data) {
                if (!Array.isArray(data)) return;
                var ownedIds = {};
                data.forEach(function (card) { ownedIds[card.api_card_id] = true; });
                qsa('.card-tile').forEach(function (tile) {
                    setCardOwnedState(tile.dataset.cardId, !!ownedIds[tile.dataset.cardId]);
                });
                applyFilter();
            })
            .catch(function (error) { console.error('Collezione:', error); });
    }

    function refreshStats() {
        if (!config.authenticated) return;
        fetch(config.urls.stats)
            .then(function (response) { return response.ok ? response.json() : null; })
            .then(function (data) {
                if (!data) return;
                qsa('[data-stat="total-value"]').forEach(function (el) {
                    el.textContent = money(data.total_value || 0);
                });
                if (data.set_counts) {
                    var owned = Object.keys(data.set_counts).reduce(function (sum, key) {
                        return sum + data.set_counts[key];
                    }, 0);
                    qsa('[data-stat="owned-count"]').forEach(function (el) { el.textContent = owned; });
                }
            })
            .catch(function (error) { console.error('Statistiche:', error); });
    }

    function setCardOwnedState(cardId, owned) {
        qsa('.card-tile[data-card-id="' + cardId + '"]').forEach(function (tile) {
            tile.classList.toggle('is-owned', !!owned);
            var btn = qs('[data-action="toggle-own"]', tile);
            if (btn) btn.textContent = owned ? 'Posseduta ✓' : 'Possiedo';
        });
    }

    function applyFilter() {
        qsa('.card-tile').forEach(function (tile) {
            var owned = tile.classList.contains('is-owned');
            var show = state.filter === 'all'
                || (state.filter === 'owned' && owned)
                || (state.filter === 'missing' && !owned);
            tile.parentElement.style.display = show ? '' : 'none';
        });
        var counter = qs('#result-count');
        if (counter) {
            var visible = qsa('.card-tile').filter(function (t) {
                return t.parentElement.style.display !== 'none';
            }).length;
            counter.textContent = visible + (visible === 1 ? ' carta' : ' carte');
        }
    }

    function toggleCardOwnership(button) {
        var cardId = button.dataset.cardId;
        if (!cardId) return;
        var tile = button.closest('.card-tile');
        var owned = button.classList.contains('owned') || (tile && tile.classList.contains('is-owned'));
        var payload = {
            card_id: cardId,
            name: button.dataset.cardName || '',
            set_id: button.dataset.setId || '',
            price: parseFloat(button.dataset.price || '0') || 0,
            language: getLanguage()
        };

        button.disabled = true;
        var request = owned
            ? postJson(config.urls.remove, { card_id: cardId, language: payload.language })
            : postJson(config.urls.add, payload);

        request.then(function (data) {
            showToast(data.message || 'Operazione completata', 'success');
            setCardOwnedState(cardId, !owned);
            applyFilter();
            refreshStats();
            syncSheetOwnership(cardId, !owned);
            return data;
        }).catch(function (error) {
            console.error('Ownership:', error);
            showToast(error.message || 'Errore nella richiesta', 'error');
        }).finally(function () { button.disabled = false; });
    }

    function initFilters() {
        qsa('[data-filter]').forEach(function (button) {
            button.addEventListener('click', function () {
                state.filter = button.dataset.filter;
                qsa('[data-filter]').forEach(function (b) { b.classList.toggle('active', b === button); });
                applyFilter();
            });
        });
    }

    function changeLanguage(value) {
        postJson(config.urls.language, { language: value })
            .then(function () {
                showToast('Lingua aggiornata', 'success');
                setTimeout(function () { location.reload(); }, 450);
            })
            .catch(function (error) { showToast(error.message || 'Errore aggiornamento lingua', 'error'); });
    }

    /* ======================================================================
       SCHEDA FINANZIARIA DELLA CARTA
       ====================================================================== */
    function openCardSheet(cardId) {
        state.currentCardId = cardId;
        var modalEl = qs('#cardModal');
        var body = qs('#cardModalBody');
        if (!modalEl || !body) return;

        body.innerHTML = '<div class="text-center py-5"><div class="spinner-app"></div>'
            + '<p class="widget-sub mt-3 mb-0">Caricamento scheda carta...</p></div>';
        bootstrap.Modal.getOrCreateInstance(modalEl).show();

        fetch(cardUrl(cardId))
            .then(function (response) {
                if (!response.ok) {
                    return response.json().catch(function () { return {}; }).then(function (data) {
                        throw new Error(data.error || 'Errore nel caricamento della carta');
                    });
                }
                return response.json();
            })
            .then(renderCardSheet)
            .catch(function (error) {
                console.error('Scheda carta:', error);
                body.innerHTML = '<div class="scan-error"><strong>Scheda non disponibile</strong><p>'
                    + escapeHtml(error.message || 'Errore sconosciuto') + '</p></div>';
            });
    }

    function trendClass(trend) {
        if (trend === 'buy') return 'up';
        if (trend === 'sell') return 'down';
        return 'warn';
    }

    function widgetZScore(market) {
        var z = market.zscore || 0;
        var pos = Math.max(0, Math.min(100, ((z + 2) / 4) * 100));
        var verdict = z <= -1 ? 'Sottovalutata' : (z >= 1 ? 'Sovravalutata' : 'In linea');
        return ''
            + '<div class="widget">'
            + '  <div class="widget-head"><h6 class="widget-title">Valutazione Z-Score</h6>'
            + '    <i class="bi bi-graph-up-arrow text-faint-app"></i></div>'
            + '  <div class="widget-value ' + (z <= -1 ? 'up' : (z >= 1 ? 'down' : '')) + '">' + z.toFixed(2) + '</div>'
            + '  <div class="widget-sub">' + verdict + ' rispetto alla media 30g</div>'
            + '  <div class="zbar"><span class="zpin" style="left:' + pos + '%"></span></div>'
            + '  <div class="zscale"><span>-2σ</span><span>0</span><span>+2σ</span></div>'
            + '  <div class="widget-rows">'
            + '    <div class="widget-row"><span>Media 30g</span><strong>' + money(market.average) + '</strong></div>'
            + '    <div class="widget-row"><span>Volatilità</span><strong>' + (market.volatility || 0) + '%</strong></div>'
            + '  </div>'
            + '</div>';
    }

    function widgetEma(market) {
        return ''
            + '<div class="widget">'
            + '  <div class="widget-head"><h6 class="widget-title">EMA 7 / 30</h6>'
            + '    <i class="bi bi-activity text-faint-app"></i></div>'
            + '  <div class="widget-value accent">' + money(market.ema7) + '</div>'
            + '  <div class="widget-sub">Media mobile esponenziale (7 giorni)</div>'
            + '  <div class="widget-rows">'
            + '    <div class="widget-row"><span>EMA 30</span><strong>' + money(market.ema30) + '</strong></div>'
            + '    <div class="widget-row"><span>Min / Max 30g</span><strong>' + money(market.min) + ' · ' + money(market.max) + '</strong></div>'
            + '  </div>'
            + '</div>';
    }

    function widgetTrend(market) {
        var cls = trendClass(market.trend);
        var icon = market.trend === 'buy' ? 'bi-arrow-up-right-circle' : (market.trend === 'sell' ? 'bi-arrow-down-right-circle' : 'bi-dash-circle');
        return ''
            + '<div class="widget">'
            + '  <div class="widget-head"><h6 class="widget-title">Trend · ' + escapeHtml(market.trend_label || 'Mantieni') + '</h6>'
            + '    <i class="bi ' + icon + ' text-faint-app"></i></div>'
            + '  <div class="widget-value ' + cls + '">' + escapeHtml(market.trend_label || 'Mantieni') + '</div>'
            + '  <div class="widget-sub">Momentum 30g: ' + (market.momentum > 0 ? '+' : '') + (market.momentum || 0) + '%</div>'
            + '  <div class="widget-rows">'
            + '    <div class="widget-row"><span>Confidenza</span><strong>' + (market.confidence || 0) + '%</strong></div>'
            + '    <div class="widget-row"><span>Fonte dati</span><strong>' + (market.simulated ? 'Simulata' : 'Storica') + '</strong></div>'
            + '  </div>'
            + '</div>';
    }

    function priceRow(label, code, source) {
        var available = source && source.available;
        var amount = available ? money(source.price) : 'Non disponibile';
        var link = (source && source.url && source.url !== '#')
            ? '<a href="' + escapeHtml(source.url) + '" target="_blank" rel="noopener noreferrer">Apri</a>'
            : '';
        return ''
            + '<div class="price-row">'
            + '  <span class="src"><span class="src-dot ' + code + '">' + label.charAt(0) + '</span>' + label + '</span>'
            + '  <span class="d-flex align-items-center gap-2">'
            + '    <span class="amount ' + (available ? '' : 'na') + '">' + amount + '</span>' + link
            + '  </span>'
            + '</div>';
    }

    function buildSheetHeader(data) {
        var market = data.market || {};
        var chips = [];
        if (data.number) chips.push('<span class="chip">#' + escapeHtml(data.number) + '</span>');
        if (data.rarity) chips.push('<span class="chip">' + escapeHtml(data.rarity) + '</span>');
        if (data.hp) chips.push('<span class="chip">' + escapeHtml(data.hp) + ' HP</span>');
        (data.types || []).forEach(function (type) { chips.push('<span class="chip accent">' + escapeHtml(type) + '</span>'); });
        if (data.set_name) chips.push('<span class="chip">' + escapeHtml(data.set_name) + '</span>');
        if (data.artist) chips.push('<span class="chip">' + escapeHtml(data.artist) + '</span>');

        var owned = !!data.owned;
        var actionButton = config.authenticated
            ? '<button type="button" class="btn-app btn-app-success' + (owned ? ' owned' : '') + '"'
                + ' data-action="toggle-own" data-owned="' + (owned ? 'true' : 'false') + '"'
                + ' data-card-id="' + escapeHtml(data.card_id) + '"'
                + ' data-card-name="' + escapeHtml(data.name) + '"'
                + ' data-set-id="' + escapeHtml(data.set_id) + '"'
                + ' data-price="' + (data.main_price || 0) + '">'
                + '<i class="bi ' + (owned ? 'bi-check2-circle' : 'bi-plus-lg') + '"></i> '
                + (owned ? 'Posseduta' : 'Aggiungi alla collezione')
                + '</button>'
            : '<a class="btn-app btn-app-primary" href="/auth/login">'
                + '<i class="bi bi-box-arrow-in-right"></i> Accedi per aggiungere</a>';

        var prices = data.prices || {};
        var marketLink = (prices.cardmarket && prices.cardmarket.url && prices.cardmarket.url !== '#')
            ? '<a class="btn-app btn-app-ghost" href="' + escapeHtml(prices.cardmarket.url) + '" target="_blank"'
                + ' rel="noopener noreferrer"><i class="bi bi-box-arrow-up-right"></i> Cardmarket</a>'
            : '';

        return ''
            + '<div class="row g-3 g-lg-4">'
            + '  <div class="col-12 col-lg-4">'
            + '    <div class="sheet-media"><img src="' + escapeHtml(data.image_url || '') + '"'
            + '         alt="' + escapeHtml(data.name) + '"></div>'
            + '    <div class="d-grid gap-2 mt-3">' + actionButton + marketLink + '</div>'
            + '  </div>'
            + '  <div class="col-12 col-lg-8">'
            + '    <div class="d-flex flex-wrap align-items-start justify-content-between gap-3">'
            + '      <div>'
            + '        <h3 class="sheet-title">' + escapeHtml(data.name) + '</h3>'
            + '        <div class="sheet-meta">' + chips.join('') + '</div>'
            + '      </div>'
            + '      <div class="text-end">'
            + '        <div class="widget-title">Prezzo attuale</div>'
            + '        <div class="widget-value ' + (data.main_price > 0 ? 'up' : 'warn') + '">'
            +          (data.main_price > 0 ? money(data.main_price) : 'N/D') + '</div>'
            + '        <div class="widget-sub">' + escapeHtml(data.main_source || 'nessuna fonte') + '</div>'
            + '      </div>'
            + '    </div>'
            + '    <div class="row g-2 g-md-3 mt-1">'
            + '      <div class="col-12 col-md-4">' + widgetZScore(market) + '</div>'
            + '      <div class="col-12 col-md-4">' + widgetEma(market) + '</div>'
            + '      <div class="col-12 col-md-4">' + widgetTrend(market) + '</div>'
            + '    </div>';
    }

    function buildSheetBody(data) {
        var prices = data.prices || {};

        var adminPanel = (config.isAdmin && config.authenticated)
            ? '<div class="admin-panel mt-3">'
                + '<div class="widget-head"><h6 class="widget-title">Gestione prezzo (Admin)</h6>'
                + '<i class="bi bi-shield-lock text-faint-app"></i></div>'
                + '<div class="d-flex flex-wrap gap-2">'
                + '<input type="number" id="admin-price-input" step="0.01" min="0" placeholder="Prezzo in €"'
                + ' style="max-width:170px;background:var(--app-surface);border:1px solid var(--app-border);'
                + 'color:var(--app-text);border-radius:8px;padding:.4rem .6rem;font-size:.82rem"'
                + ' value="' + (data.main_price || '') + '">'
                + '<button type="button" class="btn-app btn-app-ghost" data-action="save-price"'
                + ' data-card-id="' + escapeHtml(data.card_id) + '"'
                + ' data-card-name="' + escapeHtml(data.name) + '"'
                + ' data-set-id="' + escapeHtml(data.set_id) + '">Salva prezzo</button>'
                + '</div>'
                + '<p class="hint">Il prezzo viene applicato a tutte le collezioni con questa carta.</p>'
                + '</div>'
            : '';

        return ''
            + '    <div class="row g-3 mt-1">'
            + '      <div class="col-12 col-xl-7">'
            + '        <div class="chart-card">'
            + '          <div class="chart-head">'
            + '            <h6 class="widget-title m-0">Andamento 30 giorni</h6>'
            + '            <div class="chart-legend">'
            + '              <span><span class="dot price"></span>Prezzo</span>'
            + '              <span><span class="dot ema"></span>EMA 7</span>'
            + '            </div>'
            + '          </div>'
            + '          <div id="market-chart"><canvas id="market-chart-canvas"></canvas></div>'
            + '        </div>'
            + '      </div>'
            + '      <div class="col-12 col-xl-5">'
            + '        <div class="widget h-100">'
            + '          <div class="widget-head"><h6 class="widget-title">Prezzi di mercato</h6></div>'
            +            priceRow('Cardmarket', 'cm', prices.cardmarket)
            +            priceRow('TCGPlayer', 'tcg', prices.tcgplayer)
            +            priceRow('eBay', 'ebay', prices.ebay)
            + '        </div>'
            + '      </div>'
            + '    </div>'
            +      adminPanel
            + '  </div>'
            + '</div>';
    }

    function renderCardSheet(data) {
        var body = qs('#cardModalBody');
        if (!body) return;
        body.innerHTML = buildSheetHeader(data) + buildSheetBody(data);
        var title = qs('#cardModalTitle');
        if (title) title.textContent = data.name || 'Scheda carta';
        renderMarketChart(data.market || {});
    }

    /* ---------- grafico (Chart.js) ---------- */
    function emaSeries(values, period) {
        if (!values.length) return [];
        var k = 2 / (period + 1);
        var out = [values[0]];
        for (var i = 1; i < values.length; i++) {
            out.push(values[i] * k + out[i - 1] * (1 - k));
        }
        return out;
    }

    function renderMarketChart(market) {
        var box = qs('#market-chart');
        var canvas = qs('#market-chart-canvas');
        if (!box || !canvas) return;

        if (typeof Chart === 'undefined') {
            box.innerHTML = '<p class="widget-sub m-0">Libreria grafici non disponibile.</p>';
            return;
        }
        if (state.chart) { state.chart.destroy(); state.chart = null; }

        var history = (market && market.history) || [];
        if (!history.length) {
            box.innerHTML = '<p class="widget-sub m-0">Nessun dato storico disponibile per questa carta.</p>';
            return;
        }

        var labels = history.map(function (point) { return String(point.date || '').slice(5); });
        var prices = history.map(function (point) { return point.price; });
        var ctx = canvas.getContext('2d');
        var fill = ctx.createLinearGradient(0, 0, 0, 240);
        fill.addColorStop(0, 'rgba(99, 102, 241, 0.35)');
        fill.addColorStop(1, 'rgba(99, 102, 241, 0)');

        state.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Prezzo', data: prices, borderColor: '#818cf8', backgroundColor: fill,
                        borderWidth: 2, fill: true, tension: 0.35, pointRadius: 0,
                        pointHoverRadius: 4, pointHoverBackgroundColor: '#fff'
                    },
                    {
                        label: 'EMA 7', data: emaSeries(prices, 7), borderColor: '#22d3ee',
                        borderWidth: 1.6, borderDash: [5, 4], fill: false, tension: 0.35,
                        pointRadius: 0, pointHoverRadius: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(8, 15, 28, .95)',
                        borderColor: 'rgba(148, 163, 184, .25)',
                        borderWidth: 1,
                        titleColor: '#e7eefb',
                        bodyColor: '#cbd5e1',
                        callbacks: {
                            label: function (item) {
                                return item.dataset.label + ': €' + Number(item.parsed.y).toFixed(2);
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: 'rgba(148, 163, 184, .08)' },
                        ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 7 }
                    },
                    y: {
                        grid: { color: 'rgba(148, 163, 184, .08)' },
                        ticks: {
                            color: '#64748b', font: { size: 10 },
                            callback: function (value) { return '€' + value; }
                        }
                    }
                }
            }
        });
    }

    /* ---------- admin: prezzo manuale ---------- */
    function saveAdminPrice(button) {
        var input = qs('#admin-price-input');
        if (!input) return;
        var price = parseFloat(input.value);
        if (isNaN(price) || price < 0) {
            showToast('Inserisci un prezzo valido', 'error');
            return;
        }
        button.disabled = true;
        postJson(config.urls.adminPrice, {
            card_id: button.dataset.cardId,
            name: button.dataset.cardName,
            set_id: button.dataset.setId,
            price: price,
            language: getLanguage()
        }).then(function (data) {
            showToast(data.message || 'Prezzo aggiornato', 'success');
            refreshStats();
            openCardSheet(button.dataset.cardId);
        }).catch(function (error) {
            showToast(error.message || 'Errore nel salvataggio del prezzo', 'error');
        }).finally(function () { button.disabled = false; });
    }

    function syncSheetOwnership(cardId, owned) {
        if (state.currentCardId !== cardId) return;
        var btn = qs('#cardModalBody [data-action="toggle-own"]');
        if (!btn) return;
        btn.classList.toggle('owned', owned);
        btn.innerHTML = '<i class="bi ' + (owned ? 'bi-check2-circle' : 'bi-plus-lg') + '"></i> '
            + (owned ? 'Posseduta' : 'Aggiungi alla collezione');
    }

    /* ======================================================================
       SCANNER FOTOCAMERA
       ====================================================================== */
    function setScanHint(message, isError) {
        var hint = qs('#scan-hint');
        if (!hint) return;
        hint.textContent = message;
        hint.classList.toggle('error', !!isError);
    }
    function setScanLoading(active) {
        var box = qs('#scan-loading');
        if (box) box.classList.toggle('d-none', !active);
    }
    function setScanStageVisible(visible) {
        var stage = qs('#scan-stage');
        if (stage) stage.classList.toggle('d-none', !visible);
    }
    function resetScanner() {
        state.scanBusy = false;
        var result = qs('#scan-result');
        if (result) { result.innerHTML = ''; result.classList.add('d-none'); }
        setScanLoading(false);
        setScanStageVisible(true);
        var btn = qs('#scan-capture');
        if (btn) btn.disabled = false;
        setScanHint('Inquadra la carta nel riquadro e premi "Scatta foto".');
    }
    function stopScanner() {
        if (state.scanStream) {
            state.scanStream.getTracks().forEach(function (track) { track.stop(); });
            state.scanStream = null;
        }
        var video = qs('#scan-video');
        if (video) video.srcObject = null;
    }
    function startScanner() {
        var video = qs('#scan-video');
        if (!video) return;

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            var message = window.isSecureContext
                ? 'Fotocamera non supportata da questo browser.'
                : 'La fotocamera richiede una connessione sicura (HTTPS o localhost).';
            setScanHint(message, true);
            var captureBtn = qs('#scan-capture');
            if (captureBtn) captureBtn.disabled = true;
            return;
        }

        navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 960 } },
            audio: false
        }).then(function (stream) {
            state.scanStream = stream;
            video.srcObject = stream;
            var playing = video.play();
            if (playing && playing.catch) playing.catch(function () {});
            setScanHint('Inquadra la carta nel riquadro e premi "Scatta foto".');
        }).catch(function (error) {
            console.error('Fotocamera:', error);
            var message = 'Impossibile accedere alla fotocamera.';
            if (error && (error.name === 'NotAllowedError' || error.name === 'SecurityError')) {
                message = 'Permesso fotocamera negato: abilita la fotocamera per questo sito.';
            } else if (error && error.name === 'NotFoundError') {
                message = 'Nessuna fotocamera disponibile su questo dispositivo.';
            } else if (!window.isSecureContext) {
                message = 'La fotocamera richiede una connessione sicura (HTTPS o localhost).';
            }
            setScanHint(message, true);
            var btn = qs('#scan-capture');
            if (btn) btn.disabled = true;
            showToast(message, 'error');
        });
    }
    function openScanner() {
        var modal = qs('#scanModal');
        if (!modal) return;
        resetScanner();
        bootstrap.Modal.getOrCreateInstance(modal).show();
        startScanner();
    }

    function renderScanResult(data) {
        var result = qs('#scan-result');
        if (!result) return;
        var card = data.card || {};
        setScanStageVisible(false);
        setScanHint('Scansione completata.');
        result.classList.remove('d-none');
        result.innerHTML = '<div class="scan-result-card">'
            + (card.image_url ? '<img src="' + escapeHtml(card.image_url) + '" alt="' + escapeHtml(card.name) + '">' : '')
            + '<div>'
            + '  <span class="chip up">' + (data.owned ? 'Aggiunta alla collezione' : 'Carta trovata') + '</span>'
            + '  <h6>' + escapeHtml(card.name || '') + '</h6>'
            + '  <p>#' + escapeHtml(card.number || '?')
            +      (card.set_name ? ' · ' + escapeHtml(card.set_name) : '') + '</p>'
            + '  <p class="price">' + (card.price_available ? money(card.price) : 'Prezzo non disponibile') + '</p>'
            + '</div></div>';
    }

    function renderScanError(message) {
        var result = qs('#scan-result');
        if (!result) return;
        setScanStageVisible(false);
        result.classList.remove('d-none');
        result.innerHTML = '<div class="scan-error"><strong>Scansione non riuscita</strong>'
            + '<p>' + escapeHtml(message) + '</p>'
            + '<button type="button" class="btn-app btn-app-ghost" data-action="scan-retry">'
            + '<i class="bi bi-arrow-clockwise"></i> Riprova</button></div>';
    }

    function captureScan() {
        if (state.scanBusy) return;
        var video = qs('#scan-video');
        var canvas = qs('#scan-canvas');
        if (!video || !canvas || !video.videoWidth) {
            setScanHint('Fotocamera non pronta: attendi un istante e riprova.', true);
            return;
        }

        var maxWidth = 1024;
        var scale = Math.min(1, maxWidth / video.videoWidth);
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        var imageData = canvas.toDataURL('image/jpeg', 0.85);

        state.scanBusy = true;
        stopScanner();
        setScanLoading(true);
        setScanHint('Analisi in corso...');
        var captureBtn = qs('#scan-capture');
        if (captureBtn) captureBtn.disabled = true;

        postJson(config.urls.scan, { image: imageData, language: getLanguage() })
            .then(function (data) {
                renderScanResult(data);
                showToast(data.message || 'Carta riconosciuta', 'success');
                refreshStats();
                if (data.card && data.card.card_id) {
                    setCardOwnedState(data.card.card_id, true);
                    applyFilter();
                }
            })
            .catch(function (error) {
                var message = error.message || 'Errore durante la scansione';
                setScanHint(message, true);
                renderScanError(message);
            })
            .finally(function () {
                setScanLoading(false);
                state.scanBusy = false;
                if (captureBtn) captureBtn.disabled = false;
            });
    }

    /* ======================================================================
       DELEGAZIONE EVENTI + AVVIO
       ====================================================================== */
    function initDelegation() {
        document.addEventListener('click', function (event) {
            var target = event.target.closest ? event.target.closest('[data-action]') : null;
            if (!target) return;
            var action = target.dataset.action;

            if (action === 'open-card') {
                event.preventDefault();
                openCardSheet(target.dataset.cardId);
            } else if (action === 'toggle-own') {
                event.preventDefault();
                event.stopPropagation();
                toggleCardOwnership(target);
            } else if (action === 'save-price') {
                event.preventDefault();
                saveAdminPrice(target);
            } else if (action === 'scan-open') {
                event.preventDefault();
                openScanner();
            } else if (action === 'scan-capture') {
                event.preventDefault();
                captureScan();
            } else if (action === 'scan-retry') {
                event.preventDefault();
                resetScanner();
                startScanner();
            } else if (action === 'set-nav') {
                event.preventDefault();
                showLoading('Caricamento espansione...');
                window.location.href = '/set/' + encodeURIComponent(target.dataset.setId || '');
            }
        });

        // Accessibilità: apertura della scheda con Invio/Spazio
        document.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            var target = event.target.closest ? event.target.closest('[data-action="open-card"]') : null;
            if (!target) return;
            event.preventDefault();
            openCardSheet(target.dataset.cardId);
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initDelegation();
        initFilters();
        applyFilter();
        hideLoading();

        var languageSelector = qs('#language-selector');
        if (languageSelector) {
            languageSelector.addEventListener('change', function () { changeLanguage(this.value); });
        }

        var scanModal = qs('#scanModal');
        if (scanModal) scanModal.addEventListener('hidden.bs.modal', stopScanner);

        if (config.authenticated) {
            loadCollectionState();
            refreshStats();
        }
    });
})();
