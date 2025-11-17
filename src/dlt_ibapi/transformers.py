"""Data transformation utilities for normalizing IB API data for DLT."""

from typing import Any, Dict, Literal
from datetime import datetime, date


def normalize_bar_data(
    bar: Dict[str, Any],
    symbol: str,
    exchange: str,
    currency: str,
    bar_size: str = "1 day"
) -> Dict[str, Any]:
    """
    Normalize historical bar data from IB API format to DLT schema.

    Adds partition columns for Parquet storage:
    - time: Full datetime/timestamp as ISO string (primary key)
    - date: Date only (partition column)

    Args:
        bar: Raw bar data from IB API
        symbol: Stock symbol
        exchange: Exchange
        currency: Currency
        bar_size: Bar size (e.g., "1 day", "1 min")

    Returns:
        Normalized bar data with partition columns
    """
    from datetime import datetime as dt

    # Get timestamp from bar (IB returns various formats)
    bar_datetime_raw = bar.get("date")

    # Parse and normalize to ISO format timestamp
    bar_datetime = None
    bar_date = None

    if bar_datetime_raw:
        if isinstance(bar_datetime_raw, str):
            # Handle different IB date/time formats:
            # - "YYYYMMDD" (daily bars) -> "YYYY-MM-DD 00:00:00"
            # - "YYYYMMDD HH:MM:SS" (intraday bars) -> "YYYY-MM-DD HH:MM:SS"
            # - "YYYY-MM-DD HH:MM:SS" (already ISO-ish)
            try:
                if len(bar_datetime_raw) == 8 and bar_datetime_raw.isdigit():
                    # Daily bar format: YYYYMMDD
                    parsed_dt = dt.strptime(bar_datetime_raw, "%Y%m%d")
                elif " " in bar_datetime_raw and len(bar_datetime_raw) <= 17:
                    # Intraday format: "YYYYMMDD HH:MM:SS"
                    parsed_dt = dt.strptime(bar_datetime_raw, "%Y%m%d %H:%M:%S")
                else:
                    # Try ISO format with T or space separator
                    parsed_dt = dt.fromisoformat(bar_datetime_raw.replace(" ", "T"))

                # Store as ISO string (DuckDB and Parquet will recognize this)
                bar_datetime = parsed_dt.isoformat()
                bar_date = parsed_dt.date().isoformat()
            except ValueError as e:
                # Fallback: store as-is if parsing fails
                bar_datetime = bar_datetime_raw
                bar_date = bar_datetime_raw[:10] if len(bar_datetime_raw) >= 10 else None
        elif hasattr(bar_datetime_raw, 'isoformat'):
            # Python datetime object
            bar_datetime = bar_datetime_raw.isoformat()
            bar_date = bar_datetime_raw.date().isoformat()
        else:
            # Fallback: convert to string
            bar_datetime = str(bar_datetime_raw)

    return {
        "symbol": symbol,
        "exchange": exchange,
        "currency": currency,
        "bar_size": bar_size,  # Part of primary key
        "time": bar_datetime,  # Full datetime as ISO string (primary key)
        "date": bar_date,      # Date only (partition column for Hive partitioning)
        "timestamp": bar_datetime,  # Backward compatibility
        "open": float(bar.get("open", 0)),
        "high": float(bar.get("high", 0)),
        "low": float(bar.get("low", 0)),
        "close": float(bar.get("close", 0)),
        "volume": int(bar.get("volume", 0)),
        "wap": float(bar.get("wap", 0)) if bar.get("wap") else None,
        "bar_count": int(bar.get("barCount", 0)) if bar.get("barCount") else None,
    }


def normalize_contract_details(detail: Any, symbol: str) -> Dict[str, Any]:
    """
    Normalize contract details from IB API format to DLT schema.

    Args:
        detail: ContractDetails object from IB API
        symbol: Stock symbol

    Returns:
        Normalized contract details
    """
    contract = detail.contract

    return {
        "symbol": symbol,
        "contract_id": contract.conId,
        "local_symbol": contract.localSymbol,
        "trading_class": contract.tradingClass,
        "sec_type": contract.secType,
        "exchange": contract.exchange,
        "primary_exchange": contract.primaryExchange,
        "currency": contract.currency,
        "long_name": detail.longName,
        "category": detail.category,
        "subcategory": detail.subcategory,
        "industry": getattr(detail, "industry", None),
        "min_tick": detail.minTick,
        "price_magnifier": detail.priceMagnifier,
        "order_types": detail.orderTypes,
        "valid_exchanges": detail.validExchanges,
        "market_name": detail.marketName,
        "fetched_at": datetime.utcnow().isoformat(),
    }


def normalize_option_params(param: Dict[str, Any], symbol: str, conid: int) -> Dict[str, Any]:
    """
    Normalize option chain parameters from IB API format to DLT schema.

    Args:
        param: Option parameter dict from IB API
        symbol: Underlying symbol
        conid: Underlying contract ID

    Returns:
        Normalized option parameters
    """
    return {
        "underlying_symbol": symbol,
        "underlying_conid": conid,
        "exchange": param.get("exchange"),
        "trading_class": param.get("tradingClass"),
        "multiplier": param.get("multiplier"),
        "expirations": param.get("expirations", []),
        "strikes": param.get("strikes", []),
        "expiration_count": len(param.get("expirations", [])),
        "strike_count": len(param.get("strikes", [])),
        "fetched_at": datetime.utcnow().isoformat(),
    }


def normalize_tick_data(tick: Dict[str, Any], symbol: str, contract_id: int) -> Dict[str, Any]:
    """
    Normalize tick/market data from IB API format to DLT schema.

    Args:
        tick: Tick data dict from IB API
        symbol: Stock symbol
        contract_id: Contract ID

    Returns:
        Normalized tick data
    """
    tick_type = tick.get("type")

    base = {
        "symbol": symbol,
        "contract_id": contract_id,
        "tick_type": tick_type,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if tick_type == "tickPrice":
        return {
            **base,
            "tick_name": tick.get("tick"),
            "price": float(tick.get("price", 0)),
            "can_auto_execute": tick.get("attrib", {}).get("canAutoExecute"),
            "past_limit": tick.get("attrib", {}).get("pastLimit"),
            "pre_open": tick.get("attrib", {}).get("preOpen"),
        }
    elif tick_type == "tickSize":
        return {
            **base,
            "tick_name": tick.get("tick"),
            "size": int(tick.get("size", 0)),
        }
    elif tick_type == "tickString":
        return {
            **base,
            "tick_name": tick.get("tick"),
            "value": tick.get("value"),
        }
    elif tick_type == "tickOption":
        return {
            **base,
            "tick_name": tick.get("tick"),
            "implied_vol": tick.get("impliedVol"),
            "delta": tick.get("delta"),
            "option_price": tick.get("optPrice"),
            "pv_dividend": tick.get("pvDividend"),
            "gamma": tick.get("gamma"),
            "vega": tick.get("vega"),
            "theta": tick.get("theta"),
            "under_price": tick.get("underPrice"),
        }
    else:
        return base


def normalize_historical_tick_data(
    tick: Any,
    underlying: str,
    expiry: date,
    strike: float,
    right: str,
    tick_type: Literal['BID_ASK', 'TRADES', 'MIDPOINT']
) -> Dict[str, Any]:
    """
    Normalize historical tick data from HistoricalTick object to DLT schema.

    This is different from normalize_tick_data which handles real-time streaming ticks.

    Args:
        tick: HistoricalTick object from IB API (HistoricalTickBidAsk, HistoricalTickLast, etc.)
        underlying: Underlying symbol
        expiry: Expiration date
        strike: Strike price
        right: 'C' or 'P'
        tick_type: Type of tick data

    Returns:
        Dictionary matching tick schema for DLT

    Note:
        tick.time is a Unix timestamp (int), not a datetime object.
        IB API uses attribute names like priceBid, priceAsk (not bid_price, ask_price).
    """
    # Convert Unix timestamp to datetime
    # Note: tick.time is UTC Unix timestamp (seconds since epoch)
    from datetime import datetime as dt, timezone
    tick_dt = dt.fromtimestamp(tick.time, tz=timezone.utc)

    base = {
        "tick_time": tick_dt.isoformat(),
        "underlying": underlying,
        "expiry": expiry.isoformat(),
        "strike": strike,
        "right": right.upper(),
        "date": tick_dt.date().isoformat(),
        "symbol": underlying,
    }

    if tick_type == 'BID_ASK':
        # IB API uses priceBid, priceAsk, sizeBid, sizeAsk (not bid_price, etc.)
        bid_price = tick.priceBid
        ask_price = tick.priceAsk
        bid_size = tick.sizeBid
        ask_size = tick.sizeAsk

        midpoint = (bid_price + ask_price) / 2 if bid_price and ask_price else None
        spread = ask_price - bid_price if bid_price and ask_price else None
        spread_pct = (spread / midpoint * 100) if spread and midpoint else None

        return {
            **base,
            "bid_price": bid_price,
            "ask_price": ask_price,
            "bid_size": bid_size,
            "ask_size": ask_size,
            "spread": spread,
            "spread_pct": spread_pct,
            "midpoint": midpoint,
        }
    elif tick_type == 'TRADES':
        return {
            **base,
            "price": tick.price,
            "size": tick.size,
            "exchange": getattr(tick, 'exchange', ""),
            "special_conditions": getattr(tick, 'specialConditions', ""),
        }
    elif tick_type == 'MIDPOINT':
        return {
            **base,
            "price": tick.price,
        }
    else:
        return base
