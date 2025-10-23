"""Scrape Nasdaq earnings calendar using Playwright + Ollama Vision.

This script navigates to the Nasdaq earnings calendar page, takes screenshots
of the table, and uses Ollama's vision model to extract earnings data across all pages.
Compares two methods: full table screenshots vs individual row screenshots.
"""

import json
import csv
import base64
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import ollama


def scrape_nasdaq_earnings(date=None, headless=True, method="both"):
    """
    Scrape earnings data from Nasdaq using Playwright + Ollama Vision.

    Args:
        date: Optional date to fetch (format: YYYY-MM-DD). If None, uses current default.
        headless: Run browser in headless mode
        method: Extraction method - "full", "rows", or "both"

    Returns:
        Dictionary with results from each method
    """
    url = "https://www.nasdaq.com/market-activity/earnings"
    if date:
        url = f"{url}?date={date}"

    results = {
        "full_table": [],
        "individual_rows": [],
        "metadata": {
            "date": date,
            "pages_scraped": 0,
            "method": method,
            "timestamp": datetime.now().isoformat()
        }
    }

    with sync_playwright() as p:
        # Use Chromium
        browser = p.chromium.launch(
            headless=headless,
            channel="chrome",
            args=['--disable-blink-features=AutomationControlled']
        )

        # Create context with realistic settings
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

            # Wait for table to render
            print("  Waiting for table to render...")
            page.wait_for_timeout(15000)

            # Extract current date from page
            current_date = extract_current_date(page)
            print(f"Current date: {current_date}")

            # Get total records count
            pagination_text = page.locator("text=/\\d+ - \\d+ of \\d+/").inner_text()
            total_records = int(pagination_text.split("of")[-1].strip())
            print(f"Total records to scrape: {total_records}\n")

            # Scrape all pages
            page_num = 1
            while True:
                print(f"{'='*60}")
                print(f"SCRAPING PAGE {page_num}")
                print(f"{'='*60}")

                # Method A: Full table screenshot
                if method in ["full", "both"]:
                    print("\n[Method A: Full Table Screenshot]")
                    records_full = extract_with_full_table_screenshot(page, current_date, page_num)
                    results["full_table"].extend(records_full)
                    print(f"  ✓ Extracted {len(records_full)} records")
                    print(f"  Total so far: {len(results['full_table'])}")

                # Method B: Individual row screenshots
                if method in ["rows", "both"]:
                    print("\n[Method B: Individual Row Screenshots]")
                    records_rows = extract_with_row_screenshots(page, current_date, page_num)
                    results["individual_rows"].extend(records_rows)
                    print(f"  ✓ Extracted {len(records_rows)} records")
                    print(f"  Total so far: {len(results['individual_rows'])}")

                # Check for next page
                next_button = page.locator('button:has-text("click to go to the next page")')

                if next_button.count() == 0:
                    print("\n✓ No next page button found. Done.")
                    break

                is_disabled = next_button.is_disabled()
                if is_disabled:
                    print("\n✓ Next page button is disabled. Done.")
                    break

                # Click next page
                print("\n  → Clicking next page...")
                next_button.click()
                page.wait_for_timeout(3000)

                page_num += 1

            results["metadata"]["pages_scraped"] = page_num

            # Print summary
            print(f"\n{'='*60}")
            print("SCRAPING COMPLETE")
            print(f"{'='*60}")
            if method in ["full", "both"]:
                print(f"Method A (Full Table): {len(results['full_table'])} records")
            if method in ["rows", "both"]:
                print(f"Method B (Row-by-Row): {len(results['individual_rows'])} records")
            print(f"Expected: {total_records} records")
            print(f"Pages scraped: {page_num}")

        except PlaywrightTimeoutError as e:
            print(f"Timeout error: {e}")
            raise
        except Exception as e:
            print(f"Error: {e}")
            raise
        finally:
            browser.close()

    return results


def extract_current_date(page):
    """Extract the current earnings date from the page."""
    try:
        # Look for the date display (e.g., "Oct 22, 2025")
        date_text = page.locator("text=/[A-Z][a-z]{2} \\d{1,2}, \\d{4}/").first.inner_text()

        # Parse to ISO format
        dt = datetime.strptime(date_text, "%b %d, %Y")
        return dt.date().isoformat()
    except:
        # Fallback to today's date
        return datetime.now().date().isoformat()


def extract_with_full_table_screenshot(page, current_date, page_num):
    """
    Method A: Take single screenshot of entire table and extract all rows at once.

    Args:
        page: Playwright page object
        current_date: Current date being viewed
        page_num: Current page number

    Returns:
        List of earnings records
    """
    screenshot_path = f"/tmp/nasdaq_full_table_page_{page_num}.png"

    # Take screenshot of full viewport
    page.screenshot(path=screenshot_path)
    print(f"  Screenshot saved: {screenshot_path}")

    # Read screenshot as bytes
    with open(screenshot_path, "rb") as f:
        image_bytes = f.read()

    # Prepare prompt for Ollama
    prompt = f"""Analyze this Nasdaq earnings calendar table screenshot.

Extract ALL visible rows from the earnings table. For each row, extract these EXACT fields:

1. time - Look at the ICON in the first column:
   - If you see a SUN icon or orange/yellow icon = "Pre-Market"
   - If you see a MOON icon or blue/dark icon = "After Hours"
   - If no icon or unclear = "Time Not Supplied"

2. symbol - Stock ticker (e.g., TSLA, IBM, SAP)
3. company_name - Full company name
4. market_cap - Market capitalization (e.g., $1,443,162,596,405)
5. fiscal_quarter_ending - Fiscal quarter (e.g., Sep/2025)
6. consensus_eps_forecast - EPS forecast (e.g., $0.41)
7. num_estimates - Number of estimates (e.g., 11)
8. last_year_report_date - Date (e.g., 10/23/2024)
9. last_year_eps - Last year's EPS (e.g., $0.62)

Return ONLY a valid JSON array. Each object must have ALL 9 fields above.
Do NOT include table headers or pagination info.
Return format:
[
  {{"time": "Pre-Market", "symbol": "TSLA", "company_name": "Tesla, Inc", "market_cap": "$1,443,162,596,405", ...}},
  ...
]"""

    try:
        # Call Ollama vision model
        response = ollama.chat(
            model='llama3.2-vision:11b',
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': [image_bytes]
            }]
        )

        # Parse JSON response
        content = response['message']['content']

        # Clean up content - remove control characters
        import re
        content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

        # Extract JSON from response (in case there's extra text)
        json_start = content.find('[')
        json_end = content.rfind(']') + 1
        if json_start >= 0 and json_end > json_start:
            json_str = content[json_start:json_end]
            records = json.loads(json_str)
        else:
            print(f"  ⚠ No JSON array found in response")
            return []

        # Add date and scraped_at to each record
        for record in records:
            record['date'] = current_date
            record['scraped_at'] = datetime.now().isoformat()

        return records

    except Exception as e:
        print(f"  ✗ Error with Ollama extraction: {e}")
        return []


def extract_with_row_screenshots(page, current_date, page_num):
    """
    Method B: Take individual screenshot of each table row and extract separately.

    Args:
        page: Playwright page object
        current_date: Current date being viewed
        page_num: Current page number

    Returns:
        List of earnings records
    """
    records = []

    # Find all table rows (skip header)
    # Use a broad selector to find the table container
    try:
        # Wait a bit for table to be stable
        page.wait_for_timeout(1000)

        # Scroll to table
        page.evaluate("window.scrollTo(0, 400)")
        page.wait_for_timeout(500)

        # Take individual row screenshots - we know there should be ~10 rows per page
        # Instead of trying to locate rows, we'll screenshot row-by-row based on position

        # Get table bounding box estimate (adjust based on page structure)
        table_top = 450  # Approximate Y position of table start
        row_height = 60  # Approximate height of each row

        for row_idx in range(10):  # Expect up to 10 rows per page
            # Calculate row position
            y_pos = table_top + (row_idx * row_height)

            # Screenshot this row area
            screenshot_path = f"/tmp/nasdaq_row_page{page_num}_row{row_idx}.png"

            try:
                page.screenshot(
                    path=screenshot_path,
                    clip={'x': 0, 'y': y_pos, 'width': 1600, 'height': row_height}
                )

                # Read screenshot
                with open(screenshot_path, "rb") as f:
                    image_bytes = f.read()

                # Prepare prompt for single row
                prompt = f"""Analyze this single row from a Nasdaq earnings table.

Extract these EXACT fields from this ONE row:

1. time - Look at the ICON on the left:
   - SUN icon or orange/yellow = "Pre-Market"
   - MOON icon or blue/dark = "After Hours"
   - No icon = "Time Not Supplied"

2. symbol - Stock ticker
3. company_name - Company name
4. market_cap - Market cap value
5. fiscal_quarter_ending - Fiscal quarter
6. consensus_eps_forecast - EPS forecast
7. num_estimates - Number of estimates
8. last_year_report_date - Report date
9. last_year_eps - Last year EPS

Return ONLY a valid JSON object with these 9 fields. If this is a header row or empty, return: {{"skip": true}}

Format:
{{"time": "Pre-Market", "symbol": "TSLA", "company_name": "Tesla, Inc", ...}}"""

                # Call Ollama
                response = ollama.chat(
                    model='llama3.2-vision:11b',
                    messages=[{
                        'role': 'user',
                        'content': prompt,
                        'images': [image_bytes]
                    }]
                )

                content = response['message']['content']

                # Clean up content - remove control characters
                import re
                content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

                # Extract JSON
                json_start = content.find('{')
                json_end = content.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = content[json_start:json_end]
                    record = json.loads(json_str)

                    # Skip if marked to skip or no symbol
                    if record.get('skip') or not record.get('symbol'):
                        continue

                    # Add metadata
                    record['date'] = current_date
                    record['scraped_at'] = datetime.now().isoformat()
                    records.append(record)

            except Exception as e:
                # Likely ran out of rows
                if row_idx >= 5:  # Only warn if we haven't extracted at least 5 rows
                    break
                continue

    except Exception as e:
        print(f"  ✗ Error with row extraction: {e}")

    return records


def save_results(results, output_format="both"):
    """Save extraction results to files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if output_format in ["json", "both"]:
        # Save Method A results
        if results["full_table"]:
            filename_a = f"earnings_method_a_full_table_{timestamp}.json"
            with open(filename_a, "w") as f:
                json.dump(results["full_table"], f, indent=2)
            print(f"\n✓ Saved Method A results: {filename_a}")

        # Save Method B results
        if results["individual_rows"]:
            filename_b = f"earnings_method_b_rows_{timestamp}.json"
            with open(filename_b, "w") as f:
                json.dump(results["individual_rows"], f, indent=2)
            print(f"✓ Saved Method B results: {filename_b}")

        # Save comparison
        comparison = {
            "method_a_count": len(results["full_table"]),
            "method_b_count": len(results["individual_rows"]),
            "metadata": results["metadata"]
        }
        comparison_file = f"earnings_comparison_{timestamp}.json"
        with open(comparison_file, "w") as f:
            json.dump(comparison, f, indent=2)
        print(f"✓ Saved comparison: {comparison_file}")

    if output_format in ["csv", "both"]:
        # Save Method A to CSV
        if results["full_table"]:
            filename_csv_a = f"earnings_method_a_full_table_{timestamp}.csv"
            save_to_csv(results["full_table"], filename_csv_a)

        # Save Method B to CSV
        if results["individual_rows"]:
            filename_csv_b = f"earnings_method_b_rows_{timestamp}.csv"
            save_to_csv(results["individual_rows"], filename_csv_b)


def save_to_csv(records, filename):
    """Save records to CSV file."""
    if not records:
        return

    fieldnames = records[0].keys()
    with open(filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    print(f"✓ Saved CSV: {filename}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Scrape Nasdaq earnings calendar with Ollama Vision")
    parser.add_argument("--date", help="Date to fetch (YYYY-MM-DD)")
    parser.add_argument("--output", default="both", choices=["json", "csv", "both"],
                       help="Output format")
    parser.add_argument("--method", default="both", choices=["full", "rows", "both"],
                       help="Extraction method: full table, individual rows, or both")
    parser.add_argument("--no-headless", action="store_true",
                       help="Show browser window")

    args = parser.parse_args()

    print("="*60)
    print("NASDAQ EARNINGS SCRAPER - Ollama Vision")
    print("="*60)
    print(f"Method: {args.method}")
    print(f"Headless: {not args.no_headless}")
    print(f"Date: {args.date or 'Current'}")
    print("="*60)

    # Scrape data
    results = scrape_nasdaq_earnings(
        date=args.date,
        headless=not args.no_headless,
        method=args.method
    )

    # Save results
    save_results(results, output_format=args.output)

    # Print comparison
    print(f"\n{'='*60}")
    print("COMPARISON SUMMARY")
    print(f"{'='*60}")
    if results["full_table"]:
        print(f"Method A (Full Table): {len(results['full_table'])} records")
    if results["individual_rows"]:
        print(f"Method B (Row-by-Row): {len(results['individual_rows'])} records")

    if results["full_table"] and results["individual_rows"]:
        diff = abs(len(results["full_table"]) - len(results["individual_rows"]))
        print(f"Difference: {diff} records")

        if diff == 0:
            print("✓ Both methods extracted same count!")
        else:
            print("⚠ Methods extracted different counts - review results")

    print(f"{'='*60}")
