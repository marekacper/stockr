# Stockr — Portfolio Tracker

Stockr is a self-hosted web application for tracking and analyzing an investment portfolio. Built with Python and FastAPI, it runs entirely locally — your data never leaves your machine.

The project was inspired by myfund.pl, extended with quantitative analytics typically found in professional portfolio management tools.

---

## Features

### Portfolio Management

- Support for multiple portfolios with independent transaction histories
- Import transactions from XTB (XLSX) and Polish Treasury Bonds (XLS)
- Manual transaction entry
- Automatic ticker translation for Warsaw Stock Exchange (GPW), London Stock Exchange, and Xetra
- Custom valuation model for Polish Treasury Bonds (TOS, EDO series) — par value plus accrued interest

### Dashboard

- Portfolio value over time with per-asset filtering and date range selection
- Profit and loss chart in PLN
- Asset allocation donut chart broken down by category (ETF, GPW Equities, Bonds)
- Asset weight bar chart sorted by position size
- Invested capital vs. portfolio value over time

### Quantitative Analytics

All return metrics are calculated using Time-Weighted Return (TWR), which eliminates the distorting effect of cash inflows and outflows.

- **Annualized return** — TWR-based, comparable across portfolios regardless of contribution timing
- **Volatility** — annualized standard deviation of daily TWR returns
- **Sharpe Ratio** — excess return per unit of risk, using 5.5% risk-free rate (Polish government bonds)
- **Sortino Ratio** — like Sharpe, but penalizes only downside volatility
- **Maximum Drawdown** — largest peak-to-trough decline in portfolio history
- **Win Rate** — percentage of trading days with positive return
- **Drawdown chart** — continuous drawdown from all-time high
- **Asset correlation matrix** — heatmap of pairwise return correlations with diversification warnings

### Benchmark Comparison

- Compare portfolio TWR against S&P 500, NASDAQ 100, MSCI World ETF, Emerging Markets ETF, Gold, Bitcoin, or any custom ticker
- Adjustable start date for fair comparison from any point in time
- All series normalized to 100 at the selected start date

### Monte Carlo Simulation

- 1,000 simulated portfolio trajectories based on historical TWR statistics
- Percentile bands: 10th, 25th, 50th, 75th, 90th
- Probability of profit and probability of doubling the portfolio
- Optional monthly contribution included in projections

### Rebalancing Tracker

- Define target allocation weights per asset category
- Visual deviation bars showing current vs. target weights
- Buy/sell suggestions with PLN amounts to restore balance

### Dividends

- Automatic dividend history fetch via yfinance, filtered to periods when the asset was actually held
- Manual dividend entry for assets not covered by yfinance
- Monthly heatmap and annual forecast based on current holdings and dividend yield

### Investment Goals

Two calculation modes:

1. **Target amount** — enter a goal amount and deadline, the calculator determines the required monthly contribution using the portfolio's own historical return rate
2. **Fixed contribution** — enter a monthly amount and time horizon, the calculator projects the final portfolio value

Both modes include a projection chart showing portfolio value, total contributions, and investment gain over time.

### Price Alerts

- Alert when a specific stock price drops below or rises above a threshold
- Alert when total portfolio value crosses a level
- Alert when portfolio profit/loss percentage hits a target
- Alert status displayed prominently on the dashboard

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Market data | yfinance |
| Templates | Jinja2 |
| Styling | Tailwind CSS |
| Charts | Chart.js 4.4 |
| Storage | CSV + JSON (local files) |

No database required. All data is stored as plain CSV and JSON files in the `data/` directory.

---

## Installation

**Requirements:** Python 3.12 or higher

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/stockr.git
cd stockr

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Start the application
python3 main.py
```

The application will be available at `http://127.0.0.1:8000`.

---

## Project Structure

```
stockr/
├── main.py                       # FastAPI application and API endpoints
├── requirements.txt
├── data/
│   ├── portfolios.json           # Portfolio metadata
│   ├── portfolios/               # Per-portfolio transaction files (CSV)
│   ├── prices_cache.json         # Price cache (auto-generated)
│   ├── rebalancing_targets.json
│   ├── dividends.json
│   ├── goals.json
│   ├── alerts.json
│   └── imports/                  # Archive of imported files
├── services/
│   ├── portfolios.py             # Portfolio and transaction management
│   ├── prices.py                 # Price fetching with caching
│   ├── history.py                # Portfolio value history builder
│   ├── analytics.py              # Drawdown, risk metrics, correlation, Monte Carlo
│   ├── categories.py             # Asset categorization
│   ├── rebalancing.py            # Rebalancing calculations
│   ├── dividends.py              # Dividend history and forecasting
│   ├── goals.py                  # Investment goal calculations
│   ├── alerts.py                 # Alert evaluation
│   ├── bonds.py                  # Polish Treasury Bond valuation model
│   └── importer.py               # XTB and Treasury Bond file parsers
└── templates/
    ├── dashboard.html
    ├── portfolio.html
    ├── add_transaction.html
    └── upload.html
```

---

## Importing Transactions

**From XTB:**
1. In XTB: History → Cash Operations → Export to XLSX
2. In Stockr: Import → select the file → select the target portfolio

**From Polish Treasury Bonds (obligacjeskarbowe.pl / PKO / BOS):**
1. Export your transaction history as XLS
2. In Stockr: Import → select the XLS file

Duplicate detection is built in — re-importing the same file will not create duplicate transactions.

---

## Asset Categorization

Assets are automatically categorized based on their ticker suffix. You can override or extend the mapping in `services/categories.py`:

```python
MANUAL_CATEGORIES = {
    "VUAA.DE": "ETF",
    "TOS0428": "Obligacje",
    # add your own tickers here
}
```

Default suffix rules:

| Suffix | Exchange | Category |
|---|---|---|
| `.PL` | GPW Warsaw | Akcje GPW |
| `.WA` | GPW Warsaw | Akcje GPW |
| `.DE` | Xetra | ETF |
| `.UK` | London Stock Exchange | ETF |
| `.L` | London Stock Exchange | ETF |

---

## Notes

- Price data is sourced from Yahoo Finance via yfinance. Prices may be delayed or unavailable for some assets.
- Polish Treasury Bonds (TOS, EDO series) are not available on Yahoo Finance. Their value is calculated using a built-in accrual model.
- This application is intended for personal use and does not constitute financial advice.

---

## License

MIT