# browser.py
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

def get_browser():
    options = uc.ChromeOptions()
    
    # Anti-block flags
    options.add_argument("--start-maximized")
    options.add_argument("--disable-popup-blocking")
    
    # Initialize undetected-chromedriver
    # use_subprocess=True is often safer for avoiding zombie processes
    driver = uc.Chrome(options=options, use_subprocess=True)
    
    return driver


def fetch_html(url, wait=5):
    driver = get_browser()
    driver.get(url)
    time.sleep(wait)
    html = driver.page_source
    # input("Press Enter to close browser...")
    driver.quit()
    return html
