"""OllamaReader - Parses screenshots using Ollama vision model with MPS acceleration."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
import ollama


class OllamaReader:
    """Reads earnings data from screenshots using Ollama vision model."""

    def __init__(self, model="llama3.2-vision:11b", use_mps=True):
        """
        Initialize the reader.

        Args:
            model: Ollama model to use
            use_mps: Use Metal Performance Shaders (Mac GPU acceleration)
        """
        self.model = model
        self.use_mps = use_mps

        # Test Ollama connection
        try:
            ollama.list()
            print(f"✓ Ollama connected")
            print(f"  Model: {model}")
            print(f"  MPS: {'Enabled' if use_mps else 'Disabled'}")
        except Exception as e:
            raise RuntimeError(f"Cannot connect to Ollama: {e}")

    def parse_screenshot(self, screenshot_path: str, current_date: str) -> List[Dict[str, Any]]:
        """
        Parse a single screenshot and extract earnings records.

        Args:
            screenshot_path: Path to screenshot image
            current_date: Date for the records (YYYY-MM-DD)

        Returns:
            List of earnings records
        """
        print(f"\n  Parsing {Path(screenshot_path).name}...")

        # Read screenshot
        with open(screenshot_path, "rb") as f:
            image_bytes = f.read()

        # Prepare prompt
        prompt = self._build_prompt()

        try:
            # Call Ollama with MPS options
            # Note: Ollama automatically uses Metal/MPS on Mac if available
            # We can set num_gpu=1 to ensure GPU usage
            options = {"num_gpu": 1} if self.use_mps else {"num_gpu": 0}

            response = ollama.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': [image_bytes]
                }],
                options=options
            )

            # Parse response
            content = response['message']['content']
            records = self._parse_json_response(content, current_date)

            print(f"    ✓ Extracted {len(records)} records")
            return records

        except Exception as e:
            print(f"    ✗ Error: {e}")
            return []

    def parse_all_screenshots(self, screenshot_data: List[Dict]) -> List[Dict[str, Any]]:
        """
        Parse multiple screenshots.

        Args:
            screenshot_data: List of dicts with 'path', 'page_num', 'date'

        Returns:
            List of all earnings records
        """
        all_records = []

        print(f"\n{'='*60}")
        print(f"PARSING {len(screenshot_data)} SCREENSHOTS")
        print(f"{'='*60}")

        for item in screenshot_data:
            records = self.parse_screenshot(
                screenshot_path=item['path'],
                current_date=item['date']
            )
            all_records.extend(records)

            print(f"    Total so far: {len(all_records)} records")

        print(f"\n{'='*60}")
        print(f"✓ PARSING COMPLETE: {len(all_records)} total records")
        print(f"{'='*60}")

        return all_records

    def _build_prompt(self) -> str:
        """Build the prompt for Ollama."""
        return """Analyze this Nasdaq earnings calendar table screenshot.

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
  {"time": "Pre-Market", "symbol": "TSLA", "company_name": "Tesla, Inc", "market_cap": "$1,443,162,596,405", ...},
  ...
]"""

    def _parse_json_response(self, content: str, current_date: str) -> List[Dict[str, Any]]:
        """Parse JSON from Ollama response."""
        # Clean control characters
        content = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', content)

        # Extract JSON array
        json_start = content.find('[')
        json_end = content.rfind(']') + 1

        if json_start < 0 or json_end <= json_start:
            return []

        json_str = content[json_start:json_end]

        try:
            records = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"      ⚠ JSON parse error: {e}")
            return []

        # Add metadata
        for record in records:
            record['date'] = current_date
            record['scraped_at'] = datetime.now().isoformat()

        return records


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse earnings screenshots with Ollama")
    parser.add_argument("--screenshot-dir", default="/tmp/nasdaq_screenshots", help="Screenshot directory")
    parser.add_argument("--model", default="llama3.2-vision:11b", help="Ollama model")
    parser.add_argument("--no-mps", action="store_true", help="Disable MPS acceleration")
    parser.add_argument("--output", default="earnings_parsed.json", help="Output JSON file")

    args = parser.parse_args()

    print("="*60)
    print("OLLAMA READER - Screenshot Parser")
    print("="*60)

    # Load metadata
    metadata_file = Path(args.screenshot_dir) / "metadata.json"
    with open(metadata_file, "r") as f:
        metadata = json.load(f)

    # Create reader
    reader = OllamaReader(
        model=args.model,
        use_mps=not args.no_mps
    )

    # Parse all screenshots
    records = reader.parse_all_screenshots(metadata["screenshots"])

    # Save results
    with open(args.output, "w") as f:
        json.dump(records, f, indent=2)

    print(f"\n✓ Saved {len(records)} records to {args.output}")
    print(f"  Expected: {metadata['metadata']['total_records']} records")
    print(f"  Difference: {metadata['metadata']['total_records'] - len(records)}")
