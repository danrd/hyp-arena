import urllib.request
import re
from bs4 import BeautifulSoup
import time

def fetch_compounds(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode(errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            # Look for tables or lists
            print(f"URL: {url}")
            for table in soup.find_all('table'):
                for row in table.find_all('tr'):
                    cols = row.find_all(['td', 'th'])
                    cols = [ele.text.strip() for ele in cols]
                    if cols:
                        print(" | ".join(cols))

            # Look for paragraph text mentioning rationale
            for p in soup.find_all('p'):
                if 'rationale' in p.text.lower() or 'compound' in p.text.lower():
                    print("TEXT:", p.text.strip())

    except Exception as e:
        print(f"Error: {e}")

fetch_compounds("https://web.archive.org/web/20120127194542/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp/compounds-testing")
