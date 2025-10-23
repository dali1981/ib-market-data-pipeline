"""Public API for querying earnings calendar data from Parquet files."""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class EarningsCalendarReader:
    """
    Reader for querying earnings calendar data stored in Parquet format.

    Provides efficient querying capabilities using DuckDB and PyArrow,
    with predicate pushdown for optimal performance.
    """

    def __init__(
        self,
        data_path: str = "./data/nasdaq_earnings/earnings_calendar",
        use_duckdb: bool = True,
    ):
        """
        Initialize reader.

        Args:
            data_path: Path to Parquet data directory
            use_duckdb: Use DuckDB for queries (recommended for performance)
        """
        self.data_path = Path(data_path)
        self.use_duckdb = use_duckdb

        if not self.data_path.exists():
            logger.warning(f"Data path does not exist: {self.data_path}")

    def get_upcoming_earnings(
        self,
        days_ahead: int = 7,
        symbols: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get upcoming earnings announcements.

        Args:
            days_ahead: Number of days ahead to query
            symbols: Optional list of symbols to filter by

        Returns:
            List of earnings records
        """
        today = datetime.now().date()
        end_date = today + timedelta(days=days_ahead)

        query = f"""
            SELECT *
            FROM read_parquet('{self.data_path}/**/*.parquet')
            WHERE earnings_date >= '{today.isoformat()}'
              AND earnings_date <= '{end_date.isoformat()}'
        """

        if symbols:
            symbols_str = "', '".join(symbols)
            query += f" AND symbol IN ('{symbols_str}')"

        query += " ORDER BY earnings_date, symbol"

        return self._execute_query(query)

    def get_earnings_by_ticker(
        self,
        ticker: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all earnings records for a specific ticker.

        Args:
            ticker: Stock ticker symbol
            limit: Optional limit on number of records

        Returns:
            List of earnings records sorted by date (descending)
        """
        query = f"""
            SELECT *
            FROM read_parquet('{self.data_path}/**/*.parquet')
            WHERE symbol = '{ticker.upper()}'
            ORDER BY earnings_date DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        return self._execute_query(query)

    def get_earnings_by_date(
        self,
        date: str,
        earnings_time: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get all earnings announcements on a specific date.

        Args:
            date: Date in YYYY-MM-DD format
            earnings_time: Optional filter by time (BMO, AMC, TAS)

        Returns:
            List of earnings records
        """
        query = f"""
            SELECT *
            FROM read_parquet('{self.data_path}/**/*.parquet')
            WHERE earnings_date = '{date}'
        """

        if earnings_time:
            query += f" AND earnings_time = '{earnings_time}'"

        query += " ORDER BY symbol"

        return self._execute_query(query)

    def get_earnings_in_range(
        self,
        start_date: str,
        end_date: str,
        symbols: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get earnings announcements in a date range.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            symbols: Optional list of symbols to filter by

        Returns:
            List of earnings records
        """
        query = f"""
            SELECT *
            FROM read_parquet('{self.data_path}/**/*.parquet')
            WHERE earnings_date >= '{start_date}'
              AND earnings_date <= '{end_date}'
        """

        if symbols:
            symbols_str = "', '".join(symbols)
            query += f" AND symbol IN ('{symbols_str}')"

        query += " ORDER BY earnings_date, symbol"

        return self._execute_query(query)

    def get_earnings_with_surprises(
        self,
        min_surprise_pct: Optional[float] = None,
        limit: Optional[int] = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get earnings with reported actuals and surprise percentages.

        Args:
            min_surprise_pct: Minimum absolute surprise percentage
            limit: Maximum number of records to return

        Returns:
            List of earnings records with surprises
        """
        query = f"""
            SELECT *
            FROM read_parquet('{self.data_path}/**/*.parquet')
            WHERE eps_actual IS NOT NULL
              AND eps_surprise_pct IS NOT NULL
        """

        if min_surprise_pct is not None:
            query += f" AND ABS(eps_surprise_pct) >= {min_surprise_pct}"

        query += " ORDER BY earnings_date DESC"

        if limit:
            query += f" LIMIT {limit}"

        return self._execute_query(query)

    def get_latest_snapshot(self) -> Optional[str]:
        """
        Get the date of the most recent data snapshot.

        Returns:
            Most recent snapshot date or None
        """
        query = f"""
            SELECT MAX(snapshot_date) as latest_snapshot
            FROM read_parquet('{self.data_path}/**/*.parquet')
        """

        results = self._execute_query(query)
        if results and results[0].get("latest_snapshot"):
            return results[0]["latest_snapshot"]
        return None

    def get_earnings_stats(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get summary statistics for earnings data.

        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Dictionary with statistics
        """
        where_clause = ""
        if start_date and end_date:
            where_clause = f"""
                WHERE earnings_date >= '{start_date}'
                  AND earnings_date <= '{end_date}'
            """

        query = f"""
            SELECT
                COUNT(*) as total_records,
                COUNT(DISTINCT symbol) as unique_symbols,
                COUNT(DISTINCT earnings_date) as unique_dates,
                MIN(earnings_date) as earliest_date,
                MAX(earnings_date) as latest_date,
                COUNT(CASE WHEN eps_actual IS NOT NULL THEN 1 END) as reported_count,
                AVG(CASE WHEN eps_surprise_pct IS NOT NULL THEN eps_surprise_pct END) as avg_surprise_pct
            FROM read_parquet('{self.data_path}/**/*.parquet')
            {where_clause}
        """

        results = self._execute_query(query)
        return results[0] if results else {}

    def _execute_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Execute SQL query against Parquet files.

        Args:
            query: SQL query string

        Returns:
            List of result records as dictionaries
        """
        if not self.data_path.exists():
            logger.warning(f"Data path does not exist: {self.data_path}")
            return []

        try:
            if self.use_duckdb:
                return self._query_with_duckdb(query)
            else:
                return self._query_with_pyarrow(query)
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            logger.debug(f"Query: {query}")
            raise

    def _query_with_duckdb(self, query: str) -> List[Dict[str, Any]]:
        """Execute query using DuckDB."""
        conn = duckdb.connect(":memory:")
        result = conn.execute(query).fetchall()
        columns = [desc[0] for desc in conn.description]
        conn.close()

        return [dict(zip(columns, row)) for row in result]

    def _query_with_pyarrow(self, query: str) -> List[Dict[str, Any]]:
        """
        Execute query using PyArrow.

        Note: This is a simplified implementation. For complex queries,
        DuckDB is recommended.
        """
        # Read all parquet files in directory
        parquet_files = list(self.data_path.rglob("*.parquet"))

        if not parquet_files:
            return []

        # Read and combine tables
        tables = []
        for file in parquet_files:
            table = pq.read_table(file)
            tables.append(table)

        combined = pa.concat_tables(tables)

        # Convert to pandas for querying (not optimal for large datasets)
        df = combined.to_pandas()

        # This is a very simplified approach - actual implementation would
        # need proper SQL parsing and execution
        logger.warning("PyArrow querying is limited. Consider using DuckDB.")

        return df.to_dict("records")


# Convenience functions for quick access

def get_upcoming_earnings(
    days_ahead: int = 7,
    symbols: Optional[List[str]] = None,
    data_path: str = "./data/nasdaq_earnings/earnings_calendar",
) -> List[Dict[str, Any]]:
    """
    Get upcoming earnings announcements.

    Args:
        days_ahead: Number of days ahead
        symbols: Optional symbol filter
        data_path: Path to Parquet data

    Returns:
        List of earnings records
    """
    reader = EarningsCalendarReader(data_path=data_path)
    return reader.get_upcoming_earnings(days_ahead=days_ahead, symbols=symbols)


def get_earnings_by_ticker(
    ticker: str,
    limit: Optional[int] = None,
    data_path: str = "./data/nasdaq_earnings/earnings_calendar",
) -> List[Dict[str, Any]]:
    """
    Get earnings for a specific ticker.

    Args:
        ticker: Stock ticker
        limit: Optional limit
        data_path: Path to Parquet data

    Returns:
        List of earnings records
    """
    reader = EarningsCalendarReader(data_path=data_path)
    return reader.get_earnings_by_ticker(ticker=ticker, limit=limit)


def get_earnings_by_date(
    date: str,
    earnings_time: Optional[str] = None,
    data_path: str = "./data/nasdaq_earnings/earnings_calendar",
) -> List[Dict[str, Any]]:
    """
    Get earnings on a specific date.

    Args:
        date: Date (YYYY-MM-DD)
        earnings_time: Optional time filter
        data_path: Path to Parquet data

    Returns:
        List of earnings records
    """
    reader = EarningsCalendarReader(data_path=data_path)
    return reader.get_earnings_by_date(date=date, earnings_time=earnings_time)
