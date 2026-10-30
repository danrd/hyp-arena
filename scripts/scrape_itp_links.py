import urllib.request
import re
from bs4 import BeautifulSoup
import time

def fetch_links(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as resp:
            html = resp.read().decode(errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            for a in soup.find_all('a', href=True):
                if 'compound' in a.text.lower() or 'testing' in a.text.lower() or 'itp' in a['href'].lower():
                    print(f"{a.text.strip()} - {a['href']}")
    except Exception as e:
        print(f"Error: {e}")

fetch_links("https://web.archive.org/web/20120127194542/http://www.nia.nih.gov/research/dab/interventions-testing-program-itp")
