"""Debug script to inspect Nasdaq table structure."""

from curl_cffi import requests
from bs4 import BeautifulSoup

url = "https://www.nasdaq.com/market-activity/earnings"

print(f"Fetching {url}...")
response = requests.get(
    url,
    timeout=30,
    impersonate="chrome120"
)

soup = BeautifulSoup(response.text, "lxml")
tables = soup.find_all("table")

print(f"\nFound {len(tables)} tables\n")

for i, table in enumerate(tables[:5]):  # Check first 5 tables
    print(f"\n{'='*60}")
    print(f"TABLE {i+1}:")
    print(f"{'='*60}")

    # Get headers
    headers = []
    header_row = table.find("thead")
    if header_row:
        th_tags = header_row.find_all(["th", "td"])
        headers = [th.get_text(strip=True) for th in th_tags]
        print(f"Headers: {headers}")
    else:
        print("No thead found")

    # Get first few rows
    tbody = table.find("tbody")
    if tbody:
        rows = tbody.find_all("tr")[:3]  # First 3 rows
        print(f"Data rows: {len(tbody.find_all('tr'))}")

        for j, row in enumerate(rows):
            cells = row.find_all("td")
            cell_data = [cell.get_text(strip=True) for cell in cells]
            print(f"  Row {j+1}: {cell_data}")
    else:
        print("No tbody found")
