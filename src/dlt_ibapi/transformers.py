"""Data transformation utilities for normalizing IB API data for DLT."""

from typing import Any, Dict
from datetime import datetime


def normalize_bar_data(bar: Dict[str, Any], symbol: str, exchange: str, currency: str) -> Dict[str, Any]:
    """
    Normalize historical bar data from IB API format to DLT schema.

    Args:
        bar: Raw bar data from IB API
        symbol: Stock symbol
        exchange: Exchange
        currency: Currency

    Returns:
        Normalized bar data
    """
    return {
        "symbol": symbol,
        "exchange": exchange,
        "currency": currency,
        "timestamp": bar.get("date"),
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
