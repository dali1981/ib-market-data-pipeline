"""Intelligent scraper using Ollama vision + reasoning agent with Playwright tools."""

import json
import ollama
from playwright.sync_api import sync_playwright
from datetime import datetime
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/intelligent_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class IntelligentEarningsScraper:
    """LLM agent that can see, reason, and control the browser."""

    def __init__(self, model="llama3.2-vision:11b"):
        self.model = model
        self.page = None
        self.all_records = []

    def scrape(self, url="https://www.nasdaq.com/market-activity/earnings"):
        """Main scraping loop controlled by LLM agent."""

        with sync_playwright() as p:
            # Launch browser
            logger.info("="*70)
            logger.info("INTELLIGENT SCRAPER - LLM Agent with Playwright Tools")
            logger.info("="*70)
            logger.info("Launching Playwright browser (headless Chrome)...")

            browser = p.chromium.launch(headless=True, channel="chrome")
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            self.page = context.new_page()
            logger.info("✓ Browser launched successfully")

            # Navigate
            logger.info(f"Navigating to {url}...")
            self.page.goto(url, wait_until="load")
            logger.info("✓ Page loaded")
            self.page.wait_for_timeout(2000)

            # Dismiss cookies
            logger.info("Attempting to dismiss cookie consent...")
            self._dismiss_cookies()
            logger.info("Waiting 10s for page to fully render...")
            self.page.wait_for_timeout(10000)

            # Start agent loop
            page_num = 1
            while True:
                logger.info(f"\n{'='*70}")
                logger.info(f"PAGE {page_num}")
                logger.info(f"{'='*70}")

                # Take screenshot
                screenshot_path = f"/tmp/nasdaq_page_{page_num}.png"
                logger.info(f"Taking screenshot of table area...")
                logger.info(f"  Clip: x=250, y=400, width=1400, height=850")
                self.page.screenshot(
                    path=screenshot_path,
                    clip={'x': 250, 'y': 400, 'width': 1400, 'height': 850}
                )
                file_size = Path(screenshot_path).stat().st_size / 1024  # KB
                logger.info(f"✓ Screenshot saved: {screenshot_path} ({file_size:.1f} KB)")

                # Ask LLM agent to analyze and decide
                decision = self._agent_analyze_and_decide(screenshot_path, page_num)

                logger.info(f"\nAgent Decision: {decision['action']}")
                logger.info(f"Extracted: {decision['records_found']} records")

                # Store records
                if decision.get('records'):
                    self.all_records.extend(decision['records'])
                    logger.info(f"Total records collected: {len(self.all_records)}")

                # Execute action
                if decision['action'] == 'next_page':
                    logger.info(f"→ Attempting pagination to page {page_num + 1}...")
                    success = self._click_next_page(page_num + 1)
                    if not success:
                        logger.warning("✗ Cannot paginate further. Stopping.")
                        break
                    logger.info(f"✓ Successfully navigated to page {page_num + 1}")
                    page_num += 1
                    logger.info("Waiting 3s for page transition...")
                    self.page.wait_for_timeout(3000)

                elif decision['action'] == 'scroll_down':
                    logger.info("→ Scrolling down 500px...")
                    self.page.evaluate("window.scrollBy(0, 500)")
                    self.page.wait_for_timeout(1000)

                elif decision['action'] == 'done':
                    logger.info("✓ Agent indicates completion - all pages scraped")
                    break

                elif decision['action'] == 'error':
                    logger.error(f"✗ Agent error: {decision.get('message')}")
                    break

                # Safety limit
                if page_num > 15:
                    logger.warning("⚠ Safety limit reached (15 pages)")
                    break

            logger.info("Closing browser...")
            browser.close()
            logger.info("✓ Browser closed")

        return self.all_records

    def _dismiss_cookies(self):
        """Dismiss cookie consent."""
        try:
            cookie_btn = self.page.locator('button:has-text("I Accept")')
            if cookie_btn.count() > 0:
                cookie_btn.first.click(force=True)
                logger.info("✓ Dismissed cookie consent dialog")
            else:
                logger.info("No cookie consent dialog found")
        except Exception as e:
            logger.warning(f"Could not dismiss cookies: {e}")

    def _agent_analyze_and_decide(self, screenshot_path, page_num):
        """
        Send screenshot to LLM agent for analysis and decision making.

        Agent's job:
        1. Analyze the screenshot
        2. Extract all earnings records visible
        3. Decide next action: next_page, scroll_down, or done
        """

        # Read screenshot
        logger.info(f"Reading screenshot: {screenshot_path}")
        with open(screenshot_path, "rb") as f:
            image_bytes = f.read()
        logger.info(f"  Image size: {len(image_bytes)/1024:.1f} KB")

        # Build agent prompt
        logger.info(f"Building agent prompt...")
        logger.info(f"  Context: Page {page_num}, {len(self.all_records)} records collected so far")
        prompt = f"""You are an intelligent web scraping agent analyzing a Nasdaq earnings calendar screenshot.

CURRENT CONTEXT:
- Page number: {page_num}
- Total records extracted so far: {len(self.all_records)}

YOUR TASKS:
1. Extract ALL earnings records from this table screenshot
2. For each record, extract these 9 fields:
   - time: Look at icon (sun=Pre-Market, moon=After Hours)
   - symbol: Stock ticker
   - company_name: Company name
   - market_cap: Market cap value
   - fiscal_quarter_ending: Fiscal quarter
   - consensus_eps_forecast: EPS forecast
   - num_estimates: Number of estimates
   - last_year_report_date: Last year's date
   - last_year_eps: Last year's EPS

3. Decide NEXT ACTION:
   - If you see pagination buttons (page 2, 3, etc.) and we haven't scraped all pages → "next_page"
   - If table is cut off at bottom → "scroll_down"
   - If this looks like the last page or no more data → "done"
   - If you can't parse the screenshot → "error"

RETURN FORMAT (JSON only):
{{
  "action": "next_page" | "scroll_down" | "done" | "error",
  "records_found": <number of records extracted>,
  "records": [
    {{"time": "Pre-Market", "symbol": "TSLA", "company_name": "Tesla, Inc", ...}},
    ...
  ],
  "reasoning": "Brief explanation of decision",
  "next_page_exists": true/false
}}

Return ONLY valid JSON, no other text."""

        try:
            # Call Ollama with vision
            logger.info(f"→ Sending request to Ollama API...")
            logger.info(f"  Model: {self.model}")
            logger.info(f"  GPU: MPS acceleration enabled (num_gpu=1)")
            logger.info(f"  Prompt length: {len(prompt)} chars")

            import time
            start_time = time.time()

            response = ollama.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': [image_bytes]
                }],
                # options={"num_gpu": 1}
            )

            elapsed = time.time() - start_time
            content = response['message']['content']

            logger.info(f"✓ Received response from Ollama ({elapsed:.1f}s)")
            logger.info(f"  Response length: {len(content)} chars")

            # Log first 200 chars of response for debugging
            preview = content[:200].replace('\n', ' ')
            logger.debug(f"  Response preview: {preview}...")

            logger.info(f"→ Parsing JSON response...")

            # Parse JSON
            import re
            content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)
            json_start = content.find('{')
            json_end = content.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = content[json_start:json_end]
                decision = json.loads(json_str)
                logger.info(f"✓ Parsed JSON successfully")

                # Log decision details
                logger.info(f"  Action: {decision.get('action')}")
                logger.info(f"  Records found: {decision.get('records_found', 0)}")
                logger.info(f"  Next page exists: {decision.get('next_page_exists', 'unknown')}")
                logger.info(f"  Reasoning: {decision.get('reasoning', 'N/A')}")

                # Add metadata to records
                current_date = datetime.now().date().isoformat()
                for rec in decision.get('records', []):
                    rec['date'] = current_date
                    rec['scraped_at'] = datetime.now().isoformat()
                    rec['page_num'] = page_num

                return decision
            else:
                logger.error(f"✗ Could not find JSON in response")
                logger.error(f"  Content preview: {content[:500]}")
                return {
                    "action": "error",
                    "records_found": 0,
                    "message": "Could not parse LLM response as JSON"
                }

        except Exception as e:
            logger.error(f"✗ Agent error: {e}", exc_info=True)
            return {
                "action": "error",
                "records_found": 0,
                "message": str(e)
            }

    def _click_next_page(self, next_page_num):
        """Click pagination button for next page."""
        try:
            next_button = self.page.locator(f'button[data-page="{next_page_num}"]')
            if next_button.count() > 0:
                next_button.click(force=True)
                return True
            return False
        except:
            return False


if __name__ == "__main__":
    scraper = IntelligentEarningsScraper(model="llama3.2-vision:11b")
    records = scraper.scrape()

    # Save results
    output_file = f"earnings_intelligent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(records, f, indent=2)

    print(f"\n{'='*70}")
    print("SCRAPING COMPLETE")
    print(f"{'='*70}")
    print(f"Total records extracted: {len(records)}")
    print(f"Saved to: {output_file}")

    if records:
        print(f"\nSample records:")
        for i, rec in enumerate(records[:3], 1):
            print(f"{i}. {rec.get('symbol')} - {rec.get('company_name')}")
