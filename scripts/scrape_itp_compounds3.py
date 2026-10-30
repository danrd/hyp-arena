import urllib.request
from bs4 import BeautifulSoup
import time

urls_to_try = [
    "https://web.archive.org/web/20120429084334/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp/compounds-testing",
    "https://web.archive.org/web/20121020070233/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp/compounds-testing",
    "https://web.archive.org/web/20130129232706/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp/compounds-testing",
    "https://web.archive.org/web/20130731082415/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp/compounds-testing"
]

for url in urls_to_try:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode(errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            print(f"\n--- URL: {url} ---")
            found = False
            for table in soup.find_all('table'):
                for row in table.find_all('tr'):
                    cols = row.find_all(['td', 'th'])
                    cols = [ele.text.strip() for ele in cols]
                    if cols:
                        print(" | ".join(cols))
                        found = True

            if not found:
                for p in soup.find_all('p'):
                    if 'rationale' in p.text.lower() or 'compound' in p.text.lower():
                        print("TEXT:", p.text.strip())

    except Exception as e:
        print(f"Error fetching {url}: {e}")
    time.sleep(2)
