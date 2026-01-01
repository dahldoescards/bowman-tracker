/**
 * 2025 Bowman Draft Box Tracker - Main Application
 * 
 * Features:
 * - Real-time price tracking with TradingView Lightweight Charts
 * - Candlestick-style investment chart visualization
 * - Variant-specific charts (Jumbo, Breaker's Delight, Hobby)
 * - Sales table with filtering and pagination
 */

// ============================================================================
// Configuration
// ============================================================================
const API_BASE = window.location.origin + '/api';
const REFRESH_INTERVAL = 60000; // 1 minute auto-refresh
const DEBOUNCE_MS = 300; // Debounce delay for rapid clicks

// Variant colors for charts (matching the design system)
const VARIANT_COLORS = {
    jumbo: { up: '#818cf8', down: '#6366f1', line: '#6366f1' },
    breakers_delight: { up: '#f472b6', down: '#ec4899', line: '#ec4899' },
    hobby: { up: '#34d399', down: '#10b981', line: '#10b981' },
    all: { up: '#22c55e', down: '#ef4444', line: '#3b82f6' }
};

const VARIANT_LABELS = {
    jumbo: 'Jumbo',
    breakers_delight: "Breaker's Delight",
    hobby: 'Hobby'
};

// ============================================================================
// Application State
// ============================================================================
const state = {
    currentVariant: 'all',
    currentRange: '30d',
    salesData: {},
    chart: null,
    chartSeries: [], // Array to hold multiple series for multi-variant view
    pagination: { page: 1, perPage: 15 },
    refreshTimer: null,
    cache: new Map(), // Simple cache for API responses
    cacheTimeout: 30000, // Cache for 30 seconds
    pendingRequests: new Map() // Prevent duplicate requests
};

// ============================================================================
// Utility Functions
// ============================================================================

function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2
    }).format(value);
}

function formatDate(dateStr) {
    if (!dateStr) return 'N/A';

    let date;
    if (/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
        date = new Date(dateStr + 'T12:00:00');
    } else {
        date = new Date(dateStr);
    }

    if (isNaN(date.getTime())) return dateStr;

    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function truncateText(text, maxLength) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
}

function formatEbayUrl(url) {
    // Append query params to eBay URLs to prevent redirect to active listings
    if (!url) return '#';
    if (url.includes('ebay.com')) {
        const separator = url.includes('?') ? '&' : '?';
        return url + separator + 'nordt=true&orig_cvip=true&rt=nc';
    }
    return url;
}

function showLoading(show = true) {
    const overlay = document.getElementById('loadingOverlay');
    if (show) {
        overlay.classList.add('visible');
    } else {
        overlay.classList.remove('visible');
    }
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span class="toast-message">${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ============================================================================
// API Functions
// ============================================================================

async function fetchAPI(endpoint, skipCache = false) {
    const cacheKey = endpoint;

    // Check cache first (unless skipCache is true)
    if (!skipCache && state.cache.has(cacheKey)) {
        const cached = state.cache.get(cacheKey);
        if (Date.now() - cached.timestamp < state.cacheTimeout) {
            return cached.data;
        }
        // Cache expired, remove it
        state.cache.delete(cacheKey);
    }

    // Prevent duplicate concurrent requests
    if (state.pendingRequests.has(cacheKey)) {
        return state.pendingRequests.get(cacheKey);
    }

    const requestPromise = (async () => {
        try {
            const response = await fetch(`${API_BASE}${endpoint}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();

            // Cache the response
            state.cache.set(cacheKey, { data, timestamp: Date.now() });

            return data;
        } catch (error) {
            console.error(`API Error (${endpoint}):`, error);
            throw error;
        } finally {
            state.pendingRequests.delete(cacheKey);
        }
    })();

    state.pendingRequests.set(cacheKey, requestPromise);
    return requestPromise;
}

async function postAPI(endpoint, data = {}) {
    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`API Error (${endpoint}):`, error);
        throw error;
    }
}

// ============================================================================
// Data Loading
// ============================================================================

async function loadSummaryData() {
    try {
        const data = await fetchAPI('/summary');
        if (!data.success) throw new Error('Failed to load summary');

        updateSummaryCards(data.summary);
    } catch (error) {
        console.error('Error loading summary:', error);
    }
}

function updateSummaryCards(summary) {
    const variants = ['jumbo', 'breakers_delight', 'hobby'];
    const elementMap = {
        jumbo: { price: 'jumboPrice', cases: 'jumboCases', boxes: 'jumboBoxes', range: 'jumboRange' },
        breakers_delight: { price: 'delightPrice', cases: 'delightCases', boxes: 'delightBoxes', range: 'delightRange' },
        hobby: { price: 'hobbyPrice', cases: 'hobbyCases', boxes: 'hobbyBoxes', range: 'hobbyRange' }
    };

    variants.forEach(variant => {
        const stats = summary[variant] || { avg_price: 0, cases_sold: 0, boxes_sold: 0, min_price: 0, max_price: 0 };
        const els = elementMap[variant];

        const priceEl = document.getElementById(els.price);
        if (priceEl) {
            priceEl.textContent = stats.avg_price ? stats.avg_price.toFixed(2) : '--';
        }

        const casesEl = document.getElementById(els.cases);
        if (casesEl) {
            casesEl.textContent = stats.cases_sold || '0';
        }

        const boxesEl = document.getElementById(els.boxes);
        if (boxesEl) {
            // Show total boxes sold (including boxes from cases)
            boxesEl.textContent = stats.total_boxes || '0';
        }

        const rangeEl = document.getElementById(els.range);
        if (rangeEl && stats.min_price && stats.max_price) {
            rangeEl.textContent = `$${stats.min_price.toFixed(0)}-$${stats.max_price.toFixed(0)}`;
        }
    });
}

async function loadChartData(variant = 'all') {
    try {
        const endDate = new Date();
        let startDate = new Date();

        switch (state.currentRange) {
            case '7d': startDate.setDate(endDate.getDate() - 7); break;
            case '30d': startDate.setDate(endDate.getDate() - 30); break;
            case '90d': startDate.setDate(endDate.getDate() - 90); break;
            case 'all': startDate = null; break;
        }

        let url = `/chart/${variant}`;
        if (startDate) {
            url += `?start_date=${startDate.toISOString().split('T')[0]}`;
        }

        const data = await fetchAPI(url);
        if (!data.success) throw new Error('Failed to load chart data');

        state.salesData = data;
        updateCandlestickChart(data, variant);

    } catch (error) {
        console.error('Error loading chart data:', error);
    }
}

async function loadSalesTable(variant = 'all') {
    try {
        const url = variant === 'all' ? '/sales' : `/sales/${variant}`;
        const data = await fetchAPI(url);

        if (!data.success) throw new Error('Failed to load sales');

        renderSalesTable(data.sales);
        updatePagination(data.sales.length);

    } catch (error) {
        console.error('Error loading sales:', error);
    }
}

async function loadSchedulerStatus() {
    try {
        const data = await fetchAPI('/scheduler/status');
        if (!data.success) return;

        const status = data.status;

        document.getElementById('schedulerStatus').textContent =
            status.running ? 'Running' : 'Stopped';
        document.getElementById('schedulerStatus').className =
            'status-value ' + (status.running ? 'running' : 'stopped');

        document.getElementById('lastFetch').textContent =
            status.last_run ? formatDate(status.last_run) : 'Never';

        document.getElementById('proxiesActive').textContent =
            status.proxies_loaded || '0';

        const summary = await fetchAPI('/summary');
        document.getElementById('totalRecords').textContent =
            summary.total_sales || '0';

    } catch (error) {
        console.error('Error loading status:', error);
    }
}

// ============================================================================
// TradingView Lightweight Charts - Candlestick Style
// ============================================================================

function initChart() {
    const chartContainer = document.getElementById('mainChart');
    if (!chartContainer) return;

    // Clear existing chart
    chartContainer.innerHTML = '';

    // Create chart with dark theme matching our design
    state.chart = LightweightCharts.createChart(chartContainer, {
        width: chartContainer.clientWidth,
        height: 400,
        layout: {
            background: { type: 'solid', color: 'transparent' },
            textColor: '#94a3b8',
            fontFamily: "'Inter', sans-serif",
        },
        grid: {
            vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
            horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: {
                color: 'rgba(255, 255, 255, 0.2)',
                width: 1,
                style: LightweightCharts.LineStyle.Dashed,
            },
            horzLine: {
                color: 'rgba(255, 255, 255, 0.2)',
                width: 1,
                style: LightweightCharts.LineStyle.Dashed,
            },
        },
        rightPriceScale: {
            borderColor: 'rgba(255, 255, 255, 0.1)',
            scaleMargins: { top: 0.1, bottom: 0.1 },
        },
        timeScale: {
            borderColor: 'rgba(255, 255, 255, 0.1)',
            timeVisible: true,
            secondsVisible: false,
        },
        handleScroll: { vertTouchDrag: false },
        handleScale: { axisPressedMouseMove: true },
    });

    // Handle resize
    window.addEventListener('resize', () => {
        if (state.chart) {
            state.chart.applyOptions({ width: chartContainer.clientWidth });
        }
    });
}

function updateCandlestickChart(data, variant) {
    if (!state.chart) {
        initChart();
    }

    // Remove all existing series
    state.chartSeries.forEach(series => {
        try {
            state.chart.removeSeries(series);
        } catch (e) { }
    });
    state.chartSeries = [];

    // For "all" variant, create separate candlestick series for each variant type
    if (variant === 'all') {
        // Group data points by variant
        const variantGroups = {
            jumbo: [],
            breakers_delight: [],
            hobby: []
        };

        data.data_points.forEach(point => {
            const v = point.variant;
            if (variantGroups[v]) {
                variantGroups[v].push(point);
            }
        });

        // Get all timestamps and use actual sale times
        // Small offset per variant (minutes) to prevent exact overlap
        const variantOffsets = { jumbo: 0, breakers_delight: 300, hobby: 600 }; // 0, 5min, 10min offsets

        Object.keys(variantGroups).forEach(variantKey => {
            const points = variantGroups[variantKey];
            if (points.length === 0) return;

            const colors = VARIANT_COLORS[variantKey];
            const offsetSeconds = variantOffsets[variantKey];

            // Sort points by original timestamp
            const sorted = [...points].sort((a, b) => a.x - b.x);

            // Create candlestick data using actual sale timestamps
            // Add small sequential offset (1 hour between each sale of same variant)
            // Plus variant offset to prevent overlap
            const candleData = sorted.map((point, index) => {
                const price = point.y;
                // Use actual timestamp from sale, add index offset for uniqueness
                const actualTime = Math.floor(point.x / 1000) + (index * 3600) + offsetSeconds;
                const variance = price * 0.003; // Small variance for candle body

                return {
                    time: actualTime,
                    open: price - variance,
                    high: price + variance,
                    low: price - variance,
                    close: price + variance,
                };
            });

            // Add candlestick series with variant-specific colors
            const series = state.chart.addCandlestickSeries({
                upColor: colors.up,
                downColor: colors.up, // Use same color for consistent look
                borderUpColor: colors.up,
                borderDownColor: colors.up,
                wickUpColor: colors.up,
                wickDownColor: colors.up,
                title: VARIANT_LABELS[variantKey],
            });

            series.setData(candleData);
            state.chartSeries.push(series);
        });

        state.chart.timeScale().fitContent();
        updateMultiVariantLegend(variantGroups);
    } else {
        // Single variant view - use candlesticks
        const colors = VARIANT_COLORS[variant] || VARIANT_COLORS.all;
        const sortedPoints = [...data.data_points].sort((a, b) => a.x - b.x);

        const candleData = [];

        sortedPoints.forEach((point, index) => {
            const price = point.y;
            // Use actual timestamp from sale, add index offset for uniqueness
            const actualTime = Math.floor(point.x / 1000) + (index * 3600);
            const variance = price * 0.005;

            candleData.push({
                time: actualTime,
                open: price - variance,
                high: price + variance,
                low: price - variance,
                close: price + variance,
            });
        });

        const candleSeries = state.chart.addCandlestickSeries({
            upColor: colors.up,
            downColor: colors.down,
            borderUpColor: colors.up,
            borderDownColor: colors.down,
            wickUpColor: colors.up,
            wickDownColor: colors.down,
        });

        if (candleData.length > 0) {
            candleSeries.setData(candleData);
            state.chart.timeScale().fitContent();
        }

        state.chartSeries.push(candleSeries);
        updateChartLegend(variant, sortedPoints);
    }
}

function updateMultiVariantLegend(variantGroups) {
    const legend = document.getElementById('chartLegend');
    if (!legend) return;

    const legendItems = Object.keys(variantGroups).map(variantKey => {
        const points = variantGroups[variantKey];
        if (points.length === 0) return '';

        const prices = points.map(p => p.y);
        const avg = prices.reduce((a, b) => a + b, 0) / prices.length;
        const colors = VARIANT_COLORS[variantKey];

        return `
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span style="width: 12px; height: 3px; background: ${colors.line}; border-radius: 2px;"></span>
                <span style="color: var(--color-text-tertiary);">${VARIANT_LABELS[variantKey]}:</span>
                <span style="color: ${colors.line}; font-weight: 600; font-family: var(--font-mono);">$${avg.toFixed(2)}</span>
                <span style="color: var(--color-text-muted); font-size: 0.75rem;">(${points.length})</span>
            </div>
        `;
    }).filter(Boolean).join('');

    const totalSales = Object.values(variantGroups).reduce((sum, arr) => sum + arr.length, 0);

    legend.innerHTML = `
        <div style="display: flex; align-items: center; gap: 2rem; flex-wrap: wrap; justify-content: center;">
            ${legendItems}
            <div style="display: flex; align-items: center; gap: 0.5rem; border-left: 1px solid var(--border-color); padding-left: 1rem;">
                <span style="color: var(--color-text-tertiary);">Total:</span>
                <span style="color: var(--color-text-primary); font-weight: 600; font-family: var(--font-mono);">${totalSales} sales</span>
            </div>
        </div>
    `;
}

function updateChartLegend(variant, dataPoints) {
    const legend = document.getElementById('chartLegend');
    if (!legend || dataPoints.length === 0) {
        legend.innerHTML = '<span style="color: var(--color-text-tertiary);">No data for selected period</span>';
        return;
    }

    const prices = dataPoints.map(d => d.y);
    const latest = prices[prices.length - 1];
    const first = prices[0];
    const high = Math.max(...prices);
    const low = Math.min(...prices);
    const avg = prices.reduce((a, b) => a + b, 0) / prices.length;
    const colors = VARIANT_COLORS[variant] || VARIANT_COLORS.all;

    legend.innerHTML = `
        <div style="display: flex; align-items: center; gap: 2rem; flex-wrap: wrap; justify-content: center;">
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span style="width: 12px; height: 3px; background: ${colors.line}; border-radius: 2px;"></span>
                <span style="color: var(--color-text-tertiary);">${VARIANT_LABELS[variant]}:</span>
                <span style="color: var(--color-text-primary); font-weight: 600;">${dataPoints.length} sales</span>
            </div>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span style="color: var(--color-text-tertiary);">Avg:</span>
                <span style="color: var(--color-text-primary); font-weight: 600; font-family: var(--font-mono);">$${avg.toFixed(2)}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span style="color: var(--color-text-tertiary);">High:</span>
                <span style="color: var(--color-success); font-family: var(--font-mono);">$${high.toFixed(2)}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
                <span style="color: var(--color-text-tertiary);">Low:</span>
                <span style="color: var(--color-danger); font-family: var(--font-mono);">$${low.toFixed(2)}</span>
            </div>
        </div>
    `;
}

// ============================================================================
// Table Rendering
// ============================================================================

function renderSalesTable(sales) {
    const tbody = document.getElementById('salesTableBody');
    if (!tbody) return;

    const start = (state.pagination.page - 1) * state.pagination.perPage;
    const end = start + state.pagination.perPage;
    const paginatedSales = sales.slice().reverse().slice(start, end);

    if (paginatedSales.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align: center; padding: 2rem; color: var(--color-text-tertiary);">
                    No sales data available. Click "Manual Fetch" to retrieve data.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = paginatedSales.map(sale => `
        <tr>
            <td>${formatDate(sale.sale_date)}</td>
            <td><span class="variant-badge ${sale.variant_type}">${VARIANT_LABELS[sale.variant_type] || sale.variant_type}</span></td>
            <td title="${sale.title}">
                <a href="${formatEbayUrl(sale.source_url)}" target="_blank" rel="noopener noreferrer" class="sale-link">
                    ${truncateText(sale.title, 45)}
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12" style="margin-left: 4px; opacity: 0.5;">
                        <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
                        <polyline points="15,3 21,3 21,9"/>
                        <line x1="10" y1="14" x2="21" y2="3"/>
                    </svg>
                </a>
            </td>
            <td>${sale.box_count}</td>
            <td class="price-cell">${formatCurrency(sale.sale_price)}</td>
            <td class="price-cell">${formatCurrency(sale.per_box_price)}</td>
        </tr>
    `).join('');
}

function updatePagination(totalItems) {
    const totalPages = Math.ceil(totalItems / state.pagination.perPage);
    const pageInfo = document.getElementById('pageInfo');
    const prevBtn = document.getElementById('prevPage');
    const nextBtn = document.getElementById('nextPage');

    pageInfo.textContent = `Page ${state.pagination.page} of ${totalPages || 1}`;
    prevBtn.disabled = state.pagination.page <= 1;
    nextBtn.disabled = state.pagination.page >= totalPages;
}

// ============================================================================
// Event Handlers
// ============================================================================

function setupEventListeners() {
    // Tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            state.currentVariant = btn.dataset.variant;
            document.getElementById('chartTitle').textContent =
                `Price History - ${btn.dataset.variant === 'all' ? 'All Variants' : VARIANT_LABELS[btn.dataset.variant]}`;

            loadChartData(state.currentVariant);
        });
    });

    // Time range buttons
    document.querySelectorAll('.range-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            state.currentRange = btn.dataset.range;
            loadChartData(state.currentVariant);
        });
    });

    // Variant filter for table
    document.getElementById('variantFilter')?.addEventListener('change', (e) => {
        state.pagination.page = 1;
        loadSalesTable(e.target.value);
    });

    // Pagination
    document.getElementById('prevPage')?.addEventListener('click', () => {
        if (state.pagination.page > 1) {
            state.pagination.page--;
            loadSalesTable(document.getElementById('variantFilter').value);
        }
    });

    document.getElementById('nextPage')?.addEventListener('click', () => {
        state.pagination.page++;
        loadSalesTable(document.getElementById('variantFilter').value);
    });

    // Refresh button
    document.getElementById('refreshBtn')?.addEventListener('click', async () => {
        showLoading(true);
        await loadAllData();
        showLoading(false);
        showToast('Data refreshed successfully', 'success');
    });

    // Scheduler controls
    document.getElementById('startScheduler')?.addEventListener('click', async () => {
        try {
            await postAPI('/scheduler/start');
            showToast('Scheduler started', 'success');
            loadSchedulerStatus();
        } catch (error) {
            showToast('Failed to start scheduler', 'error');
        }
    });

    document.getElementById('stopScheduler')?.addEventListener('click', async () => {
        try {
            await postAPI('/scheduler/stop');
            showToast('Scheduler stopped', 'info');
            loadSchedulerStatus();
        } catch (error) {
            showToast('Failed to stop scheduler', 'error');
        }
    });

    document.getElementById('manualFetch')?.addEventListener('click', async () => {
        showLoading(true);
        try {
            const result = await postAPI('/fetch');
            showToast(`Fetched ${result.stats.new_sales} new sales`, 'success');
            await loadAllData();
        } catch (error) {
            showToast('Fetch failed: ' + error.message, 'error');
        }
        showLoading(false);
    });

    // Summary card clicks
    document.querySelectorAll('.summary-card').forEach(card => {
        card.addEventListener('click', () => {
            const variant = card.dataset.variant;

            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.variant === variant);
            });

            state.currentVariant = variant;
            document.getElementById('chartTitle').textContent =
                `Price History - ${VARIANT_LABELS[variant]}`;

            loadChartData(variant);

            document.querySelector('.charts-section').scrollIntoView({ behavior: 'smooth' });
        });
    });
}

// ============================================================================
// Initialization
// ============================================================================

async function loadAllData() {
    await Promise.all([
        loadSummaryData(),
        loadChartData(state.currentVariant),
        loadSalesTable('all'),
        loadSchedulerStatus()
    ]);
}

async function init() {
    showLoading(true);

    try {
        // Initialize the chart first
        initChart();

        setupEventListeners();
        await loadAllData();

        // Start auto-refresh
        state.refreshTimer = setInterval(loadAllData, REFRESH_INTERVAL);

    } catch (error) {
        console.error('Initialization error:', error);
        showToast('Failed to load initial data. Is the API server running?', 'error');
    }

    showLoading(false);
}

// Start the application
document.addEventListener('DOMContentLoaded', init);
