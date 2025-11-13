# earnings_ibapi - Use Cases Documentation

## Repository Overview

**Location:** `/Users/mohamedali/trading_project/earnings_ibapi`

**Purpose:** Production-grade, event-driven trading data platform for algorithmic trading workflows focused on earnings events.

**Architecture:** Local-first data persistence with PyArrow/Parquet storage, file-based event bus, and FastAPI microservices.

---

## Primary Use Cases

### Use Case 1: Earnings-Based Trading Strategy Execution

**Goal:** Execute automated trading strategies around corporate earnings announcements.

**Workflow:**
```
1. Fetch upcoming earnings calendar (3-60 days ahead)
2. Detect imminent earnings events (within threshold)
3. Generate data collection plans per symbol
4. Backfill historical equity data (1-365 days before earnings)
5. Snapshot option chains (daily around earnings date)
6. Backfill option bars for all strikes/expiries
7. Calculate volatility, Greeks, and option metrics
8. Execute trading strategy
9. Monitor positions and orders
10. Track execution results
```

**Key Components:**
- `ops/jobs/earnings_use_case.py` - Main orchestration
- `earnings/` - Earnings calendar fetching
- `common/repositories/` - Data persistence
- `flow/stages.py` - Prefect workflow stages
- `services/trading_api/` - Order execution

**Data Flow:**
```
NASDAQ API → EarningsCalendarFetcher → EarningsRepository → FileEventBus
                                                                    ↓
                                                          Plan Generator
                                                                    ↓
                                        [Equity Backfill | Option Chains | Option Bars]
                                                                    ↓
                                                        Trading Strategy Execution
```

**Configuration:**
- `EARNINGS_DEFAULT_DAYS_AHEAD=3` - Detection window
- `EARNINGS_ALLOWED_SOURCES=nasdaq` - Data sources
- Plan artifacts: `data/cache/plan/{symbol}_{date}.json`

**Example:**
```python
# Detect upcoming earnings
events = calendar_repo.query_upcoming(days_ahead=7)

# Generate plans
for event in events:
    plan = generate_plan(event.symbol, event.date)
    save_plan(plan)

# Execute plan stages
prepare_equity(plan)  # Backfill bars
prepare_chains(plan)  # Snapshot chains
prepare_bars(plan)    # Backfill option bars
```

---

### Use Case 2: Earnings Calendar Data Aggregation

**Goal:** Maintain an up-to-date, deduplicated earnings calendar from multiple sources.

**Workflow:**
```
1. Schedule daily fetch (cron/Celery)
2. Query NASDAQ API for upcoming earnings
3. Validate and normalize data
4. Store in partitioned Parquet repository
5. Emit data.available event
6. Consumers update downstream caches
7. API serves fresh data to clients
```

**Key Components:**
- `earnings/fetchers/unified.py` - Multi-source fetcher
- `earnings/sources/nasdaq.py` - NASDAQ source
- `common/repositories/earnings.py` - Storage
- `services/calendar_api/` - REST API

**API Endpoints:**
```
GET  /calendar/upcoming?days=7&symbols=AAPL,GOOGL
POST /calendar/fetch-upcoming
GET  /calendar/stats
GET  /calendar/data-availability
```

**Data Storage:**
```
data/earnings/
  collection_date=2025-01-15/
    source=nasdaq/
      part-0.parquet  # Contains: symbol, company, date, time, eps_est, revenue_est
```

**Deduplication Strategy:**
- Quality scoring based on data completeness
- Source priority (NASDAQ > Yahoo > FMP > Finnhub)
- Most recent collection date wins
- Deterministic scoring algorithm

**Example:**
```python
# Fetch and persist
fetcher = UnifiedEarningsCalendarFetcher(sources=['nasdaq'])
events = await fetcher.fetch_upcoming(days_ahead=14)

persistence = EarningsPersistence(repo)
persistence.persist_batch(events, collection_date=today)

# Query
upcoming = repo.query_upcoming(days_ahead=7)
symbol_events = repo.query_by_symbol('AAPL', days_back=30)
```

---

### Use Case 3: Historical Market Data Backfilling

**Goal:** Build complete historical dataset for backtesting and analysis.

**Workflow:**
```
1. Define backfill requirements (symbols, date ranges, bar sizes)
2. Check existing data coverage in repositories
3. Identify gaps in data
4. Fetch missing data from Interactive Brokers
5. Validate and normalize
6. Store in partitioned repositories
7. Update lineage metadata
8. Verify data quality
```

**Key Components:**
- `ops/tasks/backfill.py` - Celery backfill tasks
- `common/repositories/equity_bars.py` - Equity storage
- `common/repositories/option_bars.py` - Option storage
- `services/ib_api/` - IB Gateway integration

**Supported Data Types:**

| Data Type | Repository | Partitioning | Typical Size |
|-----------|------------|--------------|--------------|
| Equity Bars | `EquityBarRepository` | symbol, bar_size | 1M-10M rows/symbol |
| Option Bars | `OptionBarRepository` | symbol, expiry | 10K-100K rows/contract |
| Option Chains | `OptionChainSnapshotRepository` | symbol, snapshot_date | 100-1K rows/snapshot |
| Contracts | `ContractRepository` | symbol, exchange | 1-10 rows/symbol |

**Bar Sizes Supported:**
- Intraday: `1 min`, `5 mins`, `15 mins`, `30 mins`, `1 hour`
- Daily: `1 day`

**Example:**
```python
# Backfill equity bars
equity_repo = EquityBarRepository(data_root)
symbols = ['AAPL', 'GOOGL', 'MSFT']

for symbol in symbols:
    bars = fetch_from_ib(
        symbol=symbol,
        start_date='2024-01-01',
        end_date='2025-01-01',
        bar_size='1 day'
    )
    equity_repo.write_batch(bars)

# Verify coverage
coverage = equity_repo.get_date_range(symbol='AAPL', bar_size='1 day')
print(f"Coverage: {coverage.start} to {coverage.end}")
```

---

### Use Case 4: Real-Time Option Chain Monitoring

**Goal:** Capture daily option chain snapshots around earnings for volatility analysis.

**Workflow:**
```
1. Identify symbols with upcoming earnings
2. Schedule daily snapshots (e.g., -7 days to +2 days around earnings)
3. Fetch option chain from IB at market close
4. Calculate implied volatility, Greeks
5. Store snapshot in repository
6. Emit event for downstream processing
7. Serve via API for frontend visualization
```

**Key Components:**
- `flow/stages.py:prepare_chains()` - Chain collection
- `common/repositories/option_chains.py` - Storage
- `services/option_chain_api/` - REST API

**Snapshot Structure:**
```python
{
    "symbol": "AAPL",
    "snapshot_date": "2025-01-15",
    "snapshot_time": "16:00:00",
    "underlying_price": 185.50,
    "chains": [
        {
            "expiry": "2025-01-20",
            "strike": 180.0,
            "call_bid": 6.50,
            "call_ask": 6.60,
            "call_iv": 0.28,
            "call_delta": 0.65,
            "put_bid": 1.20,
            "put_ask": 1.25,
            "put_iv": 0.26,
            "put_delta": -0.35
        }
    ]
}
```

**Storage:**
```
data/option_chains/
  symbol=AAPL/
    snapshot_date=2025-01-15/
      part-0.parquet
```

**API Usage:**
```
GET /option-chains/latest/AAPL
GET /option-chains/history/AAPL?start=2025-01-01&end=2025-01-15
GET /option-chains/expiry/AAPL/2025-01-20
```

---

### Use Case 5: Event-Driven Data Pipeline

**Goal:** Build loosely-coupled data pipelines where producers and consumers operate independently.

**Workflow:**
```
1. Producer writes data to repository
2. Producer emits event to FileEventBus (JSONL)
3. Consumer reads event from bus
4. Consumer fetches data from repository using event metadata
5. Consumer processes data idempotently
6. Consumer checkpoints progress
7. Consumer emits new events for downstream
```

**Key Components:**
- `common/utils/events/bus.py` - Event bus
- `common/utils/events/consumer.py` - Consumer framework
- `common/utils/events/checkpoint.py` - State management

**Event Topics:**
- `earnings` - New earnings data available
- `option_chains` - New chain snapshots
- `option_bars` - New option bars
- `equity_bars` - New equity bars
- `contracts` - New contract metadata

**Event Format (JSONL):**
```json
{
  "topic": "earnings",
  "event_type": "data.available",
  "timestamp": "2025-01-15T06:30:00Z",
  "correlation_id": "abc123",
  "payload": {
    "collection_date": "2025-01-15",
    "source": "nasdaq",
    "symbols": ["AAPL", "GOOGL"],
    "event_count": 245
  }
}
```

**Storage Locations:**
```
data/cache/events/earnings.jsonl         # Append-only event log
data/cache/ready/earnings.flag            # Ready signal
data/cache/state/backfill/earnings.json   # Consumer checkpoint
```

**Example Consumer:**
```python
from common.utils.events import FileEventBus, Consumer

bus = FileEventBus(cache_root)
consumer = Consumer(bus, topic='earnings', consumer_id='backfill_worker')

for event in consumer.read():
    # Process event
    collection_date = event['payload']['collection_date']
    events = earnings_repo.query_by_collection_date(collection_date)

    # Generate plans
    for evt in events:
        plan = generate_plan(evt)
        save_plan(plan)

    # Checkpoint progress
    consumer.checkpoint()
```

**Benefits:**
- Idempotency: Reprocess events safely
- Resumption: Continue after crashes
- Tracing: Correlation IDs track data lineage
- Decoupling: Producers/consumers evolve independently

---

### Use Case 6: Multi-Service Architecture for Trading Platform

**Goal:** Expose trading data and operations through microservices for web UI and external systems.

**Service Topology:**
```
Frontend (React/Next.js - Port 9000)
    ↓
API Gateway / Load Balancer
    ↓
┌─────────────────────────────────────────────┐
│ Calendar API (9001)   - Earnings calendar   │
│ Equity API (9002)     - Historical bars     │
│ Option History (9003) - Option bars         │
│ Option Chain (9004)   - Chain snapshots     │
│ Orchestrator (9005)   - Workflow execution  │
│ Trading API (9006)    - Orders/positions    │
│ IB API (9007)         - IB Gateway proxy    │
└─────────────────────────────────────────────┘
    ↓
Repositories (Parquet Storage)
```

**Key Components:**
- `services/*/app.py` - FastAPI applications
- `services/*/routers/` - API endpoints
- `services/*/service.py` - Business logic
- `services/frontend/` - Web UI

**Cross-Cutting Concerns:**
- CORS enabled for frontend
- Health checks on all services
- Observability with Sentry
- Request/response logging
- Caching headers for optimization

**Deployment:**
```bash
# Development
make services-up  # Docker compose with all dependencies

# Production
uvicorn services.calendar_api.app:app --host 0.0.0.0 --port 9001 --workers 4
uvicorn services.equity_api.app:app --host 0.0.0.0 --port 9002 --workers 4
# ... etc
```

**Service Communication:**
```python
# Calendar API → Orchestrator API → IB API → IB Gateway
# Frontend ← Calendar API ← Repository
```

---

### Use Case 7: Backtesting with Historical Data

**Goal:** Validate trading strategies using historical market data.

**Workflow:**
```
1. Define backtest parameters (strategy, symbols, date range)
2. Query historical equity bars from repository
3. Query historical option chains and bars
4. Simulate strategy execution with historical data
5. Calculate performance metrics (P&L, Sharpe, drawdown)
6. Generate backtest report
7. Visualize results
```

**Key Components:**
- `common/repositories/*` - Historical data access
- `common/trading/strategy.py` - Strategy framework
- `common/trading/backtest.py` - Backtesting engine
- PyArrow for fast columnar queries

**Data Requirements:**
- Equity bars: OHLCV + volume
- Option chains: Strikes, IVs, Greeks
- Option bars: Detailed intraday option prices
- Corporate actions: Splits, dividends

**Example:**
```python
# Load historical data
equity_repo = EquityBarRepository(data_root)
bars = equity_repo.query(
    symbol='AAPL',
    start_date='2024-01-01',
    end_date='2024-12-31',
    bar_size='1 day'
)

# Load earnings events
earnings_repo = EarningsCalendarRepository(data_root)
events = earnings_repo.query_by_symbol('AAPL', days_back=365)

# Simulate strategy
results = backtest_earnings_strategy(
    bars=bars,
    events=events,
    capital=100000,
    position_size=0.1
)

# Analyze results
print(f"Total Return: {results.total_return:.2%}")
print(f"Sharpe Ratio: {results.sharpe_ratio:.2f}")
print(f"Max Drawdown: {results.max_drawdown:.2%}")
```

**Performance Optimizations:**
- PyArrow filter pushdown for fast queries
- Columnar storage reduces I/O
- Partitioning by symbol/date for locality
- Memory-mapped Parquet for large datasets

---

### Use Case 8: Trading Execution and Position Management

**Goal:** Execute trades and manage positions through Interactive Brokers.

**Workflow:**
```
1. Generate trading signal from strategy
2. Create order request (symbol, quantity, order type)
3. Submit order to Trading API
4. Trading API routes to IB Gateway
5. Monitor order status (pending → filled → acknowledged)
6. Update position repository
7. Track P&L and risk metrics
8. Generate execution reports
```

**Key Components:**
- `services/trading_api/` - Order management
- `common/repositories/trading/orders.py` - Order persistence
- `common/repositories/trading/positions.py` - Position tracking
- `services/ib_api/` - IB Gateway integration

**Order Types Supported:**
- Market orders
- Limit orders
- Stop orders
- Stop-limit orders
- Bracket orders (entry + profit target + stop loss)

**Order Schema:**
```python
@dataclass
class Order:
    order_id: str
    account: str
    symbol: str
    action: str  # BUY/SELL
    quantity: int
    order_type: str  # MARKET/LIMIT/STOP
    limit_price: Optional[float]
    stop_price: Optional[float]
    status: str  # PENDING/FILLED/CANCELLED/REJECTED
    filled_quantity: int
    avg_fill_price: float
    commission: float
    timestamp: datetime
```

**API Endpoints:**
```
POST /trading/orders          - Submit new order
GET  /trading/orders/{id}     - Get order status
GET  /trading/orders          - List all orders
DELETE /trading/orders/{id}   - Cancel order
GET  /trading/positions       - Get current positions
GET  /trading/positions/{symbol} - Get symbol position
```

**Example:**
```python
# Submit order
order = {
    "symbol": "AAPL",
    "action": "BUY",
    "quantity": 100,
    "order_type": "LIMIT",
    "limit_price": 185.50
}

response = trading_api.submit_order(order)
order_id = response['order_id']

# Monitor execution
status = trading_api.get_order_status(order_id)
while status['status'] != 'FILLED':
    await asyncio.sleep(1)
    status = trading_api.get_order_status(order_id)

# Update position
position = trading_api.get_position('AAPL')
print(f"Position: {position.quantity} shares @ ${position.avg_price}")
```

---

### Use Case 9: Data Quality and Lineage Tracking

**Goal:** Ensure data quality and maintain audit trails for regulatory compliance.

**Workflow:**
```
1. Capture metadata on every write (source, timestamp, processor)
2. Validate data against schemas
3. Score data quality (completeness, accuracy)
4. Track transformations and derivations
5. Store lineage metadata alongside data
6. Query lineage for audit trails
7. Generate data quality reports
```

**Key Components:**
- `common/lineage/` - Lineage tracking
- `common/schemas/` - Pydantic validation
- `common/repositories/base.py` - Quality checks

**Lineage Metadata:**
```python
{
    "collection_id": "uuid-12345",
    "source": "nasdaq",
    "collection_date": "2025-01-15",
    "collection_time": "06:30:00",
    "processor": "UnifiedEarningsCalendarFetcher",
    "processor_version": "2.0.0",
    "record_count": 245,
    "quality_score": 0.95,
    "validation_errors": [],
    "correlation_id": "abc123"
}
```

**Quality Checks:**
- Schema validation (Pydantic)
- Null value detection
- Duplicate detection
- Date range validation
- Reference data integrity

**Audit Query:**
```python
# Find all data for a symbol
lineage = earnings_repo.query_lineage(symbol='AAPL')

for record in lineage:
    print(f"{record.collection_date}: {record.source} (score: {record.quality_score})")

# Trace data flow
trace = get_lineage_trace(correlation_id='abc123')
print(f"Producer: {trace.producer}")
print(f"Consumers: {trace.consumers}")
print(f"Transformations: {trace.transformations}")
```

---

### Use Case 10: Scheduled Data Collection Jobs

**Goal:** Automate daily data collection on a reliable schedule.

**Workflow:**
```
1. Celery beat schedules daily task at 6:00 AM ET
2. Task: Fetch earnings calendar
3. Task: Snapshot option chains for imminent earnings
4. Task: Backfill gaps in equity data
5. Task: Process backlog of pending plans
6. Monitor task execution with Flower
7. Alert on failures via Sentry
```

**Key Components:**
- `ops/tasks/` - Celery tasks
- Celery Beat - Scheduler
- Flower - Monitoring UI
- `ops/jobs/backlog_worker.py` - Process pending plans

**Celery Tasks:**

| Task | Schedule | Purpose |
|------|----------|---------|
| `fetch_earnings_daily` | 6:00 AM ET | Fetch upcoming earnings |
| `snapshot_chains_daily` | 4:30 PM ET | Capture daily option chains |
| `process_backlog` | Every 30 mins | Execute pending plans |
| `dedup_earnings` | 2:00 AM ET | Deduplicate partitions |
| `cleanup_old_data` | Sunday 3:00 AM | Remove expired data |

**Configuration:**
```python
# celeryconfig.py
beat_schedule = {
    'fetch-earnings-daily': {
        'task': 'ops.tasks.earnings.fetch_daily',
        'schedule': crontab(hour=6, minute=0),
        'args': (14,)  # days_ahead
    },
    'snapshot-chains-daily': {
        'task': 'ops.tasks.chains.snapshot_daily',
        'schedule': crontab(hour=16, minute=30),
    }
}
```

**Monitoring:**
```bash
# Start workers
celery -A ops.tasks worker --loglevel=info

# Start beat scheduler
celery -A ops.tasks beat --loglevel=info

# Monitor with Flower
celery -A ops.tasks flower --port=5555
```

**Error Handling:**
- Retry with exponential backoff
- Circuit breaker for external APIs
- Dead letter queue for failed tasks
- Sentry alerts for critical failures

---

## Integration Points

### 1. Interactive Brokers Integration

**Purpose:** Fetch market data and execute trades

**Components:**
- `services/ib_api/` - IB Gateway proxy
- `ibapi` library - Official IB Python client
- Connection pooling for reliability
- Rate limiting to respect IB limits

**Capabilities:**
- Historical bars (equity, options)
- Real-time quotes
- Option chain requests
- Contract details
- Order execution
- Position tracking

### 2. External Data Sources

**Earnings Data:**
- NASDAQ API (primary)
- Yahoo Finance (fallback)
- FMP (Financial Modeling Prep)
- Finnhub

**Market Data:**
- Interactive Brokers (primary)
- Potential: Polygon.io, Alpha Vantage (future)

### 3. Frontend Integration

**Technology:** React/Next.js on port 9000

**Features:**
- Earnings calendar view
- Option chain visualization
- Position monitoring
- Trade execution UI
- Performance dashboards

**API Consumption:**
```javascript
// Fetch earnings
const response = await fetch('http://localhost:9001/calendar/upcoming?days=7');
const earnings = await response.json();

// Display in UI
earnings.data.forEach(event => {
  renderEarningsCard(event);
});
```

---

## Performance Characteristics

**Repository Query Performance:**
- Simple filters: <100ms for 1M rows
- Complex filters: <500ms for 10M rows
- Aggregations: <1s for 100M rows
- Partitioning reduces scan by 10-100x

**API Response Times:**
- Calendar endpoints: 50-200ms (cached)
- Equity bars: 100-500ms (PyArrow query)
- Option chains: 200-800ms (multi-table join)
- Orchestration: 1-5s (workflow creation)

**Scalability:**
- Handles 1000+ symbols concurrently
- 10M+ bars per symbol
- 100K+ option contracts
- 1M+ earnings events historical

**Storage Requirements:**
- Equity bars: ~1KB per bar
- Option bars: ~500 bytes per bar
- Option chain snapshot: ~10KB per snapshot
- Earnings event: ~200 bytes per event

---

## Operational Considerations

**Monitoring:**
- Health checks on all services
- Sentry error tracking
- Custom metrics (latency, throughput)
- Correlation ID tracing

**Reliability:**
- Repository-level checksums
- Event bus durability (JSONL append-only)
- Consumer checkpoints for resumption
- Circuit breakers on external APIs
- Retry policies with backoff

**Data Retention:**
- Earnings: 365 days (configurable)
- Equity bars: Unlimited
- Option bars: 90 days post-expiry
- Logs/events: 30 days

**Backup:**
- Parquet files are immutable
- S3/blob storage integration ready
- Incremental backup by partition

---

## Future Use Cases (Potential)

1. **Machine Learning Pipeline**: Train models on earnings/option data
2. **Multi-Asset Support**: Extend to forex, futures, crypto
3. **Real-Time Streaming**: WebSocket feeds for live data
4. **Portfolio Optimization**: Multi-symbol allocation strategies
5. **Risk Management**: VaR, stress testing, scenario analysis
6. **Compliance Reporting**: Regulatory filings, audit trails
7. **Alert System**: Price/volatility alerts, earnings notifications
8. **Social Integration**: Reddit/Twitter sentiment around earnings
9. **Collaboration**: Multi-user support, role-based access
10. **Cloud Deployment**: Kubernetes, autoscaling, global CDN

---

## Conclusion

The `earnings_ibapi` repository is a comprehensive trading data platform that enables:

✅ **Automated earnings-based trading workflows**
✅ **Multi-source data aggregation with quality scoring**
✅ **Historical data backfilling for backtesting**
✅ **Real-time option chain monitoring**
✅ **Event-driven pipeline architecture**
✅ **Microservices for frontend/external integration**
✅ **Trade execution through Interactive Brokers**
✅ **Data lineage and audit compliance**
✅ **Scheduled automation with monitoring**

The architecture prioritizes **reliability**, **performance**, and **observability**—making it production-ready for algorithmic trading operations.
