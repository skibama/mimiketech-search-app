import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Your connection details
es_url = "https://7f5e3429796d45748b57199b8b00f8d2.us-east-1.aws.found.io:443"
api_key = "OU9VcTg1VUJqeXlLQnlwZHdtdHE6ZUlqcHdodTVTWmFpTXh0cjNUVDg1UQ=="

# Try basic connection
print(f"Testing connection to {es_url}")
try:
    # Try with API key in header
    headers = {"Authorization": f"ApiKey {api_key}"}
    response = requests.get(es_url, headers=headers, verify=False, timeout=10)
    print(f"Status code: {response.status_code}")
    print(f"Response content: {response.text[:200]}")  # First 200 chars
    
    # If we get here, we got some response
    if response.status_code == 200:
        print("Connection successful!")
    else:
        print(f"Connection received but returned status code {response.status_code}")
except requests.exceptions.ConnectionError as e:
    print(f"Connection error: {e}")
except requests.exceptions.Timeout:
    print("Connection timed out - server may be unreachable")
except Exception as e:
    print(f"Other error: {e}")