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
LINKEDIN_COOKIES_B64 = os.getenv('LINKEDIN_COOKIES_B64', '')

COOKIES_FILE = 'linkedin_cookies.pkl'
CREDENTIALS_FILE = 'linkedin_credentials.pkl'

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
    driver.set_page_load_timeout(30)
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
# 3. LOGIN (CHỐNG LỖI SUBMIT BUTTON & CHUẨN CLOUD)
# ==========================================
def login_linkedin(driver):
    print("INFO: Đang truy cập LinkedIn...")
    driver.get("https://www.linkedin.com/login")
    time.sleep(3)

    # 1. Khôi phục Cookie từ Secret (nếu được cung cấp)
    if LINKEDIN_COOKIES_B64:
        print("INFO: Đang thử đăng nhập bằng Cookie từ GitHub Secret...")
        try:
            cookies_json = base64.b64decode(LINKEDIN_COOKIES_B64).decode('utf-8')
            cookies = json.loads(cookies_json)
            for cookie in cookies:
                cookie.pop('sameSite', None)
                try:
                    driver.add_cookie(cookie)
                except Exception:
                    pass
            driver.get("https://www.linkedin.com/feed")
            time.sleep(4)
            if "feed" in driver.current_url or driver.find_elements(By.CLASS_NAME, 'global-nav__me-photo'):
                print("INFO: Đăng nhập thành công bằng Cookie Secret!")
                return True
        except Exception as e:
            print(f"⚠️ Lỗi khi nạp Cookie từ Secret: {e}")

    # 2. Thử đăng nhập bằng Cookies file cũ (nếu có lưu cache)
    if os.path.exists(COOKIES_FILE):
        print("INFO: Đang thử đăng nhập bằng Cookies file cache...")
        try:
            with open(COOKIES_FILE, "rb") as f:
                cookies = pickle.load(f)
                for cookie in cookies:
                    try: driver.add_cookie(cookie)
                    except: pass

            driver.get("https://www.linkedin.com/feed")
            time.sleep(4)

            if "feed" in driver.current_url or driver.find_elements(By.CLASS_NAME, 'global-nav__me-photo'):
                print("INFO: Đăng nhập thành công bằng Cookies cache!")
                return True
            else:
                print("⚠️ Cookies hỏng hoặc hết hạn. Tiến hành đăng nhập lại...")
                driver.delete_all_cookies()
        except Exception as e:
            print(f"⚠️ Lỗi đọc Cookies file: {e}")
            driver.delete_all_cookies()

    # 3. Mở lại trang Login nếu chưa logged in
    print("INFO: Mở lại trang đăng nhập để điền Credentials...")
    driver.get("https://www.linkedin.com/login")
    time.sleep(3)

    try:
        # Bỏ qua Cookie Banner nếu đè màn hình
        try:
            cookie_btn = driver.find_element(By.XPATH, "//button[contains(@data-tracking-control-name, 'cookie') or contains(text(), 'Accept') or contains(text(), 'Accepteren')]")
            driver.execute_script("arguments[0].click();", cookie_btn)
            time.sleep(1)
        except Exception:
            pass

        # Tìm ô Username đang HIỂN THỊ
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
                el = WebDriverWait(driver, 2).until(
                    EC.visibility_of_element_located((by, sel))
                )
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
            print("❌ Không tìm thấy ô nhập Email hiển thị.")
            driver.save_screenshot("no_visible_input.png")
            return False

        # Điền Username
        driver.execute_script("arguments[0].scrollIntoView(true);", username_element)
        try:
            username_element.clear()
            username_element.send_keys(USERNAME)
        except Exception:
            driver.execute_script("arguments[0].value = arguments[1];", username_element, USERNAME)

        # Tìm ô Password đang HIỂN THỊ
        password_element = None
        pass_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
        for p_in in pass_inputs:
            if p_in.is_displayed():
                password_element = p_in
                break

        if not password_element:
            print("❌ Không tìm thấy ô Password hiển thị.")
            return False

        # Điền Password
        driver.execute_script("arguments[0].scrollIntoView(true);", password_element)
        try:
            password_element.clear()
            password_element.send_keys(PASSWORD)
        except Exception:
            driver.execute_script("arguments[0].value = arguments[1];", password_element, PASSWORD)

        time.sleep(1)

        # 4. GỬI FORM ĐĂNG NHẬP (Phím ENTER -> Nút bấm -> JS Submit)
        submitted = False
        try:
            print("INFO: Đang gửi Form bằng phím ENTER...")
            password_element.send_keys(Keys.ENTER)
            submitted = True
        except Exception as e:
            print(f"⚠️ Không gửi được bằng phím ENTER: {e}")

        if not submitted:
            submit_selectors = [
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.CSS_SELECTOR, "button[data-id='sign-in-form__submit-btn']"),
                (By.XPATH, "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'aanmelden') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'sign in')]"),
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
            print("INFO: Dùng JavaScript submit form trực tiếp...")
            driver.execute_script("arguments[0].form.submit();", password_element)

        time.sleep(6)

        # Kiểm tra nếu gặp Checkpoint/OTP/Authwall
        if any(x in driver.current_url for x in ["checkpoint", "challenge", "authwall"]):
            print("🛑 CẢNH BÁO: LinkedIn yêu cầu mã xác thực OTP hoặc Captcha!")
            print("💡 Hãy trích xuất Cookie từ trình duyệt và lưu vào Secret LINKEDIN_COOKIES_B64.")
            driver.save_screenshot("authwall_checkpoint.png")
            return False

        # 5. Kiểm tra trạng thái Đăng nhập thành công
        if "feed" in driver.current_url or driver.find_elements(By.CLASS_NAME, 'global-nav__me-photo'):
            with open(COOKIES_FILE, "wb") as f:
                pickle.dump(driver.get_cookies(), f)
            with open(CREDENTIALS_FILE, "wb") as f:
                pickle.dump({"username": USERNAME, "password": PASSWORD}, f)
            print("INFO: Đăng nhập thành công và đã cập nhật Cookies mới!")
            return True
        else:
            print(f"ERROR: Đăng nhập chưa tới trang Feed. URL hiện tại: {driver.current_url}")
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

        if "This page doesn’t exist" in page_source or "Page not found" in driver.title:
            print("⚠️ Cảnh báo: Hồ sơ không tồn tại (404).")
            return {
                "Name": "No Profile",
                "Title": "",
                "Location": "",
                "Connection": "",
                "Company": ""
            }, "NOT_FOUND"

        # Cuộn trang để nạp dữ liệu
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

            const lines = Array.from(document.querySelectorAll('p'))
                .map(el => el.innerText.trim())
                .filter(t => t.length > 0);

            const title = lines.find(t => t.includes(" at ") || t.length > 20) || "";
            let loc = "";

            const contactAnchor = document.querySelector('a[href*="contact-info"]');
            if (contactAnchor) {
                const parentText = contactAnchor.closest('div')?.innerText || "";
                loc = parentText.split('·')[0].replace('Contact info', '').trim();
            }

            return {
                name: txt('h1.text-heading-xlarge') || txt('div[data-display-contents="true"] h2') || txt('h2') || "",
                title,
                location: loc || txt('span.text-body-small.inline.t-black--light.break-words') || txt('span[class*="location"]') || "",
                company_list: sideBarElements.slice(0, 2).join(" | ") || "",
                connection_raw: document.body.innerText
            };
        """)

        name = data_js.get('name', '')
        title = data_js.get('title', '')
        location = data_js.get('location', '')
        company = data_js.get('company_list', '')
        conn_source = data_js.get('connection_raw', '')

        print(f"Debug: Extracted Name: {name}")
        print(f"Debug: Extracted Companies: {company}")

        connection = ""
        match = re.search(r'([\d,\.\+]+)\s*(connections|kết nối|followers|người theo dõi)', conn_source, re.I)
        if match:
            number = match.group(1)
            connection = f"{number} connections"

        print(f"Debug: Stats - Title: {len(title)} chars, Loc: {len(location)} chars, Comp: {len(company)} chars")

        return {
            "Name": name,
            "Title": title,
            "Location": location,
            "Connection": connection,
            "Company": company
        }, "Success"

    except Exception as e:
        print(f"Debug: Error at {url} - {str(e)}")
        return None, str(e)

# ==========================================
# 5. MAIN WORKFLOW
# ==========================================
def main():
    MAX_PROFILE = int(os.getenv('MAX_PROFILE', '20'))
    count = 0

    sh = connect_google_sheet()
    if not sh:
        print("❌ Không thể kết nối Google Sheet!")
        return

    ws = sh.worksheet(INPUT_TAB_NAME)
    all_rows = ws.get_all_values()

    driver = setup_driver()
    try:
        if not login_linkedin(driver):
            return

        for i in range(1, len(all_rows)):
            row_data = all_rows[i]
            url = row_data[0].strip() if len(row_data) > 0 else ""

            # 1. Kiểm tra URL
            if not url or "linkedin.com/in/" not in url:
                print(f"⏩ Dòng {i+1}: Bỏ qua do URL trống hoặc không hợp lệ.")
                continue

            # 2. Kiểm tra Cột G (Status index 6)
            if len(row_data) >= 7:
                status_existing = row_data[6]
                if status_existing in ["Success", "NOT_FOUND", "No Profile"]:
                    print(f"⏭️ Dòng {i+1}: Đã có dữ liệu ({status_existing}), bỏ qua.")
                    continue

            print(f"🔄 Đang xử lý dòng {i+1}: {url}")
            data, status = crawl_profile(driver, url)
            row = i + 1

            if data and data.get('Name') == "No Profile":
                ws.update(range_name=f"B{row}:G{row}", values=[[
                    "No Profile", "", "", "", "", "NOT_FOUND"
                ]])
                print("   ⚠️ Profile không tồn tại (NOT_FOUND)")

            elif data and data.get('Name') and data['Name'] != "No Profile":
                ws.update(range_name=f"B{row}:G{row}", values=[[
                    data['Name'],
                    data['Title'],
                    data['Location'],
                    data['Connection'],
                    data['Company'],
                    "Success"
                ]])
                print(f"   ✅ OK: {data['Name']}")

            else:
                error_msg = f"Error: {status}"
                ws.update(range_name=f"B{row}:G{row}", values=[[
                    "", "", "", "", "", error_msg
                ]])
                print(f"   ❌ {error_msg}")

                if status == "AUTH_WALL":
                    print("🛑 Dừng tiến trình do gặp Auth Wall!")
                    break

            count += 1
            if count >= MAX_PROFILE:
                print(f"🛑 Đã đạt giới hạn batch {MAX_PROFILE} profiles.")
                break

            time.sleep(random.randint(3, 6))

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
    print("✅ Done!")
