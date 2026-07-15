# browser.py
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

def get_browser():
    options = uc.ChromeOptions()
    
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")

    # Anti-block flags
    options.add_argument("--start-maximized")
    options.add_argument("--disable-popup-blocking")
    
    # Initialize undetected-chromedriver
    # use_subprocess=True is often safer for avoiding zombie processes
    driver = uc.Chrome(options=options, use_subprocess=True)
    
    return driver


def fetch_html(url, wait=5):
    from utils.delay import delay
    delay(2, 4)
    driver = get_browser()
    driver.get(url)
    time.sleep(wait)
    html = driver.page_source
    driver.quit()
    return html
