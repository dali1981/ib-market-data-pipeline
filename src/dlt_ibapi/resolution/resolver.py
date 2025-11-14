"""
Contract resolver service for Interactive Brokers symbol lookup.

Provides symbol search and contract resolution with:
- MatchingSymbols API for fuzzy symbol search
- ContractDetails API for complete contract information
- Rate limiting (1/sec for MatchingSymbols, 50/sec for ContractDetails)
- Automatic caching to ContractCache
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import time
import pandas as pd

from ib_connector import IBRuntime, ContractDetailsService, MatchingSymbolService
from ibapi.contract import Contract, ContractDetails

from .contract_cache import ContractCache


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, calls_per_second: float):
        """
        Initialize rate limiter.

        Args:
            calls_per_second: Maximum calls per second
        """
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0.0

    def wait_if_needed(self) -> None:
        """Wait if necessary to respect rate limit."""
        now = time.time()
        elapsed = now - self.last_call
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call = time.time()


class ContractResolver:
    """
    Service for resolving symbols to IB contracts with caching and rate limiting.

    Uses two-step resolution:
    1. MatchingSymbols: Fuzzy search to find potential matches (rate limit: 1/sec)
    2. ContractDetails: Get full contract details (rate limit: 50/sec)

    Results are cached in ContractCache to avoid repeated API calls.
    """

    def __init__(
        self,
        runtime: IBRuntime,
        cache: ContractCache,
        matching_symbols_rate: float = 1.0,  # 1 call/sec
        contract_details_rate: float = 50.0,  # 50 calls/sec
    ):
        """
        Initialize contract resolver.

        Args:
            runtime: IBRuntime instance (must be started)
            cache: ContractCache for storing resolved contracts
            matching_symbols_rate: Max calls/sec for MatchingSymbols
            contract_details_rate: Max calls/sec for ContractDetails
        """
        self.runtime = runtime
        self.cache = cache
        self.matching_svc = MatchingSymbolService(runtime)
        self.details_svc = ContractDetailsService(runtime)

        # Rate limiters
        self.matching_limiter = RateLimiter(matching_symbols_rate)
        self.details_limiter = RateLimiter(contract_details_rate)

    def search_symbol(self, pattern: str, timeout: float = 10.0) -> List[Any]:
        """
        Search for symbols matching pattern using MatchingSymbols API.

        Rate limited to 1 call/sec.

        Args:
            pattern: Symbol search pattern (e.g., "AAPL", "AAP", "Apple")
            timeout: Request timeout in seconds

        Returns:
            List of matching symbol descriptions (up to 16 results)
        """
        self.matching_limiter.wait_if_needed()
        return self.matching_svc.fetch(pattern, timeout=timeout)

    def get_contract_details(
        self,
        contract: Contract,
        timeout: float = 10.0
    ) -> List[ContractDetails]:
        """
        Get detailed contract information using ContractDetails API.

        Rate limited to 50 calls/sec.

        Args:
            contract: IB Contract object
            timeout: Request timeout in seconds

        Returns:
            List of ContractDetails objects
        """
        self.details_limiter.wait_if_needed()
        return self.details_svc.fetch(contract, timeout=timeout)

    def resolve_symbol(
        self,
        symbol: str,
        exchange: str = "SMART",
        currency: str = "USD",
        sec_type: str = "STK",
        use_cache: bool = True,
        save_to_cache: bool = True,
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve a symbol to full contract details.

        Workflow:
        1. Check cache if use_cache=True
        2. Get full details with ContractDetails
        3. Save to cache if save_to_cache=True

        Args:
            symbol: Stock symbol (e.g., "AAPL")
            exchange: Exchange (default: "SMART")
            currency: Currency (default: "USD")
            sec_type: Security type (default: "STK")
            use_cache: Check cache before API call
            save_to_cache: Save results to cache
            timeout: Request timeout

        Returns:
            Contract details dict or None if not found

        Raises:
            Exception: If API call fails or contract not found
        """
        symbol = symbol.upper()

        # Check cache first
        if use_cache:
            cached = self.cache.get_contracts_by_symbol(symbol, sec_type=sec_type)
            if not cached.empty:
                # Return first match with matching exchange/currency if possible
                matches = cached[
                    (cached["currency"] == currency)
                ]
                if not matches.empty:
                    return matches.iloc[0].to_dict()
                # Otherwise return first cached result
                return cached.iloc[0].to_dict()

        # Not in cache, need to resolve via API
        # Create contract and get details
        from ib_connector import make_stock

        contract = make_stock(symbol, exch=exchange, curr=currency) if sec_type == "STK" else None
        if not contract:
            raise ValueError(f"Cannot create contract for {symbol} (unsupported sec_type: {sec_type})")

        # Get contract details (this will raise exception if error)
        try:
            details_list = self.get_contract_details(contract, timeout=timeout)
        except Exception as e:
            raise Exception(f"Failed to get contract details for {symbol}: {str(e)}")

        if not details_list:
            raise ValueError(f"No security definition found for {symbol} on {exchange}")

        # Convert to DataFrame for caching
        df = self._contract_details_to_df(details_list, symbol)

        if df.empty:
            raise ValueError(f"Failed to parse contract details for {symbol}")

        # Save to cache
        if save_to_cache:
            self.cache.save(df)

        # Return first result
        return df.iloc[0].to_dict()

    def resolve_symbols_batch(
        self,
        symbols: List[str],
        exchange: str = "SMART",
        currency: str = "USD",
        sec_type: str = "STK",
        use_cache: bool = True,
        save_to_cache: bool = True,
        timeout: float = 10.0,
    ) -> pd.DataFrame:
        """
        Resolve multiple symbols to contract details.

        Uses cache to minimize API calls. Respects rate limits.

        Args:
            symbols: List of symbols to resolve
            exchange: Exchange (default: "SMART")
            currency: Currency (default: "USD")
            sec_type: Security type (default: "STK")
            use_cache: Check cache before API calls
            save_to_cache: Save results to cache
            timeout: Request timeout per symbol

        Returns:
            DataFrame with resolved contract details
        """
        results = []

        for symbol in symbols:
            result = self.resolve_symbol(
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                sec_type=sec_type,
                use_cache=use_cache,
                save_to_cache=save_to_cache,
                timeout=timeout,
            )
            if result:
                results.append(result)

        return pd.DataFrame(results) if results else pd.DataFrame()

    def resolve_option_contract(
        self,
        symbol: str,
        expiry: str,
        strike: float,
        right: str,
        exchange: str = "SMART",
        currency: str = "USD",
        multiplier: str = "100",
        use_cache: bool = True,
        save_to_cache: bool = True,
        timeout: float = 10.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve an option contract to full contract details.

        Workflow:
        1. Check cache if use_cache=True
        2. Create partial contract with make_option()
        3. Get full details with ContractDetails API
        4. Save to cache if save_to_cache=True

        Args:
            symbol: Underlying symbol (e.g., "AAPL")
            expiry: Expiration date in YYYYMMDD format
            strike: Strike price
            right: "C" for call or "P" for put
            exchange: Exchange (default: "SMART")
            currency: Currency (default: "USD")
            multiplier: Contract multiplier (default: "100")
            use_cache: Check cache before API call
            save_to_cache: Save results to cache
            timeout: Request timeout

        Returns:
            Contract details dict with conId, localSymbol, tradingClass, etc.
            Returns None if contract not found.

        Raises:
            Exception: If API call fails
        """
        symbol = symbol.upper()

        # Check cache first
        if use_cache:
            cached = self.cache.get_option_contract(
                symbol=symbol,
                expiry=expiry,
                strike=strike,
                right=right,
            )
            if cached:
                return cached

        # Not in cache, need to resolve via API
        from ib_connector import make_option

        contract = make_option(
            symbol=symbol,
            last_trade_date=expiry,
            strike=strike,
            right=right,
            exch=exchange,
            curr=currency,
            multiplier=multiplier,
        )

        # Get contract details (this will raise exception if error)
        try:
            details_list = self.get_contract_details(contract, timeout=timeout)
        except Exception as e:
            raise Exception(
                f"Failed to get contract details for {symbol} {expiry} {strike}{right}: {str(e)}"
            )

        if not details_list:
            raise ValueError(
                f"No security definition found for {symbol} {expiry} {strike}{right} on {exchange}"
            )

        # Convert to DataFrame for caching
        df = self._contract_details_to_df(details_list, symbol)

        if df.empty:
            raise ValueError(f"Failed to parse contract details for {symbol} {expiry} {strike}{right}")

        # Add option-specific fields
        df["strike"] = strike
        df["right"] = right
        df["last_trade_date"] = expiry

        # Save to cache
        if save_to_cache:
            self.cache.save(df)

        # Return first result
        return df.iloc[0].to_dict()

    def _contract_details_to_df(
        self,
        details_list: List[ContractDetails],
        symbol: str
    ) -> pd.DataFrame:
        """
        Convert ContractDetails objects to DataFrame matching cache schema.

        Args:
            details_list: List of ContractDetails from IB API
            symbol: Original symbol (for fallback)

        Returns:
            DataFrame with contract data
        """
        records = []

        for details in details_list:
            contract = details.contract

            record = {
                # Primary identifiers
                "symbol": contract.symbol or symbol,
                "sec_type": contract.secType or "STK",
                "conid": contract.conId,

                # Contract details
                "exchange": contract.exchange,
                "primary_exchange": contract.primaryExchange,
                "currency": contract.currency,
                "local_symbol": contract.localSymbol,
                "trading_class": contract.tradingClass,

                # Numeric fields
                "multiplier": int(contract.multiplier) if contract.multiplier else None,
                "min_tick": details.minTick if hasattr(details, "minTick") else None,
                "price_magnifier": details.priceMagnifier if hasattr(details, "priceMagnifier") else None,

                # Option/derivative fields
                "under_conid": details.underConid if hasattr(details, "underConid") else None,
                "under_symbol": details.underSymbol if hasattr(details, "underSymbol") else None,
                "under_sec_type": details.underSecType if hasattr(details, "underSecType") else None,

                # Metadata
                "long_name": details.longName if hasattr(details, "longName") else None,
                "industry": details.industry if hasattr(details, "industry") else None,
                "category": details.category if hasattr(details, "category") else None,
                "subcategory": details.subcategory if hasattr(details, "subcategory") else None,

                # Trading hours
                "timezone_id": details.timeZoneId if hasattr(details, "timeZoneId") else None,
                "trading_hours": details.tradingHours if hasattr(details, "tradingHours") else None,
                "liquid_hours": details.liquidHours if hasattr(details, "liquidHours") else None,

                # Additional fields
                "market_rule_ids": details.marketRuleIds if hasattr(details, "marketRuleIds") else None,
                "real_expiration_date": details.realExpirationDate if hasattr(details, "realExpirationDate") else None,
                "last_trade_time": details.lastTradeTime if hasattr(details, "lastTradeTime") else None,
                "stock_type": details.stockType if hasattr(details, "stockType") else None,

                # Timestamp
                "created_at": pd.Timestamp.utcnow(),
            }

            records.append(record)

        return pd.DataFrame(records) if records else pd.DataFrame()
