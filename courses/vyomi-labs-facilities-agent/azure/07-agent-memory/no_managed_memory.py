import requests
from azlab import ENDPOINT

codes = [requests.get(ENDPOINT + p, params={"api-version": "2025-03-01-preview"}, timeout=10).status_code for p in ("/openai/memory_stores", "/openai/memories")]
print("memory routes answer:", codes, "-> no managed long-term memory API")
