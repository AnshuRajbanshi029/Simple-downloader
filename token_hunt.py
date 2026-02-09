import requests
import json

BASE_URL = "https://api.spotidownloader.com"
SITE_URL = "https://spotidownloader.com"

def test_endpoint(method, url, data=None, headers=None):
    print(f"\nTesting {method} {url}...")
    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, timeout=10)
        else:
            response = requests.post(url, json=data, headers=headers, timeout=10)
            
        print(f"Status: {response.status_code}")
        try:
            print(f"Body: {json.dumps(response.json(), indent=2)}")
        except:
            print(f"Body: {response.text[:200]}...") # Print first 200 chars
            
    except Exception as e:
        print(f"Error: {e}")

def main():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Origin': SITE_URL,
        'Referer': SITE_URL + '/'
    }

    # 1. GET /token
    test_endpoint('GET', f"{BASE_URL}/token", headers=headers)
    
    # 2. GET /api/init (on site url?)
    test_endpoint('GET', f"{SITE_URL}/api/init", headers=headers)
    test_endpoint('GET', f"{BASE_URL}/api/init", headers=headers)

    # 3. POST /auth/refresh (try with expired token if available, or empty)
    # I'll try with a dummy token or the expired one
    expired_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbiI6IjAuX3hPbEJEUm5hVVZQMXAySlN4QjcyU2d3THItNDN0N0ZNXzVlTWJzd0c5NFBNRXcxdHRiaUdCNExLV0liU3VlZEtMY3paSlZmMDItSF9WajhnQ2dOTWs5cTVRMXg3T0ExMzZHYThmRW9BbXdONUMyV3Rib0dQTXZILWtZX3FwN05YRUhfZDJkc0NMbzRpcllCLUFZeTZENUtjM3ZZaWZnOFE1R1lVM1dLWVp1eWVXVWROSkMwVUVIUUp5bTRRZFQwNnVZSGl3NXB3TXR0b2ltVnY2UVNNbEVpd0xBc0FMNGF3ZXdMaTNlaGVXUzZHOVpySnIya0xUYkQzYXlJX1B3UEJLMGtLd2t0ZnYtRlVNX3hNcmV0aVV1c2gtZ09PRlFCUEV3bE5vN0RMc1ZvY0U1LUh0Zm01dFdtY2pPQ3prWFJraE1yc1RKQzV5N2NxRHJrNGdTVnZBYUo3VGJEaVhGaEVCSlVlS2VQaWhSNDNMeHA0OWh2NThxRDJ3amdrWWdqV1luZWcwVzZvcHV6Y1djek94NWk0bmZwQUFwUmQ0MFFaWnZva3ZKVWtUQm02VmI5MTNfTktIOEZEUjY1dk9nUUg5OUpyaU5SUk8zd3BqWE5PWVprSlQwV09zbWg2ZjVWUVdzT21VVmNmbVdILUJudTRaTVpmdE0zRFhMMzVuN3ljU1I4d1NQbXc0LWNIMnZfcUlQS1lZaDJXVlFkamh6bW5FZ2sxSkNaUzlQRVdFaU13aWhqMnFza1lvTHRLZkpiQm0tX0EwdmlKYXVad3E1Yy1HcDcwMTlZS3R5UUpRMEkzcTdTcU5sTXJsUmRMT1Y1VFZINGtCQXdGeDRpdGJESWFzQzlubkFfaGhBc2lEdzd2bFdUTjhqeUt1ZjlTMVpEcXZnZjlpcl91YjcyY01rTW1YbnB1LTlOdVJtU0ZyLXpBNWhhOG5FQXBjQ1A5SlNMaDg3UlpraUVMZktSeTgzNFZqMDExWjd6aGJlNHdOdVptVG5fQ1R3Ry1vclQzM3FRZ0VBZUlBYmV5WUNnZ191UkJ4VFQxcWpHQllCaFg4SGRmeFF6Ym5scVoyWlY2MEpLTzNiMnFPZ0MyZUoxdm1uX1p5MzBCYy1EX3oyMkNmX0trME9kS1ZqaVBMd0lSSlktQnZEVEpBc1V1bzN1bFVOU1N1U2dnX2RzLVc4ODl5cGRKVy1ESm4yRmc2c1hvNmZNell6ZVdhUU1NckJlcmtjZjF0SkRuQmk4QXU5RER3amU2TlpxM01TWDJ4V1M0c3ZVTWxzd2JlZG9kOXFnd2s1b0dZXzhjRzdBcExYMUsxdWlJUzhUQTktNnpkNjI5QVptQVNjbnRsZi12YzRhTE5kWS5lR0ZjNEw2SXVFSWRpeU5pdmJQZzBBLjIxMTlkNGQ0YzE4MzkzMzk4MjZiNjExZjQxMThkMjA1NzE5ZDI5ZTI1NDk1M2JmMWYzZTQ2N2MyNzkxOWM0ZjEiLCJpYXQiOjE3NzA2Mjc5ODcsImV4cCI6MTc3MDYyODU4N30.B3FOBROSHvXoKhyXx0o2khBuNShU2k-LdyPn3RootTw"
    
    test_endpoint('POST', f"{BASE_URL}/auth/refresh", data={'token': expired_token}, headers=headers)
    
    # 4. GET /login (maybe it returns a set-cookie?)
    test_endpoint('GET', f"{SITE_URL}/login", headers=headers)
    
    # 5. Check Homepage for embedded config?
    print("\nScanning homepage for embedded JSON/Token...")
    try:
        response = requests.get(SITE_URL, headers=headers)
        if "token" in response.text.lower():
            print("Found 'token' in homepage HTML! Dumping context...")
            # Find the line with 'token'
            for line in response.text.splitlines():
                if "token" in line.lower() and len(line) < 500:
                    print(line.strip())
        else:
            print("No 'token' found in homepage HTML.")
            
        # Check Cookies
        print(f"Cookies: {response.cookies.get_dict()}")
        
    except Exception as e:
        print(f"Homepage Error: {e}")

if __name__ == "__main__":
    main()
