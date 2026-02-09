import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import json
import logging

def get_token():
    print("Initializing Undetected Chrome...")
    options = uc.ChromeOptions()
    # Headless mode in UC is tricky, sometimes detected.
    # Trying headless=True first.
    options.add_argument("--headless=new") 
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    
    # Enable performance logging
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

    try:
        # UC downloads its own driver
        driver = uc.Chrome(options=options, headless=True, use_subprocess=True)
    except Exception as e:
        print(f"Failed to initialize UC driver: {e}")
        return None
    
    try:
        print("Opening https://spotidownloader.com/ ...")
        driver.get("https://spotidownloader.com/")
        
        # Wait for input
        print("Waiting for input box...")
        try:
            input_box = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='url'], input[type='text']"))
            )
            input_box.send_keys("https://open.spotify.com/track/2lZovFVlyWqwIYggSAuIcR")
            print("Entered URL.")
        except Exception as e:
            print(f"Could not find input box: {e}")
            return None

        # Click submit
        try:
            print("Clicking submit button...")
            # Try specific selector first, then generic
            try:
                submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            except:
                submit_btn = driver.find_element(By.CSS_SELECTOR, "button.btn-primary") # Guess
            
            submit_btn.click()
        except Exception as e:
            print(f"Could not find/click submit button: {e}")
            return None
        
        # Wait for network request
        print("Waiting to capture token...")
        start_time = time.time()
        
        while time.time() - start_time < 20: 
            logs = driver.get_log("performance")
            for entry in logs:
                try:
                    message_json = json.loads(entry["message"])
                    message = message_json["message"]
                    if message["method"] == "Network.requestWillBeSent":
                        req = message["params"]["request"]
                        if "api.spotidownloader.com/metadata" in req["url"]:
                            headers = req.get("headers", {})
                            auth = headers.get("Authorization") or headers.get("authorization")
                            if auth:
                                print(f"\nSUCCESS! Found Token:\n{auth}")
                                return auth
                except:
                    continue
            time.sleep(0.5)
            
        print("Timeout: Token not found in network logs.")
        
    except Exception as e:
        print(f"Error during execution: {e}")
    finally:
        if 'driver' in locals():
            driver.quit()
            
    return None

if __name__ == "__main__":
    get_token()
