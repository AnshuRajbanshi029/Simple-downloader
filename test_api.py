import json
import requests

import base64

def get_metadata():
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbiI6IjAuX3hPbEJEUm5hVVZQMXAySlN4QjcyU2d3THItNDN0N0ZNXzVlTWJzd0c5NFBNRXcxdHRiaUdCNExLV0liU3VlZEtMY3paSlZmMDItSF9WajhnQ2dOTWs5cTVRMXg3T0ExMzZHYThmRW9BbXdONUMyV3Rib0dQTXZILWtZX3FwN05YRUhfZDJkc0NMbzRpcllCLUFZeTZENUtjM3ZZaWZnOFE1R1lVM1dLWVp1eWVXVWROSkMwVUVIUUp5bTRRZFQwNnVZSGl3NXB3TXR0b2ltVnY2UVNNbEVpd0xBc0FMNGF3ZXdMaTNlaGVXUzZHOVpySnIya0xUYkQzYXlJX1B3UEJLMGtLd2t0ZnYtRlVNX3hNcmV0aVV1c2gtZ09PRlFCUEV3bE5vN0RMc1ZvY0U1LUh0Zm01dFdtY2pPQ3prWFJraE1yc1RKQzV5N2NxRHJrNGdTVnZBYUo3VGJEaVhGaEVCSlVlS2VQaWhSNDNMeHA0OWh2NThxRDJ3amdrWWdqV1luZWcwVzZvcHV6Y1djek94NWk0bmZwQUFwUmQ0MFFaWnZva3ZKVWtUQm02VmI5MTNfTktIOEZEUjY1dk9nUUg5OUpyaU5SUk8zd3BqWE5PWVprSlQwV09zbWg2ZjVWUVdzT21VVmNmbVdILUJudTRaTVpmdE0zRFhMMzVuN3ljU1I4d1NQbXc0LWNIMnZfcUlQS1lZaDJXVlFkamh6bW5FZ2sxSkNaUzlQRVdFaU13aWhqMnFza1lvTHRLZkpiQm0tX0EwdmlKYXVad3E1Yy1HcDcwMTlZS3R5UUpRMEkzcTdTcU5sTXJsUmRMT1Y1VFZINGtCQXdGeDRpdGJESWFzQzlubkFfaGhBc2lEdzd2bFdUTjhqeUt1ZjlTMVpEcXZnZjlpcl91YjcyY01rTW1YbnB1LTlOdVJtU0ZyLXpBNWhhOG5FQXBjQ1A5SlNMaDg3UlpraUVMZktSeTgzNFZqMDExWjd6aGJlNHdOdVptVG5fQ1R3Ry1vclQzM3FRZ0VBZUlBYmV5WUNnZ191UkJ4VFQxcWpHQllCaFg4SGRmeFF6Ym5scVoyWlY2MEpLTzNiMnFPZ0MyZUoxdm1uX1p5MzBCYy1EX3oyMkNmX0trME9kS1ZqaVBMd0lSSlktQnZEVEpBc1V1bzN1bFVOU1N1U2dnX2RzLVc4ODl5cGRKVy1ESm4yRmc2c1hvNmZNell6ZVdhUU1NckJlcmtjZjF0SkRuQmk4QXU5RER3amU2TlpxM01TWDJ4V1M0c3ZVTWxzd2JlZG9kOXFnd2s1b0dZXzhjRzdBcExYMUsxdWlJUzhUQTktNnpkNjI5QVptQVNjbnRsZi12YzRhTE5kWS5lR0ZjNEw2SXVFSWRpeU5pdmJQZzBBLjIxMTlkNGQ0YzE4MzkzMzk4MjZiNjExZjQxMThkMjA1NzE5ZDI5ZTI1NDk1M2JmMWYzZTQ2N2MyNzkxOWM0ZjEiLCJpYXQiOjE3NzA2Mjc5ODcsImV4cCI6MTc3MDYyODU4N30.B3FOBROSHvXoKhyXx0o2khBuNShU2k-LdyPn3RootTw"
    track_id = "0uE3vuRgjaTBvW6kg3ybdq"
    
    # Decode JWT
    try:
        parts = token.split('.')
        payload_part = parts[1]
        # Pad base64
        payload_part += '=' * (-len(payload_part) % 4)
        decoded = base64.urlsafe_b64decode(payload_part)
        payload_json = json.loads(decoded)
        print(f"Decoded Token Payload: {json.dumps(payload_json, indent=2)}")
        
        import time
        now = time.time()
        exp = payload_json.get('exp', 0)
        print(f"Current Time: {now}")
        print(f"Token Exp:    {exp}")
        print(f"Time Remaining: {exp - now} seconds")
        
        if now > exp:
            print("ERROR: Token is EXPIRED!")
            return
            
    except Exception as e:
        print(f"Could not decode token: {e}")

    # Start a session to capture cookies
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Mobile Safari/537.36',
    })

    # Visit homepage to get cookies
    print("\nFetching homepage for cookies...")
    try:
        session.get("https://spotidownloader.com/")
        print(f"Cookies captured: {session.cookies.get_dict()}")
    except Exception as e:
        print(f"Failed to fetch homepage: {e}")

    url = "https://api.spotidownloader.com/metadata"

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Origin': 'https://spotidownloader.com',
        'Referer': 'https://spotidownloader.com/'
    }
    
    # Try 1: Standard ID
    payload = {
        'type': 'track',
        'id': track_id
    }

    print("\nSending request 1 with captured cookies...")
    response = session.post(url, headers=headers, json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
    
    if response.status_code == 200:
        return

    # Try 2: URL as ID (just in case)
    print("\nTrying URL as ID...")
    payload['id'] = f"https://open.spotify.com/track/{track_id}"
    response = requests.post(url, headers=headers, json=payload)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")

if __name__ == "__main__":
    get_metadata()
