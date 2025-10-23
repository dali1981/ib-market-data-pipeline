"""Nasdaq earnings calendar scraper using curl_cffi for better anti-bot bypass."""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from curl_cffi import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class CurlCffiEarningsScraper:
    """
    Scraper for Nasdaq earnings calendar using curl_cffi.

    Uses curl_cffi to impersonate real browsers and bypass anti-bot protection.
    """

    WEB_URL = "https://www.nasdaq.com/market-activity/earnings"

    def __init__(
        self,
        days_ahead: int = 30,
        timeout: int = 30,
        impersonate: str = "chrome120",
    ):
        """
        Initialize scraper.

        Args:
            days_ahead: Number of days ahead to fetch (default: 30)
            timeout: Request timeout in seconds
            impersonate: Browser to impersonate (chrome120, safari15_5, etc.)
        """
        self.days_ahead = days_ahead
        self.timeout = timeout
        self.impersonate = impersonate

    def fetch(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch earnings calendar data.

        Args:
            date: Specific date to fetch (YYYY-MM-DD), or None for current view

        Returns:
            List of earnings records
        """
        logger.info(f"Fetching earnings data using curl_cffi (impersonate={self.impersonate})")

        # Build URL with date parameter if provided
        url = self.WEB_URL
        if date:
            url = f"{url}?date={date}"

        # Make request with browser impersonation
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=self.timeout,
                impersonate=self.impersonate,
            )
            response.raise_for_status()

            logger.info(f"Successfully fetched page (status={response.status_code})")

            # Parse HTML and extract data
            records = self._parse_html(response.text, date)
            logger.info(f"Extracted {len(records)} earnings records")

            return records

        except Exception as e:
            logger.error(f"Failed to fetch earnings data: {e}")
            raise

    def _parse_html(self, html: str, fetch_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Parse HTML to extract earnings calendar data.

        Args:
            html: Raw HTML content
            fetch_date: Date that was fetched (for metadata)

        Returns:
            List of earnings records
        """
        soup = BeautifulSoup(html, "lxml")
        records = []

        # Find the earnings table
        # Nasdaq typically uses tables with specific classes
        # We'll look for common patterns
        tables = soup.find_all("table")

        if not tables:
            logger.warning("No tables found in HTML")
            return records

        # Usually the first or second table contains earnings data
        for table in tables[:3]:  # Check first 3 tables
            rows = table.find_all("tr")

            if len(rows) < 2:  # Skip tables with no data rows
                continue

            # Try to identify if this is the earnings table
            header_row = rows[0]
            headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]

            # Check if this looks like an earnings table
            if not any(keyword in " ".join(headers) for keyword in ["symbol", "company", "earnings", "eps"]):
                continue

            logger.info(f"Found earnings table with headers: {headers}")

            # Extract data rows
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) < 3:  # Skip rows without enough data
                    continue

                # Extract cell data
                cell_texts = [cell.get_text(strip=True) for cell in cells]

                # Map to record structure (adjust based on actual table structure)
                # Common structure: Symbol, Company, Date, Time, EPS Forecast, etc.
                record = self._extract_record_from_cells(cell_texts, headers, fetch_date)
                if record:
                    records.append(record)

        return records

    def _extract_record_from_cells(
        self,
        cells: List[str],
        headers: List[str],
        fetch_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Extract a record from table cells.

        Args:
            cells: List of cell texts
            headers: List of header names
            fetch_date: Date that was fetched

        Returns:
            Earnings record or None if invalid
        """
        if len(cells) < 3:
            return None

        # Try to build a mapping based on headers
        cell_map = {}
        for i, header in enumerate(headers):
            if i < len(cells):
                cell_map[header] = cells[i]

        # Extract symbol (usually first column or has 'symbol' in header)
        symbol = (
            cell_map.get("symbol") or
            cell_map.get("ticker") or
            cells[0] if len(cells) > 0 else ""
        )

        if not symbol or len(symbol) < 1:
            return None

        # Extract other fields with fallbacks
        company_name = (
            cell_map.get("company") or
            cell_map.get("name") or
            cell_map.get("company name") or
            cells[1] if len(cells) > 1 else ""
        )

        earnings_date = (
            cell_map.get("date") or
            cell_map.get("earnings date") or
            fetch_date or
            cells[2] if len(cells) > 2 else ""
        )

        earnings_time = (
            cell_map.get("time") or
            cell_map.get("earnings time") or
            cells[3] if len(cells) > 3 else ""
        )

        eps_forecast = (
            cell_map.get("eps forecast") or
            cell_map.get("forecast") or
            cell_map.get("eps est") or
            cells[4] if len(cells) > 4 else None
        )

        market_cap = (
            cell_map.get("market cap") or
            cell_map.get("marketcap") or
            cells[5] if len(cells) > 5 else None
        )

        # Build record
        now = datetime.now(datetime.UTC)
        record = {
            "symbol": symbol,
            "company_name": company_name,
            "earnings_date": self._normalize_date(earnings_date),
            "earnings_time": earnings_time,
            "eps_forecast": self._parse_numeric(eps_forecast),
            "market_cap": market_cap,
            "snapshot_date": now.date().isoformat(),
            "scraped_at": now.isoformat(),
        }

        return record

    def _normalize_date(self, date_str: str) -> Optional[str]:
        """
        Normalize date string to YYYY-MM-DD format.

        Args:
            date_str: Date string in various formats

        Returns:
            ISO format date or None
        """
        if not date_str or date_str.strip() == "":
            return None

        # Try to parse common date formats
        formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%m/%d/%y",
            "%b %d, %Y",
            "%B %d, %Y",
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.date().isoformat()
            except ValueError:
                continue

        logger.warning(f"Could not parse date: {date_str}")
        return None

    @staticmethod
    def _parse_numeric(value: Any) -> Optional[float]:
        """
        Parse numeric value, handling various formats.

        Args:
            value: Value to parse

        Returns:
            Parsed number or None
        """
        if value is None or value == "":
            return None

        # Handle string values
        if isinstance(value, str):
            # Remove common formatting
            cleaned = value.replace(",", "").replace("$", "").replace("%", "").strip()
            if cleaned in ["--", "N/A", "", "n/a"]:
                return None
            try:
                return float(cleaned)
            except ValueError:
                return None

        # Handle numeric values
        try:
            return float(value)
        except (ValueError, TypeError):
            return None


def fetch_earnings_calendar(
    days_ahead: int = 30,
    date: Optional[str] = None,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Convenience function to fetch earnings calendar data using curl_cffi.

    Args:
        days_ahead: Number of days ahead to fetch
        date: Specific date to fetch (YYYY-MM-DD)
        **kwargs: Additional arguments for CurlCffiEarningsScraper

    Returns:
        List of earnings records
    """
    scraper = CurlCffiEarningsScraper(days_ahead=days_ahead, **kwargs)
    return scraper.fetch(date=date)
