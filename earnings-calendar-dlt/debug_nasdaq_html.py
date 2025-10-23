"""Debug script to inspect actual Nasdaq HTML structure."""

from curl_cffi import requests
from bs4 import BeautifulSoup

url = "https://www.nasdaq.com/market-activity/earnings"

print(f"Fetching {url}...")
response = requests.get(
    url,
    timeout=30,
    impersonate="chrome120"
)

print(f"Status: {response.status_code}")
print(f"Content length: {len(response.text)}")

soup = BeautifulSoup(response.text, "lxml")

# Find all tables
tables = soup.find_all("table")
print(f"\nFound {len(tables)} tables")

# Look for divs that might contain data
divs_with_earnings = soup.find_all("div", class_=lambda x: x and "earnings" in x.lower())
print(f"Found {len(divs_with_earnings)} divs with 'earnings' in class name")

# Look for script tags that might contain JSON data
scripts = soup.find_all("script")
json_scripts = [s for s in scripts if "earnings" in s.text.lower()]
print(f"Found {len(json_scripts)} script tags mentioning 'earnings'")

# Print first script that has JSON-like content
for script in scripts:
    if "__NEXT_DATA__" in script.text or "window.__" in script.text:
        print("\n" + "="*60)
        print("Found Next.js data or window object:")
        print("="*60)
        print(script.text[:500])
        break

# Save full HTML for inspection
with open("/tmp/nasdaq_earnings.html", "w") as f:
    f.write(response.text)
print(f"\nFull HTML saved to /tmp/nasdaq_earnings.html")
