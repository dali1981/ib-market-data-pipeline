"""PlaywrightScraper - Handles browser automation and screenshot capture."""

from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


class PlaywrightScraper:
    """Scrapes Nasdaq earnings calendar pages and saves screenshots."""

    def __init__(self, headless=True, screenshot_dir="/tmp/nasdaq_screenshots"):
        """
        Initialize the scraper.

        Args:
            headless: Run browser in headless mode
            screenshot_dir: Directory to save screenshots
        """
        self.headless = headless
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(exist_ok=True)

    def scrape_all_pages(self, date=None):
        """
        Navigate through all pages and save screenshots.

        Args:
            date: Optional date (YYYY-MM-DD)

        Returns:
            dict with metadata and screenshot paths
        """
        url = "https://www.nasdaq.com/market-activity/earnings"
        if date:
            url = f"{url}?date={date}"

        results = {
            "screenshots": [],
            "metadata": {
                "date": date,
                "current_date": None,
                "total_records": 0,
                "pages_scraped": 0,
                "timestamp": datetime.now().isoformat()
            }
        }

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                channel="chrome",
                args=['--disable-blink-features=AutomationControlled']
            )

            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='en-US',
                timezone_id='America/New_York',
            )

            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                })
            """)

            page = context.new_page()

            try:
                print(f"Navigating to {url}...")
                page.goto(url, wait_until="load", timeout=30000)

                # Dismiss cookie consent FIRST
                try:
                    print("  Checking for cookie consent...")
                    page.wait_for_timeout(2000)

                    # Try multiple cookie consent button selectors
                    cookie_button = page.locator('button:has-text("I Accept")')
                    if cookie_button.count() == 0:
                        cookie_button = page.locator('button:has-text("Accept All")')
                    if cookie_button.count() == 0:
                        cookie_button = page.locator('button.onetrust-close-btn-handler')

                    if cookie_button.count() > 0:
                        cookie_button.first.click(force=True)
                        print("  ✓ Dismissed cookie consent")
                        page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"  ⚠ Could not dismiss cookies: {e}")

                # Wait for table to render
                print("  Waiting for table to render...")
                page.wait_for_timeout(12000)

                # Extract metadata
                current_date = self._extract_date(page)
                results["metadata"]["current_date"] = current_date
                print(f"  Current date: {current_date}")

                # Get total records
                pagination_text = page.locator("text=/\\d+ - \\d+ of \\d+/").inner_text()
                total_records = int(pagination_text.split("of")[-1].strip())
                results["metadata"]["total_records"] = total_records
                print(f"  Total records: {total_records}")

                # Loop through all pages and take screenshots
                page_num = 1
                while True:
                    print(f"\n{'='*60}")
                    print(f"PAGE {page_num}")
                    print(f"{'='*60}")

                    # Take screenshot
                    screenshot_path = self.screenshot_dir / f"page_{page_num}.png"
                    page.screenshot(path=str(screenshot_path))
                    print(f"  ✓ Screenshot saved: {screenshot_path}")

                    results["screenshots"].append({
                        "page_num": page_num,
                        "path": str(screenshot_path),
                        "date": current_date
                    })

                    # Try to find and click next button
                    try:
                        # Look for pagination button with data-page attribute
                        next_page_num = page_num + 1
                        next_button = page.locator(f'button[data-page="{next_page_num}"]')

                        if next_button.count() == 0:
                            print("  → No next page button found")
                            break

                        # Try to click (force to bypass overlays)
                        print(f"  → Clicking to page {next_page_num}...")
                        next_button.click(force=True)
                        page.wait_for_timeout(4000)  # Wait for page transition

                    except Exception as e:
                        print(f"  → End of pagination: {e}")
                        break

                    page_num += 1

                results["metadata"]["pages_scraped"] = page_num
                print(f"\n{'='*60}")
                print(f"✓ Captured {page_num} pages")
                print(f"{'='*60}")

            except PlaywrightTimeoutError as e:
                print(f"✗ Timeout error: {e}")
                raise
            except Exception as e:
                print(f"✗ Error: {e}")
                raise
            finally:
                browser.close()

        return results

    def _extract_date(self, page):
        """Extract current date from page."""
        try:
            date_text = page.locator("text=/[A-Z][a-z]{2} \\d{1,2}, \\d{4}/").first.inner_text()
            dt = datetime.strptime(date_text, "%b %d, %Y")
            return dt.date().isoformat()
        except:
            return datetime.now().date().isoformat()


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Capture screenshots of Nasdaq earnings calendar")
    parser.add_argument("--date", help="Date to fetch (YYYY-MM-DD)")
    parser.add_argument("--no-headless", action="store_true", help="Show browser")
    parser.add_argument("--output-dir", default="/tmp/nasdaq_screenshots", help="Screenshot directory")

    args = parser.parse_args()

    print("="*60)
    print("PLAYWRIGHT SCRAPER - Screenshot Capture")
    print("="*60)

    scraper = PlaywrightScraper(
        headless=not args.no_headless,
        screenshot_dir=args.output_dir
    )

    results = scraper.scrape_all_pages(date=args.date)

    # Save metadata
    metadata_file = Path(args.output_dir) / "metadata.json"
    with open(metadata_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✓ Metadata saved to {metadata_file}")
    print(f"✓ Screenshots saved to {args.output_dir}")
