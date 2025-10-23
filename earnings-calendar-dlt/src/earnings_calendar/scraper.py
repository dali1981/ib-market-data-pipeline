"""Nasdaq earnings calendar scraper with API and Playwright fallback."""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import httpx
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)


class NasdaqEarningsScraper:
    """
    Scraper for Nasdaq earnings calendar data.

    Tries API endpoint first, falls back to Playwright if needed.
    """

    API_BASE_URL = "https://api.nasdaq.com/api/calendar/earnings"
    WEB_URL = "https://www.nasdaq.com/market-activity/earnings"

    def __init__(
        self,
        days_ahead: int = 30,
        use_playwright_fallback: bool = True,
        timeout: int = 30,
    ):
        """
        Initialize scraper.

        Args:
            days_ahead: Number of days ahead to fetch (default: 30)
            use_playwright_fallback: Fall back to Playwright if API fails
            timeout: Request timeout in seconds
        """
        self.days_ahead = days_ahead
        self.use_playwright_fallback = use_playwright_fallback
        self.timeout = timeout

    def fetch(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch earnings calendar data.

        Args:
            date: Specific date to fetch (YYYY-MM-DD), or None for date range

        Returns:
            List of earnings records
        """
        try:
            return self._fetch_via_api(date)
        except Exception as e:
            logger.warning(f"API fetch failed: {e}")
            if self.use_playwright_fallback:
                logger.info("Falling back to Playwright scraping")
                return self._fetch_via_playwright(date)
            raise

    def _fetch_via_api(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch data via Nasdaq API.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            List of earnings records
        """
        all_records = []

        # If no date specified, fetch range
        if date is None:
            dates_to_fetch = self._get_date_range()
        else:
            dates_to_fetch = [date]

        with httpx.Client(timeout=self.timeout) as client:
            for fetch_date in dates_to_fetch:
                logger.info(f"Fetching earnings for {fetch_date}")

                params = {"date": fetch_date}
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/json",
                }

                response = client.get(
                    self.API_BASE_URL,
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()

                data = response.json()
                records = self._parse_api_response(data, fetch_date)
                all_records.extend(records)

                logger.info(f"Fetched {len(records)} records for {fetch_date}")

        return all_records

    def _parse_api_response(
        self, data: Dict[str, Any], fetch_date: str
    ) -> List[Dict[str, Any]]:
        """
        Parse API response into standardized records.

        Args:
            data: Raw API response
            fetch_date: Date that was fetched

        Returns:
            List of normalized records
        """
        records = []

        # Nasdaq API typically returns data in data.rows
        if "data" not in data or "rows" not in data["data"]:
            logger.warning(f"No data found in API response for {fetch_date}")
            return records

        rows = data["data"]["rows"]

        for row in rows:
            # Extract fields - adjust based on actual API structure
            record = {
                "symbol": row.get("symbol", ""),
                "company_name": row.get("name", ""),
                "earnings_date": fetch_date,
                "earnings_time": row.get("time", ""),
                "market_cap": row.get("marketCap", None),
                "eps_forecast": self._parse_numeric(row.get("epsForecast")),
                "eps_actual": self._parse_numeric(row.get("epsActual")),
                "eps_surprise": self._parse_numeric(row.get("epsSurprise")),
                "revenue_forecast": self._parse_numeric(row.get("revenueForecast")),
                "revenue_actual": self._parse_numeric(row.get("revenueActual")),
                "num_estimates": self._parse_numeric(row.get("numEsts"), as_int=True),
                "fiscal_quarter": row.get("fiscalQuarterEnding", ""),
                "snapshot_date": datetime.utcnow().date().isoformat(),
                "scraped_at": datetime.utcnow().isoformat(),
            }
            records.append(record)

        return records

    def _fetch_via_playwright(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch data via Playwright browser automation.

        Args:
            date: Date to fetch (currently not supported, will fetch visible range)

        Returns:
            List of earnings records
        """
        records = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            try:
                logger.info(f"Navigating to {self.WEB_URL}")
                page.goto(self.WEB_URL, timeout=self.timeout * 1000)

                # Wait for table to load
                page.wait_for_selector("table", timeout=10000)

                # Extract table data
                # This is a simplified version - actual implementation would need
                # to handle pagination, date selection, etc.
                table = page.locator("table").first
                rows = table.locator("tbody tr").all()

                logger.info(f"Found {len(rows)} rows in table")

                for row in rows:
                    cells = row.locator("td").all()
                    if len(cells) >= 5:  # Adjust based on actual table structure
                        record = {
                            "symbol": cells[0].inner_text().strip(),
                            "company_name": cells[1].inner_text().strip(),
                            "earnings_date": cells[2].inner_text().strip(),
                            "earnings_time": cells[3].inner_text().strip(),
                            "eps_forecast": self._parse_numeric(cells[4].inner_text()),
                            "snapshot_date": datetime.utcnow().date().isoformat(),
                            "scraped_at": datetime.utcnow().isoformat(),
                        }
                        records.append(record)

            except PlaywrightTimeoutError as e:
                logger.error(f"Playwright timeout: {e}")
                raise

            finally:
                browser.close()

        return records

    def _get_date_range(self) -> List[str]:
        """
        Get list of dates to fetch based on days_ahead.

        Returns:
            List of date strings in YYYY-MM-DD format
        """
        dates = []
        today = datetime.utcnow().date()

        for i in range(self.days_ahead + 1):
            date = today + timedelta(days=i)
            dates.append(date.isoformat())

        return dates

    @staticmethod
    def _parse_numeric(value: Any, as_int: bool = False) -> Optional[float]:
        """
        Parse numeric value, handling various formats.

        Args:
            value: Value to parse
            as_int: Return as integer if True

        Returns:
            Parsed number or None
        """
        if value is None or value == "":
            return None

        # Handle string values
        if isinstance(value, str):
            # Remove common formatting
            cleaned = value.replace(",", "").replace("$", "").replace("%", "").strip()
            if cleaned in ["--", "N/A", ""]:
                return None
            try:
                num = float(cleaned)
                return int(num) if as_int else num
            except ValueError:
                return None

        # Handle numeric values
        try:
            num = float(value)
            return int(num) if as_int else num
        except (ValueError, TypeError):
            return None


def fetch_earnings_calendar(
    days_ahead: int = 30,
    date: Optional[str] = None,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Convenience function to fetch earnings calendar data.

    Args:
        days_ahead: Number of days ahead to fetch
        date: Specific date to fetch (YYYY-MM-DD)
        **kwargs: Additional arguments for NasdaqEarningsScraper

    Returns:
        List of earnings records
    """
    scraper = NasdaqEarningsScraper(days_ahead=days_ahead, **kwargs)
    return scraper.fetch(date=date)
