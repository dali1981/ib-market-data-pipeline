"""LangChain-based HTML scraper - uses LangChain for better LLM parsing."""

import json
from playwright.sync_api import sync_playwright
from datetime import datetime
import logging
from pathlib import Path
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import List, Literal

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/langchain_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Define output schema
class EarningsRecord(BaseModel):
    time: str = Field(description="Pre-Market or After Hours")
    symbol: str = Field(description="Stock ticker symbol")
    company_name: str = Field(description="Company name")
    market_cap: str = Field(description="Market capitalization")
    fiscal_quarter_ending: str = Field(description="Fiscal quarter ending")
    consensus_eps_forecast: str = Field(description="Consensus EPS forecast")
    num_estimates: int = Field(description="Number of estimates")
    last_year_report_date: str = Field(description="Last year report date")
    last_year_eps: str = Field(description="Last year EPS")


class ScraperDecision(BaseModel):
    action: Literal["next_page", "done", "error"] = Field(description="Next action to take")
    records_found: int = Field(description="Number of records found")
    records: List[EarningsRecord] = Field(description="List of earnings records")
    reasoning: str = Field(description="Explanation of decision")
    next_page_exists: bool = Field(description="Whether next page exists")


class LangChainEarningsScraper:
    """LangChain-powered scraper that parses HTML from Playwright."""

    def __init__(self, model="llama3.2:latest"):
        """Initialize scraper with LangChain."""
        self.model_name = model
        self.page = None
        self.all_records = []

        # Initialize LangChain components
        self.llm = ChatOllama(
            model=model,
            temperature=0,
            format="json"
        )

        self.parser = JsonOutputParser(pydantic_object=ScraperDecision)

        logger.info(f"Initialized LangChain scraper with model: {model}")
        logger.info(f"Using structured output with Pydantic schema")

    def scrape(self, url="https://www.nasdaq.com/market-activity/earnings"):
        """Main scraping loop controlled by LangChain agent."""

        with sync_playwright() as p:
            logger.info("="*70)
            logger.info("LANGCHAIN SCRAPER - Structured Output Parser")
            logger.info("="*70)
            logger.info("Launching Playwright browser...")

            browser = p.chromium.launch(headless=True, channel="chrome")
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            self.page = context.new_page()
            logger.info("✓ Browser launched")

            # Navigate
            logger.info(f"Navigating to {url}...")
            self.page.goto(url, wait_until="load")
            logger.info("✓ Page loaded")
            self.page.wait_for_timeout(2000)

            # Dismiss cookies
            logger.info("Dismissing cookies...")
            self._dismiss_cookies()
            logger.info("Waiting 10s for full page render...")
            self.page.wait_for_timeout(10000)

            # Start agent loop
            page_num = 1
            while True:
                logger.info(f"\n{'='*70}")
                logger.info(f"PAGE {page_num}")
                logger.info(f"{'='*70}")

                # Extract HTML
                page_html = self._extract_html()
                if not page_html:
                    logger.error("✗ Could not extract HTML")
                    break

                logger.info(f"✓ Extracted HTML: {len(page_html)} chars")

                # Save HTML context
                self._save_html(page_html, page_num)

                # Ask LangChain agent
                decision = self._agent_analyze(page_html, page_num)

                if not decision:
                    logger.error("✗ Agent returned no decision")
                    break

                logger.info(f"\nAgent Decision: {decision.action}")
                logger.info(f"Records found: {decision.records_found}")
                logger.info(f"Reasoning: {decision.reasoning}")

                # Store records
                if decision.records:
                    # Add metadata
                    current_date = datetime.now().date().isoformat()
                    for rec in decision.records:
                        rec_dict = rec.model_dump()
                        rec_dict['date'] = current_date
                        rec_dict['scraped_at'] = datetime.now().isoformat()
                        rec_dict['page_num'] = page_num
                        self.all_records.append(rec_dict)

                    logger.info(f"Total collected: {len(self.all_records)} records")

                # Execute action
                if decision.action == 'next_page':
                    logger.info(f"→ Paginating to page {page_num + 1}...")
                    success = self._click_next_page(page_num + 1)
                    if not success:
                        logger.warning("✗ Cannot paginate further")
                        break
                    logger.info(f"✓ Navigated to page {page_num + 1}")
                    page_num += 1
                    self.page.wait_for_timeout(3000)

                elif decision.action == 'done':
                    logger.info("✓ Agent indicates completion")
                    break

                elif decision.action == 'error':
                    logger.error(f"✗ Agent error")
                    break

                # Safety limit
                if page_num > 15:
                    logger.warning("⚠ Safety limit (15 pages)")
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
                logger.info("✓ Dismissed cookies")
        except:
            pass

    def _extract_html(self):
        """Extract rendered table HTML using Playwright."""
        try:
            logger.info("→ Waiting for table to render...")

            # Wait for table with Symbol header to be present (ensure it's rendered)
            self.page.wait_for_selector("table:has(th:has-text('Symbol'))", timeout=15000)
            logger.info("✓ Table detected")

            # Wait a bit more for all data to load
            self.page.wait_for_timeout(2000)

            # Get the earnings table specifically (has Symbol column header)
            logger.info("→ Extracting rendered table HTML...")
            table_html = self.page.eval_on_selector(
                "table:has(th:has-text('Symbol'))",
                "el => el.outerHTML"
            )

            logger.info(f"✓ Extracted rendered table HTML: {len(table_html)} chars")
            return table_html

        except Exception as e:
            logger.error(f"✗ Error extracting table: {e}")
            # Fallback: try to get any table
            try:
                logger.info("→ Fallback: getting largest table...")
                table_html = self.page.evaluate("""
                    () => {
                        const tables = document.querySelectorAll('table');
                        let largest = null;
                        let maxSize = 0;
                        for (const table of tables) {
                            const size = table.outerHTML.length;
                            if (size > maxSize) {
                                maxSize = size;
                                largest = table;
                            }
                        }
                        return largest ? largest.outerHTML : null;
                    }
                """)
                if table_html:
                    logger.info(f"✓ Fallback succeeded: {len(table_html)} chars")
                    return table_html
            except Exception as e2:
                logger.error(f"✗ Fallback failed: {e2}")
            return None

    def _save_html(self, html, page_num):
        """Save HTML to disk."""
        html_file = f"/tmp/langchain_scraper_html_page{page_num}.html"
        with open(html_file, 'w') as f:
            f.write(html)
        logger.info(f"✓ Saved HTML to: {html_file}")

        # Log a preview of what we extracted
        preview = html[:500] if html else "EMPTY"
        logger.info(f"  HTML preview: {preview[:200]}...")

        # Check if it looks like actual HTML
        if not html or '<table' not in html.lower():
            logger.error(f"⚠ WARNING: Extracted content doesn't look like table HTML!")
            logger.error(f"  Content starts with: {html[:100] if html else 'NULL'}")

    def _agent_analyze(self, page_html, page_num):
        """Use LangChain to analyze HTML and extract data."""

        logger.info(f"Building LangChain prompt...")
        logger.info(f"  Context: Page {page_num}, {len(self.all_records)} records so far")

        # Build prompt template
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert web scraping agent. Extract earnings data from HTML.

INSTRUCTIONS:
1. Find the earnings table in the HTML
2. Extract ALL earnings records from the table
3. For each record, extract these 9 fields:
   - time: Look for icons or text (sun/pre-market = "Pre-Market", moon/after-hours = "After Hours", otherwise "Time Not Supplied")
   - symbol: Stock ticker
   - company_name: Company name
   - market_cap: Market cap value
   - fiscal_quarter_ending: Fiscal quarter (e.g., Sep/2025)
   - consensus_eps_forecast: EPS forecast
   - num_estimates: Number of estimates (as integer)
   - last_year_report_date: Last year's date
   - last_year_eps: Last year's EPS

4. Decide next action:
   - "next_page" if you see pagination for more pages
   - "done" if this is the last page
   - "error" if you cannot parse the HTML

{format_instructions}"""),
            ("human", """CONTEXT:
- Page number: {page_num}
- Records extracted so far: {total_records}

HTML:
{html}

Extract all earnings records and decide next action.""")
        ])

        # Create chain
        chain = prompt | self.llm | self.parser

        # Log prompt instructions
        format_instructions = self.parser.get_format_instructions()
        logger.info(f"\n{'='*70}")
        logger.info(f"PROMPT (Page {page_num}):")
        logger.info(f"{'='*70}")
        logger.info(f"Context: Page {page_num}, {len(self.all_records)} records")
        logger.info(f"Format: Structured JSON with Pydantic schema")
        logger.info(f"{'='*70}")

        # Save prompt to file
        prompt_file = f"/tmp/langchain_scraper_prompt_page{page_num}.txt"
        with open(prompt_file, 'w') as f:
            f.write(f"Page: {page_num}\n")
            f.write(f"Total records: {len(self.all_records)}\n\n")
            f.write(format_instructions)
        logger.info(f"✓ Saved prompt to: {prompt_file}")

        try:
            import time
            start_time = time.time()

            logger.info(f"→ Invoking LangChain...")

            # Invoke chain
            result = chain.invoke({
                "page_num": page_num,
                "total_records": len(self.all_records),
                "html": page_html,
                "format_instructions": format_instructions
            })

            elapsed = time.time() - start_time
            logger.info(f"✓ Received response ({elapsed:.1f}s)")

            # Log response
            logger.info(f"\n{'='*70}")
            logger.info(f"RESPONSE (Page {page_num}):")
            logger.info(f"{'='*70}")
            logger.info(json.dumps(result, indent=2))
            logger.info(f"{'='*70}")

            # Save response
            response_file = f"/tmp/langchain_scraper_response_page{page_num}.json"
            with open(response_file, 'w') as f:
                json.dump(result, f, indent=2)
            logger.info(f"✓ Saved response to: {response_file}")

            # Parse into Pydantic model
            decision = ScraperDecision(**result)
            return decision

        except Exception as e:
            logger.error(f"✗ LangChain error: {e}", exc_info=True)
            return None

    def _click_next_page(self, next_page_num):
        """Click pagination button."""
        try:
            next_button = self.page.locator(f'button[data-page="{next_page_num}"]')
            if next_button.count() > 0:
                next_button.click(force=True)
                return True
            return False
        except:
            return False


if __name__ == "__main__":
    scraper = LangChainEarningsScraper(model="llama3.2:latest")
    records = scraper.scrape()

    # Save results
    output_file = f"earnings_langchain_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(records, f, indent=2)

    logger.info(f"\n{'='*70}")
    logger.info("SCRAPING COMPLETE")
    logger.info(f"{'='*70}")
    logger.info(f"Total records: {len(records)}")
    logger.info(f"Saved to: {output_file}")

    if records:
        logger.info(f"\nSample records:")
        for i, rec in enumerate(records[:3], 1):
            logger.info(f"{i}. {rec.get('symbol')} - {rec.get('company_name')}")
