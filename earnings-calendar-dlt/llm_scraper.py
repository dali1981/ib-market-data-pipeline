"""LLM-based HTML scraper - extracts rendered HTML and uses text LLM to parse."""

import json
import ollama
from playwright.sync_api import sync_playwright
from datetime import datetime
import logging
from pathlib import Path

SCHEMA = {
  "type": "object",
  "properties": {
    "action": {"type": "string", "enum": ["next_page","done","error"]},
    "records_found": {"type": "integer"},
    "records": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "time": {"type":"string"},
          "symbol": {"type":"string"},
          "company_name": {"type":"string"},
          "market_cap": {"type":["string","null"]},
          "fiscal_quarter_ending": {"type":["string","null"]},
          "consensus_eps_forecast": {"type":["string","null"]},
          "num_estimates": {"type":["integer","null"]},
          "last_year_report_date": {"type":["string","null"]},
          "last_year_eps": {"type":["string","null"]},
          "row_index": {"type":"integer"}  # audit hook
        },
        "required": ["symbol","company_name","row_index"]
      }
    },
    "reasoning": {"type":"string"},
    "next_page_exists": {"type":"boolean"}
  },
  "required": ["action","records_found","records","reasoning","next_page_exists"]
}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/llm_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class LLMEarningsScraper:
    """LLM agent that parses rendered HTML from Playwright."""

    def __init__(self, model="llama3.2:latest"):
        """
        Initialize scraper.

        Args:
            model: Ollama text model to use (default: llama3.2:3b for speed)
        """
        self.model = model
        self.page = None
        self.all_records = []

        logger.info(f"Initialized LLM scraper with model: {model}")

    def scrape(self, url="https://www.nasdaq.com/market-activity/earnings"):
        """Main scraping loop controlled by LLM agent."""

        with sync_playwright() as p:
            # Launch browser
            logger.info("="*70)
            logger.info("LLM SCRAPER - HTML Parser with Text LLM")
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

                # Extract HTML table
                table_html = self._extract_table_html()
                if not table_html:
                    logger.error("✗ Could not extract table HTML")
                    break

                logger.info(f"✓ Extracted table HTML ({len(table_html)} chars)")

                # Save HTML context to disk
                self._save_context_to_disk(table_html, page_num)

                # Ask LLM agent to analyze and decide
                decision = self._agent_analyze_and_decide(table_html, page_num)

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

    def _extract_table_html(self):
        """Extract the full page HTML after JavaScript rendering."""
        try:
            logger.info("→ Extracting rendered page HTML...")

            # Just wait a fixed time for JS to render - fuck networkidle
            logger.info("  Waiting 5s for JavaScript to render...")
            self.page.wait_for_timeout(5000)

            # Get entire page HTML
            page_html = self.page.content()

            logger.info(f"✓ Extracted page HTML: {len(page_html)} chars")

            # Log page title for verification
            title = self.page.title()
            logger.info(f"  Page title: {title}")

            return page_html

        except Exception as e:
            logger.error(f"✗ Error extracting page HTML: {e}", exc_info=True)
            return None

    def _save_context_to_disk(self, table_html, page_num):
        """Save HTML context to disk for debugging."""
        try:
            # Save full HTML table
            html_file = f"/tmp/llm_scraper_html_page{page_num}.html"
            with open(html_file, 'w') as f:
                f.write(table_html)
            logger.info(f"✓ Saved HTML context to: {html_file}")

            return table_html

        except Exception as e:
            logger.error(f"✗ Error extracting table HTML: {e}")
            return None

    def _agent_analyze_and_decide(self, table_html, page_num):
        """
        Send table HTML to LLM agent for analysis and decision making.

        Agent's job:
        1. Parse the HTML table
        2. Extract all earnings records
        3. Decide next action: next_page or done
        """

        # Build agent prompt
        logger.info(f"Building agent prompt...")
        logger.info(f"  Context: Page {page_num}, {len(self.all_records)} records collected so far")

        prompt = f"""You are an intelligent web scraping agent analyzing a Nasdaq earnings calendar HTML table.

CURRENT CONTEXT:
- Page number: {page_num}
- Total records extracted so far: {len(self.all_records)}

YOUR TASKS:
1. Parse the HTML table below and extract ALL earnings records
2. For each row in the table, extract these 9 fields:
   - time: Look for icon class or text (sun/pre-market icon = "Pre-Market", moon/after-hours icon = "After Hours")
   - symbol: Stock ticker
   - company_name: Company name
   - market_cap: Market capitalization value
   - fiscal_quarter_ending: Fiscal quarter (e.g., Sep/2025)
   - consensus_eps_forecast: EPS forecast
   - num_estimates: Number of estimates
   - last_year_report_date: Last year's report date
   - last_year_eps: Last year's EPS
   
WRITE ALL RECORDS FOUND IN JSON FORMAT. ALL RECORDS MUST BE INCLUDED. NO ... IS VALID

3. Decide NEXT ACTION based on pagination indicators in the HTML:
   - If you see pagination buttons for next pages (like page 2, 3, etc.) → "next_page"
   - If this appears to be the last page or no more pagination → "done"
   - If you cannot parse the HTML → "error"
   

HTML TABLE:
{table_html}


Return ONLY valid JSON, no other text."""

        ## RETURN FORMAT (JSON only):
# {{
#   "action": "next_page" | "done" | "error",
#   "records_found": <number of records extracted>,
#   "records": [
#     {{"time": "Pre-Market", "symbol": "TSLA", "company_name": "Tesla, Inc", "market_cap": "$X", "fiscal_quarter_ending": "Sep/2025", "consensus_eps_forecast": "$0.41", "num_estimates": 11, "last_year_report_date": "10/23/2024", "last_year_eps": "$0.62"}},
#     ...
#   ],
#   "reasoning": "Brief explanation of decision",
#   "next_page_exists": true/false
# }}
#
        try:
            # Call Ollama with text model
            logger.info(f"→ Sending request to Ollama API...")
            logger.info(f"  Model: {self.model}")
            logger.info(f"  Prompt length: {len(prompt)} chars")

            # Log just the instructions part (no HTML context)
            prompt_instructions = prompt.split("HTML TABLE:")[0]
            logger.info(f"\n{'='*70}")
            logger.info(f"PROMPT (Page {page_num}):")
            logger.info(f"{'='*70}")
            logger.info(prompt_instructions)
            logger.info(f"{'='*70}")

            # Save full prompt to file
            prompt_file = f"/tmp/llm_scraper_prompt_page{page_num}.txt"
            with open(prompt_file, 'w') as f:
                f.write(prompt)
            logger.info(f"✓ Saved full prompt to: {prompt_file}")

            import time
            start_time = time.time()

            system_msg = (
                "You transform INPUT HTML into OUTPUT JSON.\n"
                "- INPUT is raw HTML. Do NOT validate or critique the input as JSON.\n"
                "- OUTPUT must be valid JSON matching the provided schema.\n"
                "- If a field is missing in the HTML, use null.\n"
                "- records_found must equal the number of objects in records.\n"
                "- Only include rows you can evidence from the HTML.\n"
            )

            user_prompt = f"""
            TASK:
            Parse the Nasdaq earnings HTML table below. For each data row (<tr> excluding headers), extract:
            time, symbol, company_name, market_cap, fiscal_quarter_ending, consensus_eps_forecast,
            num_estimates, last_year_report_date, last_year_eps. Also include row_index (0-based among data rows).

            PAGINATION DECISION:
            - If a Next/» or numbered next-page control exists, set action="next_page", next_page_exists=true.
            - If none exists, set action="done", next_page_exists=false.
            - Only use action="error" if the HTML is clearly not a table or is empty/truncated.

            HTML START
            {table_html}
            HTML END
            """
            response = ollama.chat(
                model=self.model,
                format=SCHEMA,
                options={"temperature": 0},
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_prompt},
                ]
            )

            elapsed = time.time() - start_time
            content = response['message']['content']

            logger.info(f"✓ Received response from Ollama ({elapsed:.1f}s)")
            logger.info(f"  Response length: {len(content)} chars")

            # Log response to console
            logger.info(f"\n{'='*70}")
            logger.info(f"RESPONSE (Page {page_num}):")
            logger.info(f"{'='*70}")
            logger.info(content)
            logger.info(f"{'='*70}")

            # Save response to file
            response_file = f"/tmp/llm_scraper_response_page{page_num}.txt"
            with open(response_file, 'w') as f:
                f.write(content)
            logger.info(f"✓ Saved response to: {response_file}")

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
    # scraper = LLMEarningsScraper(model="llama3.2:latest")
    # scraper = LLMEarningsScraper(model="gpt-oss:20b")
    scraper = LLMEarningsScraper(model="gemma3:12b")
    records = scraper.scrape()

    # Save results
    output_file = f"earnings_llm_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(records, f, indent=2)

    logger.info(f"\n{'='*70}")
    logger.info("SCRAPING COMPLETE")
    logger.info(f"{'='*70}")
    logger.info(f"Total records extracted: {len(records)}")
    logger.info(f"Saved to: {output_file}")

    if records:
        logger.info(f"\nSample records:")
        for i, rec in enumerate(records[:3], 1):
            logger.info(f"{i}. {rec.get('symbol')} - {rec.get('company_name')}")
