import os
import time
import pickle
import random
import gspread
import re
import json
import base64
from google.oauth2.service_account import Credentials

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# CẤU HÌNH & LẤY GIÁ TRỊ TỪ GITHUB SECRETS
# ==========================================
SHEET_ID_OR_URL = os.getenv('SHEET_ID_OR_URL', 'https://docs.google.com/spreadsheets/d/1xyHLonUX4dm8Bmt055MGunpZX6andoDOvHUtf-BXnqQ/edit?gid=0#gid=0')
INPUT_TAB_NAME = os.getenv('INPUT_TAB_NAME', 'Sheet1')

USERNAME = os.getenv('LINKEDIN_USERNAME', 'ray@sam-foundation.org')
PASSWORD = os.getenv('LINKEDIN_PASSWORD', 'passnotE@1234')
LINKEDIN_COOKIES_B64 = os.getenv('LINKEDIN_COOKIES_B64', '').strip()

# ==========================================
# 1. SETUP DRIVER (HEADLESS CHROME)
# ==========================================
def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US,en")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(35)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

# ==========================================
# 2. KẾT NỐI GOOGLE SHEET QUA SERVICE ACCOUNT
# ==========================================
def connect_google_sheet():
    try:
        service_account_info = os.getenv("SERVICE_ACCOUNT_JSON")
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        if service_account_info:
            creds_dict = json.loads(service_account_info)
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            gc = gspread.authorize(creds)
        else:
            gc = gspread.service_account(filename="service_account.json", scopes=scopes)

        sh = gc.open_by_url(SHEET_ID_OR_URL) if "http" in SHEET_ID_OR_URL else gc.open_by_key(SHEET_ID_OR_URL)
        return sh
    except Exception as e:
        print(f"⚠️ Lỗi kết nối Sheet: {e}")
        return None

# ==========================================
# 3. ĐĂNG NHẬP LINKEDIN
# ==========================================
def login_linkedin(driver):
    print("INFO: Đang truy cập LinkedIn...")
    driver.get("https://www.linkedin.com/login")
    time.sleep(2)

    # 1. Khôi phục Cookie từ GitHub Secret
    if LINKEDIN_COOKIES_B64:
        print("INFO: Đang nạp Cookie từ Secret LINKEDIN_COOKIES_B64...")
        cookies_list = []
        try:
            # Thử giải mã binary pickle (từ Colab)
            try:
                raw_bytes = base64.b64decode(LINKEDIN_COOKIES_B64)
                cookies_list = pickle.loads(raw_bytes)
            except Exception:
                # Thử giải mã chuỗi JSON Base64
                try:
                    raw_str = base64.b64decode(LINKEDIN_COOKIES_B64).decode('utf-8')
                    cookies_list = json.loads(raw_str)
                except Exception:
                    # JSON thuần
                    cookies_list = json.loads(LINKEDIN_COOKIES_B64)
        except Exception as e:
            print(f"⚠️ Lỗi giải mã Cookie Secret: {e}")

        if cookies_list and isinstance(cookies_list, list):
            for cookie in cookies_list:
                cookie.pop('sameSite', None)
                try:
                    driver.add_cookie(cookie)
                except Exception:
                    pass

            driver.get("https://www.linkedin.com/feed")
            time.sleep(5)

            if "feed" in driver.current_url or driver.find_elements(By.CLASS_NAME, 'global-nav__me-photo'):
                print("✅ Đăng nhập thành công bằng Cookies Secret!")
                return True
            else:
                print("⚠️ Cookies Secret không vào được feed. Thử xóa cookie và chuyển sang login form...")
                driver.delete_all_cookies()

    # 2. Đăng nhập bằng Form (Fallback)
    print("INFO: Mở trang đăng nhập để điền Credentials...")
    driver.get("https://www.linkedin.com/login")
    time.sleep(3)

    try:
        try:
            cookie_btn = driver.find_element(By.XPATH, "//button[contains(@data-tracking-control-name, 'cookie') or contains(text(), 'Accept') or contains(text(), 'Accepteren')]")
            driver.execute_script("arguments[0].click();", cookie_btn)
            time.sleep(1)
        except Exception:
            pass

        username_element = None
        selectors_user = [
            (By.ID, "username"),
            (By.ID, "session_key"),
            (By.NAME, "session_key"),
            (By.CSS_SELECTOR, "input[name='session_key']"),
            (By.CSS_SELECTOR, "input#username")
        ]

        for by, sel in selectors_user:
            try:
                el = WebDriverWait(driver, 2).until(EC.visibility_of_element_located((by, sel)))
                if el and el.is_displayed():
                    username_element = el
                    break
            except Exception:
                continue

        if not username_element:
            inputs = driver.find_elements(By.TAG_NAME, "input")
            for inp in inputs:
                if inp.is_displayed() and inp.get_attribute("type") in ["text", "email"]:
                    username_element = inp
                    break

        if not username_element:
            print("❌ Không tìm thấy ô nhập Email.")
            driver.save_screenshot("no_visible_input.png")
            return False

        driver.execute_script("arguments[0].scrollIntoView(true);", username_element)
        try:
            username_element.clear()
            username_element.send_keys(USERNAME)
        except Exception:
            driver.execute_script("arguments[0].value = arguments[1];", username_element, USERNAME)

        password_element = None
        pass_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        for p_in in pass_inputs:
            if p_in.is_displayed():
                password_element = p_in
                break

        if not password_element:
            print("❌ Không tìm thấy ô Password.")
            return False

        driver.execute_script("arguments[0].scrollIntoView(true);", password_element)
        try:
            password_element.clear()
            password_element.send_keys(PASSWORD)
        except Exception:
            driver.execute_script("arguments[0].value = arguments[1];", password_element, PASSWORD)

        time.sleep(1)

        submitted = False
        try:
            password_element.send_keys(Keys.ENTER)
            submitted = True
        except Exception:
            pass

        if not submitted:
            submit_selectors = [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.CSS_SELECTOR, "button[data-id='sign-in-form__submit-btn']"),
                (By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'sign in')]"),
                (By.XPATH, "//button[@type='submit']")
            ]
            for by, sel in submit_selectors:
                try:
                    btns = driver.find_elements(by, sel)
                    for b in btns:
                        if b.is_displayed():
                            driver.execute_script("arguments[0].click();", b)
                            submitted = True
                            break
                    if submitted:
                        break
                except Exception:
                    continue

        if not submitted:
            driver.execute_script("arguments[0].form.submit();", password_element)

        time.sleep(6)

        if any(x in driver.current_url for x in ["checkpoint", "challenge", "authwall"]):
            print(f"🛑 CẢNH BÁO: LinkedIn yêu cầu OTP/Captcha tại {driver.current_url}")
            driver.save_screenshot("authwall_checkpoint.png")
            return False

        if "feed" in driver.current_url or driver.find_elements(By.CLASS_NAME, 'global-nav__me-photo'):
            print("✅ Đăng nhập thành công bằng tài khoản và mật khẩu!")
            return True
        else:
            print(f"ERROR: Chưa vào được trang Feed. URL: {driver.current_url}")
            driver.save_screenshot("login_failed.png")
            return False

    except Exception as e:
        print(f"ERROR: Lỗi trong quá trình đăng nhập: {e}")
        driver.save_screenshot("login_error.png")
        return False

# ==========================================
# 4. CRAWL PROFILE
# ==========================================
def crawl_profile(driver, raw_url):
    try:
        url = raw_url.strip()
        driver.get(url)

        print(f"--- Processing: {url}")
        time.sleep(random.uniform(5, 7))
        page_source = driver.page_source
        page_title = driver.title

        if "This page doesn’t exist" in page_source or "Page not found" in page_title:
            print("⚠️ Cảnh báo: Hồ sơ không tồn tại (404).")
            return {
                "Name": "No Profile",
                "Headline": "",
                "Locality": "",
                "Connections": "",
                "Company": ""
            }, "NOT_FOUND"

        if "This page isn’t working" in page_title or "redirected you too many times" in page_source:
            print("🛑 Lỗi Redirect Loop (ERR_TOO_MANY_REDIRECTS).")
            driver.save_screenshot("redirect_loop_error.png")
            return None, "REDIRECT_LOOP"

        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(1)

        if any(x in driver.current_url for x in ["login", "authwall", "checkpoint", "challenge"]):
            print("Debug: Auth wall detected.")
            driver.save_screenshot(f"authwall_{int(time.time())}.png")
            return None, "AUTH_WALL"

        data_js = driver.execute_script("""
            const txt = (sel) => document.querySelector(sel)?.innerText.trim() || "";

            const sideBarElements = Array.from(document.querySelectorAll('div[role="button"]'))
                .map(el => el.innerText.trim())
                .filter(t => t.length > 3 && !t.includes('connection') && !t.includes('follower') && !t.includes('kết nối'));

            const lines = Array.from(document.querySelectorAll('p, div.text-body-medium'))
                .map(el => el.innerText.trim())
                .filter(t => t.length > 0);

            const headline = txt('div.text-body-medium.break-words') ||
                             txt('h2.top-card-layout__headline') ||
                             lines.find(t => t.includes(" at ") || t.length > 20) || "";

            let loc = "";
            const contactAnchor = document.querySelector('a[href*="contact-info"]');
            if (contactAnchor) {
                const parentText = contactAnchor.closest('div')?.innerText || "";
                loc = parentText.split('·')[0].replace('Contact info', '').replace('Thông tin liên hệ', '').trim();
            }
            if (!loc) {
                loc = txt('span.text-body-small.inline.t-black--light.break-words') ||
                      txt('span.top-card__subline-item') ||
                      txt('span[class*="location"]') || "";
            }

            return {
                name: txt('h1.text-heading-xlarge') || txt('div[data-display-contents="true"] h2') || txt('h1') || "",
                headline: headline,
                locality: loc,
                company: sideBarElements.slice(0, 2).join(" | ") || "",
                connection_raw: document.body.innerText
            };
        """)

        name = data_js.get('name', '').strip()
        headline = data_js.get('headline', '').strip()
        locality = data_js.get('locality', '').strip()
        company = data_js.get('company', '').strip()
        conn_source = data_js.get('connection_raw', '')

        if not name and page_title and "linkedin" in page_title.lower():
            clean_name = page_title.split("|")[0].split(" - ")[0].split(" – ")[0].strip()
            if clean_name and "this page" not in clean_name.lower():
                name = clean_name

        if not name:
            slug = url.rstrip("/").split("/")[-1].split("?")[0]
            if slug:
                name = " ".join([word.capitalize() for word in slug.replace("-", " ").split() if not word.isdigit()])

        if not company and " at " in headline:
            company = headline.split(" at ")[-1].split("|")[0].split("•")[0].strip()
        elif not company and " @ " in headline:
            company = headline.split(" @ ")[-1].split("|")[0].split("•")[0].strip()

        connections = ""
        match = re.search(r'([\d,\.\+]+)\s*(connections|kết nối|followers|người theo dõi)', conn_source, re.I)
        if match:
            connections = f"{match.group(1)} connections"

        print(f"Debug: Name: '{name}' | Headline: '{headline}' | Loc: '{locality}' | Conn: '{connections}' | Comp: '{company}'")

        return {
            "Name": name if name else "LinkedIn Member",
            "Headline": headline,
            "Locality": locality,
            "Connections": connections,
            "Company": company
        }, "Success"

    except Exception as e:
        print(f"Debug: Error at {url} - {str(e)}")
        return None, str(e)

# ==========================================
# 5. MAIN WORKFLOW
# ==========================================
def main():
    MAX_PROFILE = int(os.getenv('MAX_PROFILE', '25'))
    count = 0

    sh = connect_google_sheet()
    if not sh:
        print("❌ Không thể kết nối Google Sheet!")
        return

    tab_name = (os.getenv('INPUT_TAB_NAME') or '').strip()
    try:
        ws = sh.worksheet(tab_name) if tab_name else sh.get_worksheet(0)
    except Exception:
        ws = sh.get_worksheet(0)

    all_rows = ws.get_all_values()

    driver = setup_driver()
    try:
        if not login_linkedin(driver):
            return

        for i in range(1, len(all_rows)):
            row_data = all_rows[i]
            url = row_data[0].strip() if len(row_data) > 0 else ""

            if not url or "linkedin.com/in/" not in url:
                continue

            name_existing = row_data[1].strip() if len(row_data) > 1 else ""
            status_existing = row_data[6].strip() if len(row_data) > 6 else ""

            if name_existing and name_existing != "This page isn’t working" and status_existing in ["Success", "NOT_FOUND", "No Profile"]:
                continue

            print(f"\n🔄 Đang xử lý dòng {i+1}: {url}")
            data, status = crawl_profile(driver, url)
            row = i + 1

            if data and data.get('Name') == "No Profile":
                ws.update(range_name=f"B{row}:G{row}", values=[[
                    "No Profile", "", "", "", "", "NOT_FOUND"
                ]])
                print(f"   ⚠️ Dòng {row}: Profile không tồn tại (NOT_FOUND)")

            elif data and data.get('Name') and data['Name'] not in ["No Profile", "This page isn’t working"]:
                payload = [
                    data['Name'],
                    data['Headline'],
                    data['Locality'],
                    data['Connections'],
                    data['Company'],
                    "Success"
                ]
                ws.update(range_name=f"B{row}:G{row}", values=[payload])
                print(f"   ✅ Dòng {row} OK: {data['Name']}")

            else:
                error_msg = f"Error: {status}"
                ws.update(range_name=f"B{row}:G{row}", values=[[
                    "", "", "", "", "", error_msg
                ]])
                print(f"   ❌ Dòng {row}: {error_msg}")

                if status in ["AUTH_WALL", "REDIRECT_LOOP"]:
                    print("🛑 Dừng tiến trình do gặp Auth Wall / Redirect Loop!")
                    break

            count += 1
            if count >= MAX_PROFILE:
                print(f"🛑 Đã hoàn thành batch {MAX_PROFILE} profiles.")
                break

            time.sleep(random.randint(3, 6))

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
    print("✅ Done!")
