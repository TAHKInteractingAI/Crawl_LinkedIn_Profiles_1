import os
import time
import random
import gspread
import re
import json
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
LINKEDIN_LI_AT = os.getenv('LINKEDIN_LI_AT', '').strip()

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
# 3. ĐĂNG NHẬP LINKEDIN (ƯU TIÊN LI_AT)
# ==========================================
def login_linkedin(driver):
    print("INFO: Đang truy cập LinkedIn...")

    # Ưu tiên đăng nhập bằng Cookie li_at từ Secret
    if LINKEDIN_LI_AT:
        print("INFO: Đang nạp Cookie 'li_at' từ GitHub Secret...")
        try:
            driver.get("https://www.linkedin.com/404")
            time.sleep(2)
            driver.add_cookie({
                'name': 'li_at',
                'value': LINKEDIN_LI_AT,
                'domain': '.linkedin.com',
                'path': '/',
                'secure': True,
                'httpOnly': True
            })
            driver.get("https://www.linkedin.com/feed/")
            time.sleep(5)

            if "feed" in driver.current_url or driver.find_elements(By.CLASS_NAME, 'global-nav__me-photo'):
                print("✅ Đăng nhập thành công với Secret 'li_at'!")
                return True
            else:
                print("⚠️ Cookie 'li_at' đã hết hạn hoặc không đúng giá trị.")
        except Exception as e:
            print(f"⚠️ Lỗi khi nạp li_at: {e}")

    # Fallback thử đăng nhập bằng Mật khẩu
    print("INFO: Đang thử đăng nhập bằng Username/Password...")
    driver.get("https://www.linkedin.com/login")
    time.sleep(3)

    try:
        try:
            cookie_btn = driver.find_element(By.XPATH, "//button[contains(@data-tracking-control-name, 'cookie') or contains(text(), 'Accept') or contains(text(), 'Accepteren')]")
            driver.execute_script("arguments[0].click();", cookie_btn)
            time.sleep(1)
        except Exception:
            pass

        user_input = WebDriverWait(driver, 5).until(EC.visibility_of_element_located((By.ID, "username")))
        user_input.clear()
        user_input.send_keys(USERNAME)

        pass_input = driver.find_element(By.ID, "password")
        pass_input.clear()
        pass_input.send_keys(PASSWORD)
        time.sleep(1)

        pass_input.send_keys(Keys.ENTER)
        time.sleep(6)

        if "feed" in driver.current_url or driver.find_elements(By.CLASS_NAME, 'global-nav__me-photo'):
            print("✅ Đăng nhập thành công bằng tài khoản và mật khẩu!")
            return True
        else:
            print(f"🛑 CẢNH BÁO: LinkedIn yêu cầu OTP/Captcha tại {driver.current_url}")
            driver.save_screenshot("authwall_checkpoint.png")
            return False

    except Exception as e:
        print(f"ERROR: Lỗi đăng nhập: {e}")
        driver.save_screenshot("login_error.png")
        return False

# ==========================================
# 4. CRAWL DỮ LIỆU TỪ LINK PROFILE LINKEDIN
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
                "Headline": "",
                "Locality": "",
                "Connections": "",
                "Company": ""
            }, "NOT_FOUND"

        # Cuộn trang để tải DOM đầy đủ
        for _ in range(3):
            driver.execute_script("window.scrollBy(0, 500);")
            time.sleep(1)

        if any(x in driver.current_url for x in ["login", "authwall", "checkpoint", "challenge"]):
            print("Debug: Auth wall / Checkpoint detected.")
            driver.save_screenshot(f"authwall_{int(time.time())}.png")
            return None, "AUTH_WALL"

        data_js = driver.execute_script("""
            const txt = (sel) => document.querySelector(sel)?.innerText.trim() || "";

            // 1. Name
            let name = txt('h1.text-heading-xlarge') || 
                       txt('h1.top-card-layout__title') ||
                       txt('div.ph5 h1') ||
                       txt('section.top-card h1') ||
                       txt('h1') || "";

            // 2. Headline
            const lines = Array.from(document.querySelectorAll('p, div.text-body-medium'))
                .map(el => el.innerText.trim())
                .filter(t => t.length > 0);

            let headline = txt('div.text-body-medium.break-words') ||
                           txt('h2.top-card-layout__headline') ||
                           lines.find(t => t.includes(" at ") || (t.length > 15 && t.length < 150)) || "";

            // 3. Locality
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

            // 4. Company sau update
            const sideBarElements = Array.from(document.querySelectorAll('div[role="button"], ul.overflow-hidden li, button[aria-label*="Current company"]'))
                .map(el => el.innerText.trim())
                .filter(t => t.length > 2 && !t.toLowerCase().includes('connection') && !t.toLowerCase().includes('follower') && !t.toLowerCase().includes('kết nối'));

            let company = sideBarElements.slice(0, 2).join(" | ") || "";

            return {
                name: name,
                headline: headline,
                locality: loc,
                company: company,
                page_title: document.title || "",
                connection_raw: document.body.innerText
            };
        """)

        name = data_js.get('name', '').strip()
        headline = data_js.get('headline', '').strip()
        locality = data_js.get('locality', '').strip()
        company = data_js.get('company', '').strip()
        page_title = data_js.get('page_title', '').strip()
        conn_source = data_js.get('connection_raw', '')

        # Fallback tên nếu DOM thay đổi
        if not name and page_title and "linkedin" in page_title.lower():
            clean_p_title = page_title.split("|")[0].split(" - ")[0].split(" – ")[0].replace("Profile", "").strip()
            if clean_p_title and len(clean_p_title) < 50:
                name = clean_p_title

        if not name:
            slug = url.rstrip("/").split("/")[-1].split("?")[0]
            if slug:
                name = " ".join([word.capitalize() for word in slug.replace("-", " ").split() if not word.isdigit()])

        # Fallback công ty từ Headline
        if not company and " at " in headline:
            company = headline.split(" at ")[-1].split("|")[0].split("•")[0].strip()
        elif not company and " @ " in headline:
            company = headline.split(" @ ")[-1].split("|")[0].split("•")[0].strip()

        # Connection
        connections = ""
        match = re.search(r'([\d,\.\+]+)\s*(connections|kết nối|followers|người theo dõi)', conn_source, re.I)
        if match:
            connections = f"{match.group(1)} connections"

        print(f"Debug: [Name: '{name}'] | [Headline: '{headline}'] | [Loc: '{locality}'] | [Conn: '{connections}'] | [Comp: '{company}']")

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

        # Quét qua từng dòng từ hàng 2 (index 1)
        for i in range(1, len(all_rows)):
            row_data = all_rows[i]
            url = row_data[0].strip() if len(row_data) > 0 else ""

            # 1. Bỏ qua nếu cột A không phải là link LinkedIn
            if not url or "linkedin.com/in/" not in url:
                continue

            # 2. KIỂM TRA: Chỉ chạy nếu CỘT B TRỐNG hoặc CỘT G (Status) CHƯA CÓ SUCCESS / NOT_FOUND
            name_existing = row_data[1].strip() if len(row_data) > 1 else ""
            status_existing = row_data[6].strip() if len(row_data) > 6 else ""

            if name_existing or status_existing in ["Success", "NOT_FOUND", "No Profile"]:
                continue

            print(f"\n🔄 Đang xử lý dòng {i+1}: {url}")
            data, status = crawl_profile(driver, url)
            row = i + 1

            if data and data.get('Name') == "No Profile":
                # Cột B:G khi không tìm thấy Profile
                ws.update(range_name=f"B{row}:G{row}", values=[[
                    "No Profile", "", "", "", "", "NOT_FOUND"
                ]])
                print(f"   ⚠️ Dòng {row}: Profile không tồn tại (NOT_FOUND)")

            elif data and status == "Success":
                # Ghi đúng 6 cột: B(Name), C(Headline), D(Locality), E(Connections), F(Company sau update), G(Status)
                payload = [
                    data['Name'],
                    data['Headline'],
                    data['Locality'],
                    data['Connections'],
                    data['Company'],
                    "Success"
                ]
                ws.update(range_name=f"B{row}:G{row}", values=[payload])
                print(f"   ✅ Dòng {row} OK: {data['Name']} | {data['Headline']}")

            else:
                error_msg = f"Error: {status}"
                ws.update(range_name=f"B{row}:G{row}", values=[[
                    "", "", "", "", "", error_msg
                ]])
                print(f"   ❌ Dòng {row}: {error_msg}")

                if status == "AUTH_WALL":
                    print("🛑 Dừng tiến trình do gặp Auth Wall!")
                    break

            count += 1
            if count >= MAX_PROFILE:
                print(f"🛑 Đã hoàn thành batch {MAX_PROFILE} profiles cho lần chạy này.")
                break

            time.sleep(random.randint(3, 6))

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
    print("✅ Done!")
