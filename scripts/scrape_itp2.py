import urllib.request
import re
from bs4 import BeautifulSoup

def fetch_and_parse(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode(errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            # Extract text to see if there is rationale
            text = soup.get_text()
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            for line in lines:
                if 'rationale' in line.lower() or 'compound' in line.lower():
                    print(line)
    except Exception as e:
        print(f"Error: {e}")

fetch_and_parse("https://web.archive.org/web/20120127194542/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp")
