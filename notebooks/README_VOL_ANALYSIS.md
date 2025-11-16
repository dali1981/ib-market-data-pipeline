# Volatility Term Structure Analysis

## Notebook: 05_volatility_term_structure_earnings.ipynb

### Overview
Analyzes **implied volatility collapse** around earnings to visualize the edge that calendar spread strategies capture.

### What It Shows

1. **Volatility Smiles** - IV across strikes for each expiration
2. **Term Structure** - IV across maturities by moneyness (ATM/OTM/ITM)
3. **IV Collapse Heatmap** - Strike × Maturity visualization
4. **Differential Collapse** - Quantifies calendar spread edge

### Key Finding

Calendar spreads profit from **differential IV collapse**:
- Short-term options lose MORE IV after earnings
- Long-term options retain MORE IV
- This differential = profit opportunity

### Dependencies

**Package**: `dlt-ibapi` (installed via uv)
- `dlt_ibapi.utils.black_scholes` - IV calculation
- `dlt_ibapi.repositories` - Data readers

**External**: `scipy`, `pandas`, `matplotlib`, `seaborn`, `duckdb`

### Usage

```bash
cd notebooks
jupyter lab 05_volatility_term_structure_earnings.ipynb
```

### Implementation Notes

- Uses scipy-based Black-Scholes IV solver (Python 3.13 compatible)
- No external vollib dependencies (had compatibility issues)
- Clean imports - no sys.path manipulation
- All logic in installed package, not notebook code

### Related Notebooks

- `03_calendar_spread_tmc_earnings.ipynb` - Single trade P&L
- `04_calendar_spread_earnings_backtest.ipynb` - Multi-event backtest
