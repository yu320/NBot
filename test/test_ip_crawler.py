import requests
from bs4 import BeautifulSoup
import logging
import sys
import json
import requests.packages.urllib3
import os
import re 

# 【新增：用於忽略 InsecureRequestWarning 警告】
os.environ['PYTHONWARNINGS'] = 'ignore:UnrewindableBodyWarning:urllib3.exceptions' 
requests.packages.urllib3.disable_warnings() 

# --- 【配置區：請修改這些變數】 ---
URL = "https://netflow.yuntech.edu.tw/netflow.pl"
TARGET_IP = "140.125.203.233" 
TARGET_YEAR = "2025"
TARGET_MONTH = "11"
TARGET_DAY = "02"
# 限制提取的數據筆數 (日期/天數)
DATA_LIMIT = 5
# 日誌檔案名稱
LOG_FILE_NAME = "crawler_results_all.log"
# --- ------------ ---

# 【設置日誌記錄】
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE_NAME, mode='a', encoding='utf-8') 
    ]
)
logger = logging.getLogger(__name__)

logger.info("==========================================================")
logger.info(f"爬蟲腳本啟動 @ {os.path.basename(sys.argv[0])}")
logger.info(f"結果將寫入檔案: {LOG_FILE_NAME}")
logger.info("==========================================================")


def get_specific_ip_traffic(url, target_ip, year, month, day, limit):
    
    logger.info(f"--- 開始 IP 歷史數據提取作業 ---")
    logger.info(f"查詢 IP: {target_ip}，基準日期: {year}-{month}-{day}")
    logger.info(f"*** 限制提取：前 {limit} 個日期 ***")
    
    PAYLOAD = {
        'action': 'ShowIP', 'IP': target_ip, 'year': year,           
        'month': month, 'day': day, 'submit': '查詢'        
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.88 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded' 
    }
    
    all_data = []
    page_update_time = "N/A"
    update_time_pattern = re.compile(r"Current Time: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
    
    try:
        # 1. 發送 POST 請求 (增加超時時間至 60 秒)
        logger.info(f"正在發送 POST 請求，Payload: {PAYLOAD}")
        
        response = requests.post(url, data=PAYLOAD, headers=headers, timeout=60, verify=False) 
        response.raise_for_status()

        logger.info(f"HTTP 請求成功，狀態碼: {response.status_code}")

        # 2. 解析 HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        logger.info("正在嘗試定位歷史流量表格...")

        table = soup.find('table', {'width': '95%'}) 
        if not table:
            table = soup.find('table')
        
        if not table:
            # 即使找不到表格，也嘗試找頁面時間
            update_time_match = re.search(r"Current Time: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", soup.get_text())
            if update_time_match:
                page_update_time = update_time_match.group(1)
            logger.error(f"錯誤：找不到網頁表格。")
            return {"Page_UpdateTime": page_update_time, "Data": "錯誤：找不到網頁表格。"}

        logger.info("已找到表格。開始遍歷數據行...")
        
        # 3. 遍歷表格的資料行
        data_rows = table.find_all('tr')
        data_rows_content = data_rows[1:] if len(data_rows) > 0 else [] 
        
        COLUMNS = [
            'Year', 'Month', 'Day', '校外Send', '校外Receive', 
            '校內Send', '校內Receive', 'Total', 'UL/DL'
        ]
        
        # 核心邏輯：限制提取筆數
        count = 0
        for i, row in enumerate(data_rows_content):
            cells = row.find_all('td')
            
            # --- 數據行提取邏輯 ---
            if len(cells) >= 9:
                if count < limit: # 確保只提取前 DATA_LIMIT 筆數據
                    row_data = {}
                    for j in range(9):
                        value = cells[j].get_text(strip=True).replace('\xa0', '')
                        row_data[COLUMNS[j]] = value
                    
                    all_data.append(row_data)
                    count += 1
                    logger.info(f"   [第 {count} 筆] 提取成功，Total: {row_data.get('Total', 'N/A')}")
                
            # --- 時間戳搜索邏輯 ---
            if page_update_time == "N/A":
                # 遍歷這一行的所有單元格，查找時間戳
                for cell in cells:
                    cell_text = cell.get_text(strip=True)
                    update_time_match = update_time_pattern.search(cell_text)
                    if update_time_match:
                        page_update_time = update_time_match.group(1)
                        logger.info(f"✅ 頁面當前時間已獲取 (來自表格單元格): {page_update_time}")
                        break 
            
            # 優化：如果數據抓滿且時間戳已找到，則跳出外層行循環
            if count >= limit and page_update_time != "N/A":
                break
        
        # 4. 如果時間戳還沒找到，在整個 HTML 中查找（作為最終備用方案）
        if page_update_time == "N/A":
            update_time_match = re.search(r"Current Time: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", soup.get_text())
            if update_time_match:
                page_update_time = update_time_match.group(1)
                logger.info(f"✅ 頁面當前時間已獲取 (全頁查找備用): {page_update_time}")
            
        # 5. 返回提取的數據
        final_result = {"Page_UpdateTime": page_update_time, "Data": all_data}
        
        if all_data:
            logger.info(f"✔️ 總共成功提取 {len(all_data)} 條數據。")
        else:
            logger.warning("❌ 未提取到任何數據。")
            
        return final_result

    except Exception as e:
        logger.error(f"發生錯誤: {e}", exc_info=True)
        return f"發生錯誤: {e}"
    finally:
        logger.info("--- 查詢作業結束 ---")

# 執行函式
history_data_result = get_specific_ip_traffic(URL, TARGET_IP, TARGET_YEAR, TARGET_MONTH, TARGET_DAY, limit=DATA_LIMIT)

# === 將最終結果寫入 LOG 的部分 ===
logger.info("\n========== 最終提取結果 (Start) ==========")

if isinstance(history_data_result, dict) and "Data" in history_data_result:
    data_list = history_data_result["Data"]
    page_time = history_data_result["Page_UpdateTime"]
    
    logger.info(f"網頁時間: {page_time}")
    logger.info(f"查詢 IP: {TARGET_IP} 的歷史數據 (僅前 {DATA_LIMIT} 筆):")
    
    json_output = json.dumps(history_data_result, indent=4, ensure_ascii=False)
    logger.info(f"--- 完整結果 JSON --- \n{json_output}")

    # 格式化輸出到 LOG 和控制台
    output_message = "\n--- 簡潔列表 ---\n"
    output_message += f"網頁時間: {page_time}\n"
    output_message += f"歷年流量查詢: {TARGET_IP}\n"

    # 查找基準日期的 Total
    specified_date_str = f"{TARGET_YEAR}-{TARGET_MONTH.zfill(2)}-{TARGET_DAY.zfill(2)}"
    specified_data = next((item for item in data_list if item.get('Year') == TARGET_YEAR and item.get('Month') == TARGET_MONTH and item.get('Day') == TARGET_DAY), None)
    specified_date_total = specified_data.get('Total', 'N/A') if specified_data else 'N/A'
    
    output_message += f"當日指定 ({specified_date_str}) 的 Total: {specified_date_total} Giga Byte(s)\n"
    output_message += "\n--- 提取的歷史數據 (前 {} 筆) ---\n".format(DATA_LIMIT)
    
    for i, data in enumerate(data_list):
        date = f"{data['Year']}-{data['Month'].zfill(2)}-{data['Day'].zfill(2)}"
        total = data['Total']
        output_message += f"{i+1}. 日期: {date} -> Total: {total} Giga Byte(s)\n"
    
    logger.info(output_message) # 寫入 LOG

elif isinstance(history_data_result, str):
    error_message = f"❌ 程式運行失敗，錯誤訊息: {history_data_result}"
    logger.error(error_message)
    output_message = error_message
    
logger.info("========== 最終提取結果 (End) ==========\n")

# print 到控制台
print(output_message)
print(f"程式執行完成。請查看檔案：{LOG_FILE_NAME}")