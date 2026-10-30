import pytest
import subprocess
import os

def test_llm_catalog():
    result = subprocess.run(['python', 'scripts/llm_catalog_check.py'], capture_output=True, text=True)
    assert result.returncode == 0, f"Catalog check failed: {result.stdout}"
