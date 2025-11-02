# test_crawler.py
# 一個獨立的 Python 腳本，僅用於測試課程人數爬蟲功能。

import requests
from bs4 import BeautifulSoup
import logging
from typing import Optional, Dict
import re
import urllib3 # 用於忽略 SSL 警告

# --- 爬蟲基礎設定與安全性 ---
# 禁用 requests 呼叫 verify=False 時產生的警告 (解決 [SSL: CERTIFICATE_VERIFY_FAILED] 錯誤)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning) 

# 設定 logging，確保在終端機輸出錯誤和資訊
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# --- 網站 URL ---
TARGET_URL = "https://webapp.yuntech.edu.tw/WebNewCAS/Course/QueryCour.aspx" 


# =========================================================
# ✅ 核心功能 1/2：動態獲取 ASP.NET 狀態密鑰 (__VIEWSTATE 等)
# =========================================================
def _fetch_state_keys() -> Optional[Dict[str, str]]:
    """
    執行 GET 請求到初始查詢頁面，從 HTML 中提取動態的狀態密鑰。
    這是為了模擬使用者第一次載入頁面。
    """
    GET_URL = TARGET_URL
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # ⚠️ 必須使用 verify=False 忽略 SSL 錯誤
        response = requests.get(GET_URL, headers=headers, timeout=10, verify=False)
        response.raise_for_status() 
        soup = BeautifulSoup(response.text, 'html.parser')
        
        keys = {}
        
        # 遍歷所有隱藏的輸入欄位，提取其名稱和值
        for input_tag in soup.find_all('input', type='hidden'):
            if input_tag.get('name') and input_tag.get('value'):
                keys[input_tag['name']] = input_tag['value']
        
        # 確保關鍵密鑰存在
        if '__VIEWSTATE' in keys and '__EVENTVALIDATION' in keys:
            
            # 輔助密鑰：ToolkitScriptManager (這裡使用固定值，因為它較少變動)
            toolkit_key = keys.get('ctl00$MainContent$ToolkitScriptManager1$HiddenField', ';;AjaxControlToolkit, Version=4.1.60919.0, Culture=neutral, PublicKeyToken=28f01b0e84b6d53e:zh-TW:ab75ae50-1505-49da-acca-8b96b908cb1a:475a4ef5:effe2a26:7e63a579:5546a2b:d2e10b12:37e2e5c9:1d3ed089:751cdd15:dfad98a5:497ef277:a43b07eb:3cf12cf1')

            return {
                'ToolkitScriptManager': toolkit_key,
                'VIEWSTATE': keys['__VIEWSTATE'],
                'VIEWSTATEGENERATOR': keys.get('__VIEWSTATEGENERATOR', ''),
                'EVENTVALIDATION': keys['__EVENTVALIDATION'],
            }

    except Exception as e:
        logging.error(f"無法從初始頁面獲取狀態密鑰: {e}")
        return None
        
    return None


# =========================================================
# ✅ 核心功能 2/2：執行查詢並解析人數 (整合所有修正)
# =========================================================
def _get_current_enrollment(course_id: str, acad_seme: str) -> Optional[Dict[str, int]]:
    """
    執行爬蟲並獲取指定課號和學期碼的 (當前人數, 限制人數)。
    """
    
    # 1. 獲取動態密鑰 (GET Request)
    state_keys = _fetch_state_keys()
    if not state_keys:
        return None

    # 2. 構造 POST 請求的 Payload
    payload = {
        # --- 動態獲取的 ASP.NET 狀態變數 ---
        'ctl00_MainContent_ToolkitScriptManager1$HiddenField': state_keys['ToolkitScriptManager'],
        '__LASTFOCUS': '',
        '__EVENTTARGET': '',
        '__EVENTARGUMENT': '',
        '__VIEWSTATE': state_keys['VIEWSTATE'],
        '__VIEWSTATEGENERATOR': state_keys['VIEWSTATEGENERATOR'],
        '__VIEWSTATEENCRYPTED': '',
        '__EVENTVALIDATION': state_keys['EVENTVALIDATION'],
        
        # --- 使用者輸入欄位 ---
        'ctl00$MainContent$AcadSeme': acad_seme, # 使用傳入的學期碼
        'ctl00$MainContent$College': '',
        'ctl00$MainContent$DeptCode': '',
        'ctl00$MainContent$CurrentSubj': course_id, # 傳入要查詢的課號
        'ctl00$MainContent$TextBoxWatermarkExtender3_ClientState': '',
        'ctl00$MainContent$SubjName': '',
        'ctl00$MainContent$TextBoxWatermarkExtender1_ClientState': '',
        'ctl00$MainContent$Instructor': '',
        'ctl00$MainContent$TextBoxWatermarkExtender2_ClientState': '',
        'ctl00$MainContent$Submit': '執行查詢',
    }

    # 3. Headers 資訊
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': TARGET_URL
    }

    try:
        # 4. 執行 POST 請求 (忽略 SSL 憑證驗證)
        response = requests.post(TARGET_URL, data=payload, headers=headers, timeout=15, verify=False)
        response.raise_for_status() 
        
        # 5. HTML 解析
        soup = BeautifulSoup(response.text, 'html.parser')

        # 6. 尋找結果表格 (使用正確的 ID: ctl00_MainContent_Course_GridView)
        course_table = soup.find('table', id='ctl00_MainContent_Course_GridView') 
        if not course_table:
             logging.error(f"課號 {course_id} 爬蟲失敗：找不到結果表格 ID。")
             return None

        # 7. 尋找包含課號的資料行 (跳過第一行表頭)
        rows = course_table.find_all('tr')
        data_row = None
        
        for row in rows[1:]: 
            cells = row.find_all('td')
            
            # 課號 (學期課號) 在第一個 td 儲存格 (索引 0)
            if len(cells) > 0:
                 course_id_in_table = cells[0].text.strip()
                 course_id_in_table = re.sub(r'\s+', '', course_id_in_table) # 移除空白/換行
                 
                 if course_id_in_table == course_id: 
                     data_row = row
                     break

        if not data_row:
            logging.warning(f"課號 {course_id} 在學期 {acad_seme} 的查詢結果中未找到該行數據。")
            return None

        # 8. 提取人數數據 (修課人數 Sel. 和 限制人數 Max)
        cells = data_row.find_all('td')
        
        # 根據您的 HTML：
        # cells[9] 是 "修課人數 (Sel.)"
        # cells[10] 是 "人數限制 (Max)"
        
        if len(cells) > 10: 
            try:
                # 獲取當前人數
                current_count_text = cells[9].text.strip()
                current_count = int(current_count_text)
                
                # 獲取限制人數 (格式為 "限<br>80人" 或空白)
                max_count_text = cells[10].text.strip()
                max_match = re.search(r'(\d+)', max_count_text) 
                
                max_count = 999 # 預設為 999 (如果找不到限制)
                if max_match:
                    max_count = int(max_match.group(1))
                elif "限" not in max_count_text:
                    # 如果欄位是空的 (沒有 "限" 字)，也視為無限制
                    max_count = 999 

                return {'current': current_count, 'max': max_count}
            
            except Exception as e:
                logging.warning(f"課號 {course_id} 找到行但解析人數時出錯: {e}")
                return None
        else:
            logging.warning(f"課號 {course_id} 的表格行欄位數量不足 (只有 {len(cells)} 欄)。")
            return None

    except requests.exceptions.RequestException as e:
        logging.error(f"爬蟲請求失敗: {e}")
        return None

# =========================================================
# 🏁 測試區塊 (直接在 Venv 中運行此檔案)
# =========================================================
if __name__ == "__main__":
    
    # --- ⚠️ 請修改這裡的測試參數 ---
    # demo = input("請輸入測試參數 (格式: 課號,學期碼，例如 GO,1121): ")
    # TEST_COURSE_ID, TEST_ACAD_SEME = demo.split(",")

    TEST_COURSE_ID = input("請輸入測試課號 (例如 GO): ").strip() or "GO"
    # --------------------------------- 
    TEST_ACAD_SEME = input("請輸入測試學期 (例如 1121): ").strip() or "1121"

    logging.info(f"--- 開始測試課程人數爬蟲功能 (課號: {TEST_COURSE_ID}, 學期: {TEST_ACAD_SEME}) ---")
    
    # 執行爬蟲
    result = _get_current_enrollment(TEST_COURSE_ID, TEST_ACAD_SEME)
    
    if result:
        logging.info(f"✅ 測試成功：")
        logging.info(f"   > 當前人數 (Sel.): {result['current']}")
        logging.info(f"   > 限制人數 (Max): {result['max']}")
        if result['current'] < result['max']:
            logging.info(f"   > 狀態: 🟢 有空位")
        else:
            logging.info(f"   > 狀態: 🔴 已額滿")
    else:
        logging.error(f"❌ 測試失敗：無法獲取課號 {TEST_COURSE_ID} 的人數。請查看上方日誌尋找錯誤原因。")