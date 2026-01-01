# 2025 Bowman Draft Box Tracker

A production-ready web application for tracking sales prices of 2025 Bowman Draft Hobby Boxes with automated hourly data fetching, duplicate detection, and stock-market-style visualizations.

![Bowman Draft Tracker](https://via.placeholder.com/800x400?text=Bowman+Draft+Box+Tracker)

## Features

- **Real-Time Price Tracking**: Monitor live sales data for all three box variants
- **Three Variant Trackers**: Jumbo, Breaker's Delight, and Regular Hobby boxes
- **Smart Price Calculation**: Automatically calculates per-box prices from case sales
- **Duplicate Detection**: Uses eBay product IDs to prevent duplicate entries
- **ML-Based Filtering**: Trained classifier distinguishes box sales from player card sales
- **Automated Data Collection**: Hourly fetching via 130point.com with proxy rotation
- **Stock-Chart Visualizations**: Interactive Chart.js scatter plots with tooltips
- **Modern Premium UI**: Award-winning design with glassmorphism and animations

## Architecture

```
bowman-draft-tracker/
├── backend/
│   ├── app.py                 # Flask API server
│   ├── database.py            # SQLite database management
│   ├── requirements.txt       # Python dependencies
│   ├── services/
│   │   ├── data_fetcher.py    # 130point API integration
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

### Option 1: Railway (Recommended)

1. **Push to GitHub**
2. **Connect Railway to your repo**: [railway.app](https://railway.app)
3. **Add environment variables**:
   ```
   USE_PROXIES=false
   FLASK_ENV=production
   ```
4. **Add a cron job** for hourly fetching:
   - Create a new service → Cron
   - Schedule: `0 * * * *`
   - Command: `cd backend && python -c "from services.scheduler import run_single_fetch; run_single_fetch()"`

### Option 2: Render

1. **Push to GitHub**
2. **Connect Render to your repo**: [render.com](https://render.com)
3. **Use the `render.yaml`** blueprint (auto-configures web + cron job)
4. **Environment variables are set automatically**

### Option 3: Local Production with Gunicorn

```bash
pip install gunicorn
cd backend
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 app:app
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_PROXIES` | `true` | Set to `false` for cloud deployment |
| `FLASK_ENV` | `development` | Set to `production` for prod |
| `PORT` | `5000` | Server port |
| `DATABASE_PATH` | `./sales_history.db` | SQLite database location |

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

- Data sourced from [130point.com](https://130point.com)
- Charts powered by [Chart.js](https://chartjs.org)
- Design inspired by modern fintech dashboards
