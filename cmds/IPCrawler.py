import discord
from discord import app_commands # ✅ 修正：現在 app_commands 已正確匯入
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
import urllib3 # ✅ 使用標準 import

# --- 設定常量 ---
IP_MONITOR_FILE = './data/ip_monitor_list.json' # 儲存 IP 監測任務的檔案路徑
CHECK_INTERVAL_MINUTES = 10           # 檢查間隔 (10 分鐘)
CRAWL_DELAY_SECONDS = 30              # 每筆 IP 查詢之間的延遲 (慢慢爬)
TRAFFIC_THRESHOLD_GB = 10.0           # 流量警告閾值 (10 GB)

# 讀取 IP 通知的頻道 ID
IP_MONITOR_CHANNEL_ID_STR = os.getenv('IP_MONITOR_CHANNEL_ID') 

# 爬蟲目標 URL
URL = "https://netflow.yuntech.edu.tw/netflow.pl"

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning) 

# =========================================================
# ✅ 核心爬蟲邏輯 (保持不變)
# =========================================================
def _fetch_ip_traffic(target_ip: str) -> Optional[Dict[str, Any]]:
    """
    執行爬蟲並獲取指定 IP **今天**的流量數據。
    返回 {'total_gb': float, 'update_time': str} 或 None
    """
    
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
        response = requests.post(URL, data=PAYLOAD, headers=headers, timeout=60, verify=False) 
        response.raise_for_status()
        logging.info(f"HTTP 請求成功 (IP: {target_ip})")

        soup = BeautifulSoup(response.text, 'html.parser')
        
        update_time_match = update_time_pattern.search(soup.get_text())
        if update_time_match:
            page_update_time = update_time_match.group(1)

        table = soup.find('table', {'width': '95%'}) 
        if not table:
            table = soup.find('table')
        
        if not table:
            logging.error(f"錯誤 (IP: {target_ip})：找不到網頁表格。")
            return None

        data_rows = table.find_all('tr')
        data_rows_content = data_rows[1:] if len(data_rows) > 0 else [] 
        
        for row in data_rows_content:
            cells = row.find_all('td')
            
            if len(cells) >= 9:
                row_year = cells[0].get_text(strip=True).replace('\xa0', '')
                row_month = cells[1].get_text(strip=True).replace('\xa0', '')
                row_day = cells[2].get_text(strip=True).replace('\xa0', '')
                
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

class IPCrawler(Cog_Extension):
    
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
            logging.info("IP 流量監測任務已啟動。") # ✅ 中文化
        else:
            logging.warning("IP 流量監測任務**未**啟動，因為缺少 IP_MONITOR_CHANNEL_ID。") # ✅ 中文化
            
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
            last_status = job.get('last_status', "OK") 
            
            # --- 執行爬蟲 ---
            status_data = await asyncio.to_thread(_fetch_ip_traffic, ip)
            
            if status_data is None:
                logging.warning(f"IP {ip} 爬蟲失敗或未找到數據。")
                continue
                
            current_traffic_gb = status_data['total_gb']
            page_update_time = status_data['update_time']
            
            # --- 判斷邏輯 ---
            new_status = "OVER_LIMIT" if current_traffic_gb > TRAFFIC_THRESHOLD_GB else "OK"
            
            if new_status == last_status:
                continue
                
            # --- 狀態已改變，準備發送通知 ---
            list_changed = True
            job['last_status'] = new_status 
            
            if new_status == "OVER_LIMIT":
                logging.warning(f"IP {ip} 流量超標！ ({current_traffic_gb} GB)")
                embed = discord.Embed(
                    title="🚨 IP 流量警告：流量超標",
                    description=f"監測的 IP **{ip}** 今日流量已達 **{current_traffic_gb} GB**，超過 **{TRAFFIC_THRESHOLD_GB} GB** 的限制！",
                    color=0xFF0000 # 紅色
                )
                embed.set_footer(text=f"頁面更新時間: {page_update_time}")
                await target_channel.send(embed=embed)
                
            else: # new_status == "OK"
                logging.info(f"IP {ip} 流量已恢復正常 ({current_traffic_gb} GB)")
                embed = discord.Embed(
                    title="✅ IP 流量狀態：已恢復正常",
                    description=f"監測的 IP **{ip}** 今日流量已降至 **{current_traffic_gb} GB**。",
                    color=0x00FF00 # 綠色
                )
                embed.set_footer(text=f"頁面更新時間: {page_update_time}")
                await target_channel.send(embed=embed)

            # --- 慢慢爬 ---
            await asyncio.sleep(CRAWL_DELAY_SECONDS) 

        if list_changed:
            self._save_ip_list(ip_list)
        
        logging.info("IP 流量檢查完畢。")

    # =========================================================
    # ✅ 錯誤處理 (Error Handler) - V3.2 標準
    # =========================================================
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        # 關鍵修正：如果指令不屬於 'IPCrawler' Cog，就直接退出
        if ctx.command and ctx.command.cog_name != 'IPCrawler':
            return
            
        logging.warning(f"IPCrawler Cog 捕獲到指令錯誤 (指令: {ctx.command}, 錯誤: {error})")

        is_private = ctx.interaction is not None
        
        if ctx.command and (ctx.command.name == 'ipmonitor' or (ctx.command.root_parent and ctx.command.root_parent.name == 'ipmonitor')):
            
            if isinstance(error, commands.MissingPermissions):
                await ctx.send("❌ **權限不足：** 您沒有權限執行此指令。", ephemeral=is_private)
            
            elif isinstance(error, commands.MissingRequiredArgument):
                 await ctx.send(f"⚠️ **參數遺漏錯誤：** 您忘記提供 `{error.param.name}` 參數了！", ephemeral=is_private)
            
            else:
                pass # 其他錯誤上報給 bot.py

    # =========================================================
    # ✅ 指令：設定監測任務 (已升級為 Hybrid Group)
    # =========================================================
    @commands.hybrid_group(name='ipmonitor', aliases=['ip監測'], description="管理 IP 流量監測任務")
    async def ipmonitor(self, ctx: commands.Context):
        """管理 IP 流量監測任務。"""
        is_private = ctx.interaction is not None
        
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="📈 IP 流量監測管理",
                color=0x00AEEF
            )
            embed.add_field(name=f"1. 新增任務", value=f"`{ctx.prefix}ipmonitor add <IP位址>`", inline=False)
            embed.add_field(name=f"2. 查看清單", value=f"`{ctx.prefix}ipmonitor list`", inline=False)
            embed.add_field(name=f"3. 移除任務", value=f"`{ctx.prefix}ipmonitor remove <IP位址>`", inline=False)
            await ctx.send(embed=embed, ephemeral=is_private)

    @ipmonitor.command(name='add', aliases=['新增'], description="新增一個 IP 流量監測任務")
    @app_commands.describe(ip_address="要監測的 IP 位址")
    @commands.has_permissions(administrator=True) # 僅限管理員
    async def add_ip_job(self, ctx: commands.Context, ip_address: str):
        """新增一個 IP 流量監測任務。"""
        is_private = ctx.interaction is not None
        
        if not self.notification_channel_id:
            return await ctx.send("❌ 錯誤：管理員尚未設定通知頻道 (IP_MONITOR_CHANNEL_ID)。", ephemeral=is_private)

        monitor_list = self._load_ip_list()
        
        if any(job['ip'] == ip_address for job in monitor_list):
            return await ctx.send(f"⚠️ IP `{ip_address}` 已經在監測清單中。", ephemeral=is_private)
            
        # ✅ 遵循「耗時指令」SOP
        original_message = await ctx.send(f"⏳ 正在嘗試抓取 `{ip_address}` 的初始狀態...", ephemeral=is_private)
        
        # --- 執行即時檢查 ---
        status_data = await asyncio.to_thread(_fetch_ip_traffic, ip_address)
        
        if status_data is None:
            error_msg = f"❌ 無法抓取 IP `{ip_address}` 的初始狀態。爬蟲可能失敗或 IP 錯誤。"
            if is_private: await ctx.followup.send(error_msg, ephemeral=True)
            else: await original_message.edit(content=error_msg)
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
        
        success_msg = (
            f"✅ 成功新增監測任務：\n"
            f"**IP:** `{ip_address}`\n"
            f"**初始狀態:** {new_status} ({current_traffic_gb} GB)"
        )
        if is_private: await ctx.followup.send(success_msg, ephemeral=True)
        else: await original_message.edit(content=success_msg)

    @ipmonitor.command(name='remove', aliases=['移除', '刪除'], description="移除一個 IP 流量監測任務")
    @app_commands.describe(ip_address="要移除的 IP 位址")
    @commands.has_permissions(administrator=True) # 僅限管理員
    async def remove_ip_job(self, ctx: commands.Context, ip_address: str):
        """移除一個 IP 流量監測任務。"""
        is_private = ctx.interaction is not None
        monitor_list = self._load_ip_list()
        initial_count = len(monitor_list)
        
        monitor_list = [job for job in monitor_list if job['ip'] != ip_address]
        
        if len(monitor_list) == initial_count:
            return await ctx.send(f"❌ 錯誤：監測清單中找不到 IP `{ip_address}`。", ephemeral=is_private)
            
        self._save_ip_list(monitor_list)
        await ctx.send(f"✅ 成功移除 IP `{ip_address}` 的監測任務。", ephemeral=is_private)

    @ipmonitor.command(name='list', aliases=['清單'], description="顯示所有當前的 IP 監測任務")
    async def list_ip_jobs(self, ctx: commands.Context):
        """顯示所有當前的 IP 監測任務。"""
        is_private = ctx.interaction is not None
        monitor_list = self._load_ip_list()
        
        if not monitor_list:
            return await ctx.send("目前沒有任何 IP 監測任務。", ephemeral=is_private)
            
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
            
        await ctx.send(embed=embed, ephemeral=is_private)

async def setup(bot):
    await bot.add_cog(IPCrawler(bot))
