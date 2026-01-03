# 2025 Bowman Draft Box Tracker

A production-ready web application for tracking sales prices of 2025 Bowman Draft Hobby Boxes with automated hourly data fetching, duplicate detection, and stock-market-style visualizations.

![Bowman Draft Tracker](https://via.placeholder.com/800x400?text=Bowman+Draft+Box+Tracker)

## Features

- **Real-Time Price Tracking**: Monitor live sales data for all three box variants
- **Three Variant Trackers**: Jumbo, Breaker's Delight, and Regular Hobby boxes
- **Smart Price Calculation**: Automatically calculates per-box prices from case sales
- **Duplicate Detection**: Uses eBay product IDs to prevent duplicate entries
- **ML-Based Filtering**: Trained classifier distinguishes box sales from player card sales
- **Automated Data Collection**: Hourly fetching from eBay sold listings
- **Stock-Chart Visualizations**: Interactive candlestick-style charts
- **Modern Premium UI**: Award-winning design with glassmorphism and animations

## Architecture

```
bowman-draft-tracker/
├── backend/
│   ├── app.py                 # Flask API server
│   ├── database.py            # SQLite database management
│   ├── requirements.txt       # Python dependencies
│   ├── services/
│   │   ├── data_fetcher.py    # eBay sales data integration
│   │   ├── scheduler.py       # Automated hourly fetching
│   │   └── title_parser.py    # Title parsing & price calculation
│   └── models/
│       └── player_vs_box_classifier_combined.pkl
├── frontend/
│   ├── index.html             # Main application page
│   ├── css/
│   │   ├── styles.css         # Core design system
│   │   ├── components.css     # Card & chart styles
│   │   └── utilities.css      # Tables & responsive
│   └── js/
│       └── app.js             # Frontend application
├── .env.example               # Environment configuration template
└── README.md                  # This file
```

## Quick Start

### Prerequisites

- Python 3.9+
- Node.js (optional, for development)
- Proxy file for 130point requests

### Installation

1. **Clone or navigate to the project:**
   ```bash
   cd bowman-draft-tracker
   ```

2. **Install Python dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

3. **Copy the classifier model:**
   ```bash
   mkdir -p models
   cp /path/to/player_vs_box_classifier_combined.pkl models/
   ```

4. **Configure environment:**
   ```bash
   cp ../.env.example .env
   # Edit .env with your proxy file path
   ```

5. **Initialize the database:**
   ```bash
   python database.py
   ```

6. **Start the server:**
   ```bash
   python app.py --host 0.0.0.0 --port 5000
   ```

7. **Open in browser:**
   ```
   http://localhost:5000
   ```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sales` | GET | Get all sales with optional filtering |
| `/api/sales/<variant>` | GET | Get sales for specific variant |
| `/api/chart/<variant>` | GET | Get chart-formatted time series data |
| `/api/summary` | GET | Get summary statistics |
| `/api/scheduler/status` | GET | Get scheduler status |
| `/api/scheduler/start` | POST | Start the scheduler |
| `/api/scheduler/stop` | POST | Stop the scheduler |
| `/api/fetch` | POST | Trigger manual data fetch |
| `/api/health` | GET | Health check endpoint |

### Query Parameters

- `variant`: Filter by type (`jumbo`, `breakers_delight`, `hobby`)
- `start_date`: Filter from date (YYYY-MM-DD)
- `end_date`: Filter to date (YYYY-MM-DD)
- `limit`: Maximum results to return

## Database Schema

### Sales Table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| unique_id | TEXT | Unique identifier (eBay ID or URL hash) |
| source | TEXT | Data source (ebay, other) |
| source_url | TEXT | Original listing URL |
| ebay_item_id | TEXT | eBay item number |
| title | TEXT | Listing title |
| sale_price | REAL | Total sale price |
| box_count | INTEGER | Number of boxes in listing |
| per_box_price | REAL | Calculated per-box price |
| variant_type | TEXT | jumbo, breakers_delight, or hobby |
| sale_date | TEXT | Sale date (YYYY-MM-DD) |
| sale_timestamp | INTEGER | Unix timestamp |
| created_at | TEXT | Record creation timestamp |

## Title Parser Logic

The title parser extracts:

1. **Variant Type**: Detects Jumbo, Breaker's Delight, or Hobby from keywords
2. **Box Count**: Parses patterns like "6 box case", "8-box", "case of 12"
3. **Per-Box Price**: Divides total price by box count

### Known Case Sizes

| Variant | Boxes per Case |
|---------|---------------|
| Hobby | 6 boxes |
| Jumbo | 8 boxes |
| Breaker's Delight | 16 boxes |

## Proxy Configuration

Create a proxy file with one proxy per line in format:
```
host:port:username:password
```

Example:
```
proxy1.example.com:8080:user:pass123
proxy2.example.com:8080:user:pass456
```

## Scheduler

The scheduler runs hourly by default. Control it via:

- **UI**: Use the "Start/Stop Scheduler" buttons
- **API**: POST to `/api/scheduler/start` or `/api/scheduler/stop`
- **CLI**: Run `python services/scheduler.py --once` for single fetch

## Development

### Running in Development Mode

```bash
python app.py --debug --host 127.0.0.1 --port 5000
```

### Testing the Title Parser

```bash
cd backend
python services/title_parser.py
```

### Testing the Data Fetcher

```bash
cd backend
python services/data_fetcher.py
```

## Production Deployment

### 🚀 Production Checklist

Before deploying to production, ensure:

- [ ] `SECRET_KEY` environment variable is set to a secure random string
- [ ] `FLASK_ENV=production` is set
- [ ] `DATABASE_URL` is set (for PostgreSQL) or database is persistent
- [ ] `USE_PROXIES=false` (unless you have working proxies)
- [ ] Cron job is configured for hourly data fetching
- [ ] Health check endpoint `/api/health` is monitored

### Database Options

| Environment | Database | Configuration |
|-------------|----------|---------------|
| Development | SQLite | Automatic (no config needed) |
| Production | PostgreSQL | Set `DATABASE_URL` env var |

The app automatically detects which database to use based on the `DATABASE_URL` environment variable.

### Option 1: Render (Recommended)

1. **Push to GitHub**
2. **Connect Render to your repo**: [render.com](https://render.com)
3. **Use the `render.yaml`** blueprint (auto-configures web + cron + PostgreSQL)
4. **Add environment variables**:
   ```
   SECRET_KEY=your-secure-random-string-here
   USE_PROXIES=false
   FLASK_ENV=production
   ```

### Option 2: Railway

1. **Push to GitHub**
2. **Connect Railway to your repo**: [railway.app](https://railway.app)
3. **Add PostgreSQL database** from Railway marketplace
4. **Add environment variables**:
   ```
   SECRET_KEY=your-secure-random-string-here
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   USE_PROXIES=false
   FLASK_ENV=production
   ```
5. **Add a cron job** for hourly fetching:
   - Create a new service → Cron
   - Schedule: `0 * * * *`
   - Command: `cd backend && python -c "from services.scheduler import run_single_fetch; run_single_fetch()"`

### Option 3: Local Production with Gunicorn

```bash
pip install gunicorn
cd backend
SECRET_KEY=your-key FLASK_ENV=production gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 app:app
```

### Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `SECRET_KEY` | - | ✅ Production | Secure random string for admin authentication |
| `DATABASE_URL` | - | ⚠️ Recommended | PostgreSQL connection string |
| `FLASK_ENV` | `development` | ✅ Production | Set to `production` |
| `USE_PROXIES` | `true` | - | Set to `false` for cloud |
| `PORT` | `5000` | - | Server port |
| `DB_POOL_MIN` | `5` | - | Min database connections |
| `DB_POOL_MAX` | `20` | - | Max database connections |

## Security

### API Access Control

All API endpoints are protected and only accessible from:
- **Same-origin requests** (the frontend at bowmandrafttracker.com)
- **Admin requests** with valid `X-Admin-Key` header
- **Health check** (`/api/health`) is open for monitoring

External requests (curl, Postman, other websites) will receive:
```json
{"success": false, "error": "API access restricted to authorized clients only"}
```

### Protected Admin Endpoints

These endpoints require `X-Admin-Key` header or `key` in JSON body:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/scheduler/start` | POST | Start scheduler |
| `/api/scheduler/stop` | POST | Stop scheduler |
| `/api/fetch` | POST | Manual data fetch |
| `/api/refetch` | POST | Delete and re-fetch data |
| `/api/sales/<id>` | PATCH | Update sale record |

### Rate Limiting

All public endpoints are rate-limited to **60 requests per minute per IP**.

### Security Headers

The application sets these security headers on all responses:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy` (restricts script/style sources)
- `Strict-Transport-Security` (HTTPS only, production)


### Automatic Data Fetching

In production, set up a cron job to run hourly:

```bash
# Runs every hour at minute 0
0 * * * * cd /path/to/backend && python -c "from services.scheduler import run_single_fetch; run_single_fetch()"
```


## Troubleshooting

### No data appearing

1. Check if the proxy file path is correct in `.env`
2. Verify proxies are working: `curl --proxy http://user:pass@host:port https://back.130point.com/`
3. Try a manual fetch from the UI

### Classifier not loading

1. Ensure the `.pkl` file is in `backend/models/`
2. Check scikit-learn version matches the training version

### Database errors

1. Delete `sales_history.db` and re-run `python database.py`
2. Check file permissions

## License

MIT License

## Credits

- Data sourced from eBay sold listings
- Charts powered by [TradingView Lightweight Charts](https://tradingview.github.io/lightweight-charts/)
- Design inspired by modern fintech dashboards
