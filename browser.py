# browser.py
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

def get_browser():
    options = Options()

    # DO NOT USE HEADLESS
    # options.add_argument("--headless=new")

    # Anti-block flags
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")

    # DNS fix flags
    options.add_argument("--disable-features=UseDnsHttpsSvcb")
    options.add_argument("--disable-features=EnforceDnsHttps")
    options.add_argument("--disable-features=EncryptedClientHello")
    options.add_argument("--disable-features=UseChromeOSDirectDNSConfig")
    options.add_argument("--disable-features=UseDNSHTTPS")
    options.add_argument("--dns-prefetch-disable")

    # Safety
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-running-insecure-content")

    # IMPORTANT: Pass options
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    return driver


def fetch_html(url, wait=5):
    driver = get_browser()
    driver.get(url)
    time.sleep(wait)
    html = driver.page_source
    # input("Press Enter to close browser...")
    driver.quit()
    return html
