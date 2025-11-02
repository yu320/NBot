import discord
from discord.ext import commands, tasks
from core.classes import Cog_Extension 
import json
import os
import asyncio
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional
import logging
import re 
from datetime import datetime
import requests.packages.urllib3

# --- 設定常量 ---
IP_MONITOR_FILE = './data/ip_monitor_list.json' # 儲存 IP 監測任務的檔案路徑
CHECK_INTERVAL_MINUTES = 10                  # 檢查間隔 (10 分鐘)
CRAWL_DELAY_SECONDS = 30                     # 每筆 IP 查詢之間的延遲 (慢慢爬)
TRAFFIC_THRESHOLD_GB = 10.0                  # 流量警告閾值 (10 GB)

# 讀取 IP 通知的頻道 ID
IP_MONITOR_CHANNEL_ID_STR = os.getenv('IP_MONITOR_CHANNEL_ID') 

# 爬蟲目標 URL
URL = "https://netflow.yuntech.edu.tw/netflow.pl"

# 禁用 SSL 警告 (來自您的腳本)
requests.packages.urllib3.disable_warnings() 

# =========================================================
# ✅ 核心爬蟲邏輯 (從您的 test_ip_crawler.py 移植)
# =========================================================
def _fetch_ip_traffic(target_ip: str) -> Optional[Dict[str, Any]]:
    """
    執行爬蟲並獲取指定 IP **今天**的流量數據。
    返回 {'total_gb': float, 'update_time': str} 或 None
    """
    
    # 自動獲取今天的日期
    now = datetime.now()
    year, month, day = str(now.year), str(now.month), str(now.day)
    
    logging.info(f"開始 IP 數據提取 (IP: {target_ip}, Date: {year}-{month}-{day})")
    
    PAYLOAD = {
        'action': 'ShowIP', 'IP': target_ip, 'year': year,           
        'month': month, 'day': day, 'submit': '查詢'        
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.88 Safari/537.36',
        'Content-Type': 'application/x-www-form-urlencoded' 
    }
    
    page_update_time = "N/A"
    update_time_pattern = re.compile(r"Current Time: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
    
    try:
        # 1. 執行 POST 請求
        response = requests.post(URL, data=PAYLOAD, headers=headers, timeout=60, verify=False) 
        response.raise_for_status()
        logging.info(f"HTTP 請求成功 (IP: {target_ip})")

        # 2. 解析 HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        update_time_match = update_time_pattern.search(soup.get_text())
        if update_time_match:
            page_update_time = update_time_match.group(1)

        # 3. 定位表格
        table = soup.find('table', {'width': '95%'}) 
        if not table:
            table = soup.find('table')
        
        if not table:
            logging.error(f"錯誤 (IP: {target_ip})：找不到網頁表格。")
            return None

        # 4. 遍歷表格的資料行
        data_rows = table.find_all('tr')
        data_rows_content = data_rows[1:] if len(data_rows) > 0 else [] 
        
        # 尋找今天的數據
        for row in data_rows_content:
            cells = row.find_all('td')
            
            if len(cells) >= 9:
                row_year = cells[0].get_text(strip=True).replace('\xa0', '')
                row_month = cells[1].get_text(strip=True).replace('\xa0', '')
                row_day = cells[2].get_text(strip=True).replace('\xa0', '')
                
                # 檢查是否為今天的日期
                if row_year == year and row_month == month and row_day == day:
                    total_gb_str = cells[7].get_text(strip=True).replace('\xa0', '')
                    try:
                        total_gb_float = float(total_gb_str)
                        logging.info(f"✔️ (IP: {target_ip}) 提取成功, Total: {total_gb_float} GB")
                        return {'total_gb': total_gb_float, 'update_time': page_update_time}
                    except ValueError:
                        logging.warning(f"❌ (IP: {target_ip}) 找到行，但 Total 欄位不是數字: {total_gb_str}")
                        return None
        
        logging.warning(f"❌ (IP: {target_ip}) 找到了表格，但未找到今天的數據。")
        return None

    except Exception as e:
        logging.error(f"爬蟲 (IP: {target_ip}) 發生錯誤: {e}", exc_info=True)
        return None

# =========================================================

class IPMonitor(Cog_Extension):
    
    def __init__(self, bot):
        super().__init__(bot)
        
        # 驗證通知頻道 ID
        self.notification_channel_id = None
        if IP_MONITOR_CHANNEL_ID_STR and IP_MONITOR_CHANNEL_ID_STR.isdigit():
            self.notification_channel_id = int(IP_MONITOR_CHANNEL_ID_STR)
        else:
            logging.error("IP_MONITOR_CHANNEL_ID 未設定或格式錯誤，IP 監測通知將無法發送！")

        os.makedirs('./data', exist_ok=True)
        if not os.path.exists(IP_MONITOR_FILE):
            self._save_ip_list([])
            
        if self.notification_channel_id:
            self.check_ip_traffic.start()
            logging.info("IP Monitor task started.")
        else:
            logging.warning("IP Monitor task DID NOT start due to missing IP_MONITOR_CHANNEL_ID.")
            
    def cog_unload(self):
        self.check_ip_traffic.cancel()
        
    def _load_ip_list(self) -> List[Dict[str, Any]]:
        try:
            with open(IP_MONITOR_FILE, 'r', encoding='utf8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"載入 IP 監測清單失敗: {e}")
            return []

    def _save_ip_list(self, ip_list: List[Dict[str, Any]]):
        try:
            with open(IP_MONITOR_FILE, 'w', encoding='utf8') as f:
                json.dump(ip_list, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.error(f"儲存 IP 監測清單失敗: {e}")

    # =========================================================
    # ✅ 背景任務：每 10 分鐘檢查一次
    # =========================================================
    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def check_ip_traffic(self):
        await self.bot.wait_until_ready()
        
        ip_list = self._load_ip_list()
        list_changed = False 
        
        target_channel = self.bot.get_channel(self.notification_channel_id)
        if not target_channel:
            logging.error(f"找不到指定的 IP 通知頻道 ID: {self.notification_channel_id}，任務暫停。")
            return

        logging.info(f"開始執行 {len(ip_list)} 筆 IP 流量檢查...")

        for job in ip_list:
            ip = job['ip']
            last_status = job.get('last_status', "OK") # 預設為 "OK"
            
            # --- ✅ 執行爬蟲 ---
            status_data = await asyncio.to_thread(_fetch_ip_traffic, ip)
            
            if status_data is None:
                logging.warning(f"IP {ip} 爬蟲失敗或未找到數據。")
                continue
                
            current_traffic_gb = status_data['total_gb']
            page_update_time = status_data['update_time']
            
            # --- ✅ 判斷邏輯 ---
            new_status = "OVER_LIMIT" if current_traffic_gb > TRAFFIC_THRESHOLD_GB else "OK"
            
            # 如果狀態沒有改變，就跳過
            if new_status == last_status:
                continue
                
            # --- 狀態已改變，準備發送通知 ---
            list_changed = True
            job['last_status'] = new_status 
            
            if new_status == "OVER_LIMIT":
                # 從 OK -> OVER_LIMIT
                logging.warning(f"IP {ip} 流量超標！ ({current_traffic_gb} GB)")
                embed = discord.Embed(
                    title="🚨 IP 流量警告：流量超標",
                    description=f"監測的 IP **{ip}** 今日流量已達 **{current_traffic_gb} GB**，超過 **{TRAFFIC_THRESHOLD_GB} GB** 的限制！",
                    color=0xFF0000 # 紅色
                )
                embed.set_footer(text=f"頁面更新時間: {page_update_time}")
                await target_channel.send(embed=embed)
                
            else: # new_status == "OK"
                # 從 OVER_LIMIT -> OK
                logging.info(f"IP {ip} 流量已恢復正常 ({current_traffic_gb} GB)")
                embed = discord.Embed(
                    title="✅ IP 流量狀態：已恢復正常",
                    description=f"監測的 IP **{ip}** 今日流量已降至 **{current_traffic_gb} GB**。",
                    color=0x00FF00 # 綠色
                )
                embed.set_footer(text=f"頁面更新時間: {page_update_time}")
                await target_channel.send(embed=embed)

            # --- ✅ 慢慢爬 ---
            # 檢查完一筆後，休息 30 秒再查下一筆
            await asyncio.sleep(CRAWL_DELAY_SECONDS) 

        if list_changed:
            self._save_ip_list(ip_list)
        
        logging.info("IP 流量檢查完畢。")

    # =========================================================
    # ✅ 指令：設定監測任務
    # =========================================================
    @commands.group(name='ipmonitor', invoke_without_command=True, aliases=['ip監測'])
    async def ipmonitor(self, ctx):
        """管理 IP 流量監測任務。"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="📈 IP 流量監測管理",
                color=0x00AEEF
            )
            embed.add_field(
                name=f"1. 新增任務",
                value=f"`#ipmonitor add <IP位址>`\n(範例：`#ipmonitor add 140.125.203.233`)",
                inline=False
            )
            embed.add_field(
                name=f"2. 查看清單",
                value=f"`#ipmonitor list`",
                inline=False
            )
            embed.add_field(
                name=f"3. 移除任務",
                value=f"`#ipmonitor remove <IP位址>`",
                inline=False
            )
            await ctx.send(embed=embed)

    @ipmonitor.command(name='add', aliases=['新增'])
    @commands.has_permissions(administrator=True) # 僅限管理員
    async def add_ip_job(self, ctx, ip_address: str):
        """新增一個 IP 流量監測任務。"""
        
        if not self.notification_channel_id:
            return await ctx.send("❌ 錯誤：管理員尚未設定通知頻道 (IP_MONITOR_CHANNEL_ID)。")

        monitor_list = self._load_ip_list()
        
        if any(job['ip'] == ip_address for job in monitor_list):
            return await ctx.send(f"⚠️ IP `{ip_address}` 已經在監測清單中。", delete_after=10)
            
        await ctx.send(f"⏳ 正在嘗試抓取 `{ip_address}` 的初始狀態...")
        
        # --- 執行即時檢查 ---
        status_data = await asyncio.to_thread(_fetch_ip_traffic, ip_address)
        
        if status_data is None or status_data["Error"]:
            await ctx.send(f"❌ 無法抓取 IP `{ip_address}` 的初始狀態。爬蟲可能失敗或 IP 錯誤。")
            return

        current_traffic_gb = status_data['total_gb']
        new_status = "OVER_LIMIT" if current_traffic_gb > TRAFFIC_THRESHOLD_GB else "OK"

        # --- 新增任務 ---
        new_job = {
            "ip": ip_address,
            "user_id": ctx.author.id,     
            "set_by": ctx.author.display_name,
            "last_status": new_status # 儲存初始狀態
        }
        monitor_list.append(new_job)
        self._save_ip_list(monitor_list)
        
        await ctx.send(
            f"✅ 成功新增監測任務：\n"
            f"**IP:** `{ip_address}`\n"
            f"**初始狀態:** {new_status} ({current_traffic_gb} GB)"
        )

    @ipmonitor.command(name='remove', aliases=['移除', '刪除'])
    @commands.has_permissions(administrator=True) # 僅限管理員
    async def remove_ip_job(self, ctx, ip_address: str):
        """移除一個 IP 流量監測任務。"""
        monitor_list = self._load_ip_list()
        initial_count = len(monitor_list)
        
        monitor_list = [job for job in monitor_list if job['ip'] != ip_address]
        
        if len(monitor_list) == initial_count:
            return await ctx.send(f"❌ 錯誤：監測清單中找不到 IP `{ip_address}`。")
            
        self._save_ip_list(monitor_list)
        await ctx.send(f"✅ 成功移除 IP `{ip_address}` 的監測任務。")

    @ipmonitor.command(name='list', aliases=['清單'])
    async def list_ip_jobs(self, ctx):
        """顯示所有當前的 IP 監測任務。"""
        monitor_list = self._load_ip_list()
        
        if not monitor_list:
            return await ctx.send("目前沒有任何 IP 監測任務。")
            
        embed = discord.Embed(
            title="📈 當前 IP 流量監測清單",
            description=f"總計 {len(monitor_list)} 個任務。每 {CHECK_INTERVAL_MINUTES} 分鐘檢查一次。",
            color=0x00AEEF
        )
        
        for job in monitor_list:
            last_status_str = job.get('last_status', '尚未檢查')
            if last_status_str == "OK":
                last_status_str = "🟢 正常"
            elif last_status_str == "OVER_LIMIT":
                last_status_str = "🔴 超量"

            embed.add_field(
                name=f"IP: {job['ip']}",
                value=(
                    f"目前狀態: **{last_status_str}**\n"
                    f"設定者: {job.get('set_by', 'N/A')}"
                ),
                inline=False
            )
            
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(IPCrawler(bot))