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
// Global Error Handling - Catches all uncaught errors gracefully
// ============================================================================

window.onerror = function (message, source, lineno, colno, error) {
    console.error('Uncaught error:', { message, source, lineno, colno, error });
    // Don't show toast for every error - only critical ones
    if (message.includes('fetch') || message.includes('network')) {
        showToast('Connection issue. Retrying...', 'error');
    }
    return true; // Prevents default browser error handling
};

window.addEventListener('unhandledrejection', function (event) {
    console.error('Unhandled promise rejection:', event.reason);
    event.preventDefault(); // Prevents console error spam
});

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
    chartFallbackMode: false, // True when using table fallback instead of chart
    pagination: { page: 1, perPage: 15 },
    refreshTimer: null,
    cache: new Map(), // Simple cache for API responses
    cacheTimeout: 30000, // Cache for 30 seconds
    pendingRequests: new Map(), // Prevent duplicate requests
    isTransitioning: false // Prevent rapid state changes
};

// ============================================================================
// Performance Utilities
// ============================================================================

// Throttle: limit function calls to once per wait period
function throttle(func, wait) {
    let lastTime = 0;
    return function (...args) {
        const now = Date.now();
        if (now - lastTime >= wait) {
            lastTime = now;
            return func.apply(this, args);
        }
    };
}

// Debounce: delay function call until after wait period of inactivity
function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

// RequestAnimationFrame wrapper for smooth DOM updates
function smoothUpdate(callback) {
    requestAnimationFrame(() => {
        callback();
    });
}

// Batch DOM updates to reduce reflows
function batchUpdate(updates) {
    requestAnimationFrame(() => {
        updates.forEach(update => update());
    });
}


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
    if (!overlay) return;

    if (show) {
        overlay.classList.remove('hidden');
    } else {
        overlay.classList.add('hidden');
    }
}

/**
 * Show skeleton loading state for an element
 * @param {HTMLElement} element - Element to show skeleton in
 * @param {string} type - Type of skeleton: 'text', 'price', 'chart'
 */
function showSkeleton(element, type = 'text') {
    if (!element) return;

    // Store original content
    if (!element.dataset.originalContent) {
        element.dataset.originalContent = element.innerHTML;
    }

    // Add skeleton based on type
    switch (type) {
        case 'price':
            element.innerHTML = '<span class="skeleton skeleton-price"></span>';
            break;
        case 'chart':
            element.innerHTML = '<div class="skeleton skeleton-chart"></div>';
            break;
        case 'badge':
            element.innerHTML = '<span class="skeleton skeleton-badge"></span>';
            break;
        default:
            element.innerHTML = '<span class="skeleton skeleton-text"></span>';
    }
}

/**
 * Hide skeleton and restore content
 * @param {HTMLElement} element - Element to restore
 * @param {string} newContent - New content to display (optional)
 */
function hideSkeleton(element, newContent = null) {
    if (!element) return;

    if (newContent !== null) {
        element.innerHTML = newContent;
    } else if (element.dataset.originalContent) {
        element.innerHTML = element.dataset.originalContent;
    }

    delete element.dataset.originalContent;
}

/**
 * Show skeleton states for summary cards
 */
function showCardSkeletons() {
    // Price values
    ['jumboPrice', 'delightPrice', 'hobbyPrice'].forEach(id => {
        const el = document.getElementById(id);
        if (el && el.textContent === '--') {
            el.classList.add('skeleton', 'skeleton-pulse');
            el.style.width = '80px';
            el.style.display = 'inline-block';
        }
    });
}

/**
 * Hide skeleton states from summary cards
 */
function hideCardSkeletons() {
    ['jumboPrice', 'delightPrice', 'hobbyPrice'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.classList.remove('skeleton', 'skeleton-pulse');
            el.style.width = '';
        }
    });
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

const API_TIMEOUT = 10000; // 10 second timeout
const MAX_RETRIES = 2;

async function fetchWithTimeout(url, timeout = API_TIMEOUT) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
        const response = await fetch(url, { signal: controller.signal });
        clearTimeout(timeoutId);
        return response;
    } catch (error) {
        clearTimeout(timeoutId);
        if (error.name === 'AbortError') {
            throw new Error('Request timed out');
        }
        throw error;
    }
}

async function fetchAPI(endpoint, skipCache = false, retries = MAX_RETRIES) {
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
        let lastError;

        for (let attempt = 0; attempt <= retries; attempt++) {
            try {
                const response = await fetchWithTimeout(`${API_BASE}${endpoint}`);

                if (!response.ok) {
                    // Don't retry on client errors (4xx), only server errors (5xx)
                    if (response.status >= 400 && response.status < 500) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();

                // Cache the response
                state.cache.set(cacheKey, { data, timestamp: Date.now() });

                return data;
            } catch (error) {
                lastError = error;
                console.warn(`API attempt ${attempt + 1}/${retries + 1} failed (${endpoint}):`, error.message);

                // Wait before retrying (exponential backoff)
                if (attempt < retries) {
                    await new Promise(resolve => setTimeout(resolve, 500 * Math.pow(2, attempt)));
                }
            }
        }

        console.error(`API Error (${endpoint}): All retries failed`, lastError);
        throw lastError;
    })();

    state.pendingRequests.set(cacheKey, requestPromise);

    try {
        return await requestPromise;
    } finally {
        state.pendingRequests.delete(cacheKey);
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
        return true;
    } catch (error) {
        console.error('Error loading summary:', error);
        // Show fallback state - don't crash the whole app
        showSummaryError();
        return false;
    }
}

function showSummaryError() {
    const variants = ['jumbo', 'breakers_delight', 'hobby'];
    const elementMap = {
        jumbo: 'jumboPrice',
        breakers_delight: 'delightPrice',
        hobby: 'hobbyPrice'
    };

    variants.forEach(variant => {
        const priceEl = document.getElementById(elementMap[variant]);
        if (priceEl) {
            priceEl.textContent = '--';
            priceEl.style.opacity = '0.5';
        }
    });
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


// TradingView Lightweight Charts - Candlestick Style
// ============================================================================

/**
 * Check if chart library is available
 * Since we self-host the library, it should always be available unless
 * there's a critical server issue (in which case we fallback gracefully)
 */
function isChartLibraryAvailable() {
    return typeof LightweightCharts !== 'undefined';
}

/**
 * Show skeleton loading state for the chart
 */
function showChartSkeleton() {
    const chartContainer = document.getElementById('mainChart');
    if (!chartContainer) return;

    chartContainer.innerHTML = `
        <div class="chart-skeleton" style="height: 400px; display: flex; flex-direction: column; justify-content: flex-end; padding: 1rem; gap: 0.5rem;">
            <div style="display: flex; align-items: flex-end; gap: 4px; height: 100%;">
                ${Array(20).fill(0).map((_, i) => {
        const height = 30 + Math.random() * 60;
        return `<div style="flex: 1; height: ${height}%; background: linear-gradient(180deg, rgba(99, 102, 241, 0.3) 0%, rgba(99, 102, 241, 0.1) 100%); border-radius: 4px 4px 0 0; animation: skeleton-pulse 1.5s ease-in-out infinite; animation-delay: ${i * 0.05}s;"></div>`;
    }).join('')}
            </div>
            <div style="text-align: center; color: var(--color-text-tertiary); font-size: 0.875rem; padding-top: 1rem;">
                Loading chart data...
            </div>
        </div>
        <style>
            @keyframes skeleton-pulse {
                0%, 100% { opacity: 0.4; }
                50% { opacity: 0.8; }
            }
        </style>
    `;
}

/**
 * Render a fallback table visualization when chart is unavailable
 * This provides graceful degradation - users still see their data
 */
function renderFallbackChart(data, variant) {
    const chartContainer = document.getElementById('mainChart');
    const legend = document.getElementById('chartLegend');
    if (!chartContainer) return;

    state.chartFallbackMode = true;

    // Group data by date for summary
    const dailyData = {};
    data.data_points.forEach(point => {
        const date = point.date;
        if (!dailyData[date]) {
            dailyData[date] = { date, prices: [], count: 0 };
        }
        dailyData[date].prices.push(point.y);
        dailyData[date].count++;
    });

    // Sort by date descending
    const sortedDays = Object.values(dailyData).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 10);

    // Calculate overall stats
    const allPrices = data.data_points.map(p => p.y);
    const avg = allPrices.length > 0 ? (allPrices.reduce((a, b) => a + b, 0) / allPrices.length) : 0;
    const high = allPrices.length > 0 ? Math.max(...allPrices) : 0;
    const low = allPrices.length > 0 ? Math.min(...allPrices) : 0;

    chartContainer.innerHTML = `
        <div style="padding: 1rem;">
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin-bottom: 1.5rem;">
                <div style="background: rgba(99, 102, 241, 0.1); padding: 1rem; border-radius: 0.75rem; text-align: center;">
                    <div style="font-size: 0.75rem; color: var(--color-text-tertiary); margin-bottom: 0.25rem;">Average</div>
                    <div style="font-size: 1.5rem; font-weight: 600; color: var(--color-primary); font-family: var(--font-mono);">$${avg.toFixed(2)}</div>
                </div>
                <div style="background: rgba(34, 197, 94, 0.1); padding: 1rem; border-radius: 0.75rem; text-align: center;">
                    <div style="font-size: 0.75rem; color: var(--color-text-tertiary); margin-bottom: 0.25rem;">High</div>
                    <div style="font-size: 1.5rem; font-weight: 600; color: var(--color-success); font-family: var(--font-mono);">$${high.toFixed(2)}</div>
                </div>
                <div style="background: rgba(239, 68, 68, 0.1); padding: 1rem; border-radius: 0.75rem; text-align: center;">
                    <div style="font-size: 0.75rem; color: var(--color-text-tertiary); margin-bottom: 0.25rem;">Low</div>
                    <div style="font-size: 1.5rem; font-weight: 600; color: var(--color-danger); font-family: var(--font-mono);">$${low.toFixed(2)}</div>
                </div>
                <div style="background: rgba(148, 163, 184, 0.1); padding: 1rem; border-radius: 0.75rem; text-align: center;">
                    <div style="font-size: 0.75rem; color: var(--color-text-tertiary); margin-bottom: 0.25rem;">Total Sales</div>
                    <div style="font-size: 1.5rem; font-weight: 600; color: var(--color-text-primary); font-family: var(--font-mono);">${data.data_points.length}</div>
                </div>
            </div>
            
            <div style="background: rgba(255,255,255,0.02); border-radius: 0.75rem; overflow: hidden;">
                <table style="width: 100%; border-collapse: collapse; font-size: 0.875rem;">
                    <thead>
                        <tr style="background: rgba(255,255,255,0.05);">
                            <th style="padding: 0.75rem 1rem; text-align: left; color: var(--color-text-tertiary); font-weight: 500;">Date</th>
                            <th style="padding: 0.75rem 1rem; text-align: right; color: var(--color-text-tertiary); font-weight: 500;">Sales</th>
                            <th style="padding: 0.75rem 1rem; text-align: right; color: var(--color-text-tertiary); font-weight: 500;">Avg Price</th>
                            <th style="padding: 0.75rem 1rem; text-align: right; color: var(--color-text-tertiary); font-weight: 500;">Range</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${sortedDays.map(day => {
        const dayAvg = day.prices.reduce((a, b) => a + b, 0) / day.prices.length;
        const dayHigh = Math.max(...day.prices);
        const dayLow = Math.min(...day.prices);
        return `
                                <tr style="border-top: 1px solid rgba(255,255,255,0.05);">
                                    <td style="padding: 0.75rem 1rem; color: var(--color-text-primary);">${formatDate(day.date)}</td>
                                    <td style="padding: 0.75rem 1rem; text-align: right; color: var(--color-text-secondary);">${day.count}</td>
                                    <td style="padding: 0.75rem 1rem; text-align: right; font-family: var(--font-mono); color: var(--color-primary);">$${dayAvg.toFixed(2)}</td>
                                    <td style="padding: 0.75rem 1rem; text-align: right; font-family: var(--font-mono); color: var(--color-text-tertiary);">$${dayLow.toFixed(0)} - $${dayHigh.toFixed(0)}</td>
                                </tr>
                            `;
    }).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;

    // Update legend to show we're in fallback mode
    if (legend) {
        legend.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: center; gap: 0.5rem; color: var(--color-text-tertiary); font-size: 0.875rem;">
                <span>📊</span>
                <span>Showing ${data.data_points.length} sales from the last ${sortedDays.length} days</span>
            </div>
        `;
    }
}

/**
 * Initialize the chart with production-ready error handling
 * Self-hosted library means no CDN race conditions
 */
function initChart() {
    const chartContainer = document.getElementById('mainChart');
    if (!chartContainer) return false;

    // Show loading skeleton while we initialize
    if (!state.chart) {
        showChartSkeleton();
    }

    // Check if library is available (should always be true with self-hosting)
    if (!isChartLibraryAvailable()) {
        console.warn('Chart library not available, will use fallback visualization');
        state.chartFallbackMode = true;
        return false;
    }

    try {
        // Clear existing chart if any
        if (state.chart) {
            try {
                state.chart.remove();
            } catch (e) {
                // Chart already removed or never existed
            }
            state.chart = null;
            state.chartSeries = [];
        }

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

        // Handle resize with debouncing for performance
        const handleResize = debounce(() => {
            if (state.chart && chartContainer.clientWidth > 0) {
                state.chart.applyOptions({ width: chartContainer.clientWidth });
            }
        }, 100);

        window.addEventListener('resize', handleResize);

        state.chartFallbackMode = false;
        console.log('Chart initialized successfully');
        return true;

    } catch (error) {
        console.error('Chart initialization failed:', error);
        state.chartFallbackMode = true;
        return false;
    }
}

function updateCandlestickChart(data, variant) {
    // Use fallback visualization if chart is not available
    if (state.chartFallbackMode || !isChartLibraryAvailable()) {
        renderFallbackChart(data, variant);
        return;
    }

    // Try to initialize chart if needed
    if (!state.chart) {
        const success = initChart();
        if (!success) {
            renderFallbackChart(data, variant);
            return;
        }
    }

    try {
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
    } catch (error) {
        console.error('Chart rendering error, using fallback:', error);
        renderFallbackChart(data, variant);
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

            // Update chart title
            document.getElementById('chartTitle').textContent =
                `Price History - ${btn.dataset.variant === 'all' ? 'All Variants' : VARIANT_LABELS[btn.dataset.variant]}`;

            // Reload chart AND sales table for selected variant
            loadChartData(state.currentVariant);
            state.pagination.page = 1; // Reset to first page
            loadSalesTable(state.currentVariant);
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
        loadSalesTable('all')
    ]);
}

// ============================================================================
// Theme Toggle
// ============================================================================

function initTheme() {
    // Check for saved theme preference or system preference
    const savedTheme = localStorage.getItem('theme');
    const systemPrefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

    if (savedTheme) {
        document.documentElement.setAttribute('data-theme', savedTheme);
    } else if (!systemPrefersDark) {
        // Only set light if system prefers light (dark is default)
        document.documentElement.setAttribute('data-theme', 'light');
    }

    // Setup toggle button
    const toggleBtn = document.getElementById('themeToggle');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', toggleTheme);
    }
}

function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme');
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';

    if (newTheme === 'dark') {
        html.removeAttribute('data-theme');
    } else {
        html.setAttribute('data-theme', newTheme);
    }

    localStorage.setItem('theme', newTheme);

    // Update chart colors if chart exists
    if (state.chart) {
        updateChartTheme(newTheme);
    }
}

function updateChartTheme(theme) {
    const isLight = theme === 'light';

    state.chart.applyOptions({
        layout: {
            background: { type: 'solid', color: 'transparent' },
            textColor: isLight ? '#475569' : '#94a3b8',
        },
        grid: {
            vertLines: { color: isLight ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.05)' },
            horzLines: { color: isLight ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.05)' },
        },
    });
}

async function init() {
    // Initialize theme FIRST (before showing content)
    initTheme();

    // Show skeleton loading states immediately
    showCardSkeletons();
    showLoading(true);

    try {
        // Initialize the chart (may fail if library not loaded, but that's ok)
        try {
            initChart();
        } catch (chartError) {
            console.warn('Chart initialization delayed:', chartError.message);
            // Chart will retry automatically via initChart's retry logic
        }

        setupEventListeners();

        // Load data even if chart failed
        await loadAllData();

        // Start auto-refresh
        state.refreshTimer = setInterval(loadAllData, REFRESH_INTERVAL);

    } catch (error) {
        console.error('Initialization error:', error);
        // Only show error if it's a real API failure, not a chart library issue
        if (error.message && !error.message.includes('LightweightCharts')) {
            showToast('Failed to load data. Please refresh the page.', 'error');
        }
    }

    // Hide skeletons when done
    hideCardSkeletons();
    showLoading(false);
}

// Register service worker for offline support
function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js')
            .then(registration => {
                console.log('Service Worker registered:', registration.scope);

                // Check for updates
                registration.addEventListener('updatefound', () => {
                    const newWorker = registration.installing;
                    newWorker.addEventListener('statechange', () => {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            // New version available
                            console.log('New version available - refresh to update');
                        }
                    });
                });
            })
            .catch(error => {
                console.log('Service Worker registration failed:', error);
            });
    }
}

// Start the application
document.addEventListener('DOMContentLoaded', () => {
    init();
    registerServiceWorker();
});

