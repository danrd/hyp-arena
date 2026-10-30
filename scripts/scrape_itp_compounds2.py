import urllib.request
import re
from bs4 import BeautifulSoup
import time
import json

def fetch_compounds(url, timestamp):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode(errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            # Look for tables or lists
            found = False
            for table in soup.find_all('table'):
                for row in table.find_all('tr'):
                    cols = row.find_all(['td', 'th'])
                    cols = [ele.text.strip() for ele in cols]
                    if cols:
                        print(f"{timestamp} | " + " | ".join(cols))
                        found = True

            if not found:
                for p in soup.find_all('p'):
                    if 'rationale' in p.text.lower() or 'compound' in p.text.lower():
                        print(f"TEXT {timestamp}:", p.text.strip())

    except Exception as e:
        print(f"Error fetching {timestamp}: {e}")

# Try fetching a few
urls = [
    ("20120129094056", "https://web.archive.org/web/20120129094056/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp/compounds-testing"),
    ("20130327165321", "https://web.archive.org/web/20130327165321/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp/compounds-testing"),
    ("20140707174058", "https://web.archive.org/web/20140707174058/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp/compounds-testing")
]
for ts, url in urls:
    fetch_compounds(url, ts)
    time.sleep(2)
