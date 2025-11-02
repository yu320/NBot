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
import urllib3 

# --- 設定常量 ---
MONITOR_FILE = './data/monitor_list.json' 
CHECK_INTERVAL_SECONDS = 180  # 每 3 分鐘檢查一次           
DEFAULT_ACAD_SEME = "1142"              

# --- ✅ 修正點 1：讀取全域通知頻道 ID ---
# (請確保您已在 .env / GitHub Secrets / Dockge 中設定了此變數)
MONITOR_NOTIFICATION_CHANNEL_ID_STR = os.getenv('MONITOR_CHANNEL_ID') 
MONITOR_ROLE_CATEGORY_ID_STR = os.getenv('MONITOR_ROLE_CATEGORY_ID')

# 禁用 requests 呼叫 verify=False 時產生的警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning) 

# --- 爬蟲核心函式 (保持不變) ---
def _fetch_state_keys() -> Optional[Dict[str, str]]:
    GET_URL = "https://webapp.yuntech.edu.tw/WebNewCAS/Course/QueryCour.aspx"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(GET_URL, headers=headers, timeout=10, verify=False)
        response.raise_for_status() 
        soup = BeautifulSoup(response.text, 'html.parser')
        keys = {}
        for input_tag in soup.find_all('input', type='hidden'):
            if input_tag.get('name') and input_tag.get('value'):
                keys[input_tag['name']] = input_tag['value']
        
        if '__VIEWSTATE' in keys and '__EVENTVALIDATION' in keys:
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

def _get_course_status(course_id: str, acad_seme: str) -> Optional[Dict[str, int]]:
    TARGET_URL = "https://webapp.yuntech.edu.tw/WebNewCAS/Course/QueryCour.aspx" 
    state_keys = _fetch_state_keys()
    if not state_keys:
        return None
    payload = {
        'ctl00_MainContent_ToolkitScriptManager1$HiddenField': state_keys['ToolkitScriptManager'],
        '__LASTFOCUS': '',
        '__EVENTTARGET': '',
        '__EVENTARGUMENT': '',
        '__VIEWSTATE': state_keys['VIEWSTATE'],
        '__VIEWSTATEGENERATOR': state_keys['VIEWSTATEGENERATOR'],
        '__VIEWSTATEENCRYPTED': '',
        '__EVENTVALIDATION': state_keys['EVENTVALIDATION'],
        'ctl00$MainContent$AcadSeme': acad_seme, 
        'ctl00$MainContent$College': '',
        'ctl00$MainContent$DeptCode': '',
        'ctl00$MainContent$CurrentSubj': course_id, 
        'ctl00$MainContent$TextBoxWatermarkExtender3_ClientState': '',
        'ctl00$MainContent$SubjName': '',
        'ctl00$MainContent$TextBoxWatermarkExtender1_ClientState': '',
        'ctl00$MainContent$Instructor': '',
        'ctl00$MainContent$TextBoxWatermarkExtender2_ClientState': '',
        'ctl00$MainContent$Submit': '執行查詢',
    }
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': TARGET_URL
    }
    try:
        response = requests.post(TARGET_URL, data=payload, headers=headers, timeout=15, verify=False)
        response.raise_for_status() 
        soup = BeautifulSoup(response.text, 'html.parser')
        course_table = soup.find('table', id='ctl00_MainContent_Course_GridView') 
        if not course_table:
             logging.error(f"課號 {course_id} 爬蟲失敗：找不到結果表格 ID。")
             return None
        rows = course_table.find_all('tr')
        data_row = None
        for row in rows[1:]: 
            cells = row.find_all('td')
            if len(cells) > 0:
                 course_id_in_table = cells[0].text.strip()
                 course_id_in_table = re.sub(r'\s+', '', course_id_in_table) 
                 if course_id_in_table == course_id: 
                     data_row = row
                     break
        if not data_row:
            logging.warning(f"課號 {course_id} 在學期 {acad_seme} 的查詢結果中未找到該行數據。")
            return None
        cells = data_row.find_all('td')
        if len(cells) > 10: 
            try:
                current_count_text = cells[9].text.strip()
                current_count = int(current_count_text)
                max_count_text = cells[10].text.strip()
                max_match = re.search(r'(\d+)', max_count_text) 
                max_count = 999 
                if max_match:
                    max_count = int(max_match.group(1))
                elif "限" not in max_count_text:
                    max_count = 999 
                return {'current': current_count, 'max': max_count}
            except Exception as e:
                logging.warning(f"課號 {course_id} 找到行但解析人數時出錯: {e}")
                return None
        else:
            logging.warning(f"課號 {course_id} 的表格行欄位數量不足。")
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"爬蟲請求失敗: {e}")
        return None

# =========================================================

class EnrollmentMonitor(Cog_Extension):
    
    def __init__(self, bot):
        super().__init__(bot)
        
        # ✅ 修正點 2：在啟動時驗證通知頻道 ID
        self.notification_channel_id = None
        if MONITOR_NOTIFICATION_CHANNEL_ID_STR and MONITOR_NOTIFICATION_CHANNEL_ID_STR.isdigit():
            self.notification_channel_id = int(MONITOR_NOTIFICATION_CHANNEL_ID_STR)
        else:
            logging.error("MONITOR_CHANNEL_ID 未設定或格式錯誤，課程監測通知將無法發送！")

        os.makedirs('./data', exist_ok=True)
        if not os.path.exists(MONITOR_FILE):
            self._save_monitor_list([])
            
        # 只有在頻道 ID 設定正確時才啟動任務
        if self.notification_channel_id:
            self.check_enrollment.start()
            logging.info("Enrollment Monitor task started.")
        else:
            logging.warning("Enrollment Monitor task DID NOT start due to missing MONITOR_CHANNEL_ID.")
            
    def cog_unload(self):
        self.check_enrollment.cancel()
        
    def _load_monitor_list(self) -> List[Dict[str, Any]]:
        try:
            with open(MONITOR_FILE, 'r', encoding='utf8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"載入監測清單失敗: {e}")
            return []

    def _save_monitor_list(self, monitor_list: List[Dict[str, Any]]):
        try:
            with open(MONITOR_FILE, 'w', encoding='utf8') as f:
                json.dump(monitor_list, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.error(f"儲存監測清單失敗: {e}")

    # =========================================================
    # ✅ 背景任務：定期檢查 (修正點 3：使用 self.notification_channel_id)
    # =========================================================
    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def check_enrollment(self):
        await self.bot.wait_until_ready()
        
        monitor_list = self._load_monitor_list()
        list_changed = False 
        
        # 獲取一次通知頻道物件
        target_channel = self.bot.get_channel(self.notification_channel_id)
        if not target_channel:
            logging.error(f"找不到指定的通知頻道 ID: {self.notification_channel_id}，任務暫停。")
            return

        for job in monitor_list:
            course_id = job['course_id']
            acad_seme = job['acad_seme']
            role_id = job.get('role_id', None) 
            last_status = job.get('last_status', None) 
            
            if not role_id: # 如果 role_id 遺失，則跳過
                logging.warning(f"任務 {course_id} 的 RoleID 遺失，跳過。")
                continue 

            status_data = await asyncio.to_thread(_get_course_status, course_id, acad_seme)
            
            if status_data is None:
                logging.warning(f"課號 {course_id} ({acad_seme}) 爬蟲失敗或未找到數據。")
                continue
                
            current_count = status_data['current']
            max_count = status_data['max']
            
            new_status = "AVAILABLE" if current_count < max_count else "FULL"
            
            if new_status == last_status:
                continue
                
            # --- 狀態已改變，準備發送通知 ---
            list_changed = True
            job['last_status'] = new_status 
            
            user_mention = f"<@&{role_id}>" # @ 身份組
            
            if new_status == "AVAILABLE":
                logging.info(f"課號 {course_id} ({acad_seme}) 變為 AVAILABLE。")
                embed = discord.Embed(
                    title="🟢 搶課警報：有空位了！",
                    description=f"課程 **{course_id}** (學期: {acad_seme}) **有空位了，快搶！**",
                    color=0x32CD32 
                )
                embed.add_field(name="當前人數 (Sel.)", value=f"**{current_count}** 人", inline=True)
                embed.add_field(name="限制人數 (Max)", value=f"**{max_count}** 人", inline=True)
                await target_channel.send(user_mention, embed=embed)
                
            else: # new_status == "FULL"
                logging.info(f"課號 {course_id} ({acad_seme}) 變為 FULL。")
                embed = discord.Embed(
                    title="🔴 課程狀態：已額滿",
                    description=f"課程 **{course_id}** (學期: {acad_seme}) **位置滿了，下次請早。**",
                    color=0xAAAAAA 
                )
                embed.add_field(name="當前人數 (Sel.)", value=f"**{current_count}** 人", inline=True)
                embed.add_field(name="限制人數 (Max)", value=f"**{max_count}** 人", inline=True)
                await target_channel.send(user_mention, embed=embed)

        if list_changed:
            self._save_monitor_list(monitor_list)


    # =========================================================
    # ✅ 指令：設定監測任務 (修正點 4：修改 Add)
    # =========================================================
    @commands.group(name='monitor', invoke_without_command=True, aliases=['監測', '課表監測'])
    async def monitor(self, ctx):
        """管理課程人數監測任務。"""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="📚 課程人數監測管理",
                description="這是一系列監測指令。",
                color=0x4682B4
            )
            embed.add_field(
                name=f"1. 新增任務 (互動式)",
                value=f"`#monitor add`\n(Bot 會引導您輸入課號，自動建立身份組，並使用預設學期 {DEFAULT_ACAD_SEME})",
                inline=False
            )
            embed.add_field(
                name=f"2. 更新學期",
                value=f"`#monitor update <課號> <新學期碼>`\n(範例：`#monitor update 5512 1141`)",
                inline=False
            )
            embed.add_field(
                name=f"3. 查看清單",
                value=f"`#monitor list`",
                inline=False
            )
            embed.add_field(
                name=f"4. 移除任務",
                value=f"`#monitor remove <課號>`",
                inline=False
            )
            await ctx.send(embed=embed)

    @monitor.command(name='add', aliases=['新增'])
    @commands.has_permissions(manage_roles=True) 
    async def add_monitor_job(self, ctx):
        """
        以互動方式新增一個課程人數監測任務 (使用預設學期)。
        """
        
        # --- ✅ 修正點 4：檢查 Bot 權限和通知頻道設定 ---
        if not ctx.guild.me.guild_permissions.manage_roles:
            return await ctx.send("❌ 錯誤：Bot 需要「管理身份組 (Manage Roles)」權限才能執行此操作。", ephemeral=True)
            
        if not self.notification_channel_id:
            return await ctx.send("❌ 錯誤：管理員尚未設定通知頻道 (MONITOR_CHANNEL_ID)。", ephemeral=True)
            
        target_channel = self.bot.get_channel(self.notification_channel_id)
        if not target_channel:
             return await ctx.send(f"❌ 錯誤：找不到設定的通知頻道 ID: {self.notification_channel_id}。", ephemeral=True)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            # --- 步驟 1：詢問課號 ---
            prompt = await ctx.send(f"請輸入您要監測的**課號 (Serial No.)**： (30 秒內回應)", ephemeral=True)
            
            msg_course_id = await self.bot.wait_for('message', check=check, timeout=30.0)
            course_id = msg_course_id.content.strip()
            
            try:
                await msg_course_id.delete() 
            except discord.Forbidden:
                pass 
            
            # --- 步驟 2：使用預設學期碼 ---
            acad_seme = DEFAULT_ACAD_SEME

            # --- 步驟 3：驗證與儲存 ---
            monitor_list = self._load_monitor_list()
            
            if any(job['course_id'] == course_id and job['acad_seme'] == acad_seme for job in monitor_list):
                await ctx.send(f"⚠️ 課號 `{course_id}` ({acad_seme}) 已經在監測清單中，請勿重複新增。", ephemeral=True)
                return
            
            # --- 步驟 4：建立身份組並設定位置 ---
            role_name = f"Mon-{course_id}"
            existing_role = discord.utils.get(ctx.guild.roles, name=role_name)
            
            if existing_role:
                new_role = existing_role
                logging.info(f"找到已存在的身份組: {role_name}")
            else:
                try:
                    permissions = discord.Permissions.none() 
                    new_role = await ctx.guild.create_role(
                        name=role_name,
                        permissions=permissions,
                        mentionable=True, 
                        reason=f"由 {ctx.author} 建立的課程監測"
                    )
                    logging.info(f"已建立新身份組: {role_name}")
                    
                    if MONITOR_ROLE_CATEGORY_ID_STR:
                        try:
                            category_role_id = int(MONITOR_ROLE_CATEGORY_ID_STR)
                            category_role = ctx.guild.get_role(category_role_id)
                            
                            if category_role:
                                await new_role.edit(position=category_role.position)
                                logging.info(f"已將身份組 {new_role.name} 移動至 {category_role.name} 下方。")
                            else:
                                logging.warning(f"找不到設定的 MONITOR_ROLE_CATEGORY_ID: {MONITOR_ROLE_CATEGORY_ID_STR}")
                        except Exception as e:
                            logging.error(f"移動身份組時發生錯誤: {e}")
                            
                except discord.Forbidden:
                    await ctx.send("❌ 錯誤：Bot 無法建立或移動身份組，請檢查權限設定。", ephemeral=True)
                    return
                except Exception as e:
                    await ctx.send(f"建立身份組時發生錯誤：{e}", ephemeral=True)
                    return

            # --- 步驟 5：新增任務 ---
            new_job = {
                "course_id": course_id,
                "acad_seme": acad_seme,
                "channel_id": self.notification_channel_id, # ✅ 修正點：使用全域通知頻道
                "user_id": ctx.author.id, 
                "role_id": new_role.id, 
                "set_by": ctx.author.display_name,
                "last_status": None 
            }
            monitor_list.append(new_job)
            self._save_monitor_list(monitor_list)
            
            # --- ✅ 修正點 4：在「指定頻道」發送公開的建立訊息 ---
            await target_channel.send(f"✅ 任務已新增！\n正在監測課號 `{course_id}` (學期 {acad_seme})。\n感興趣的成員請自行加入 {new_role.mention} 身份組以接收通知。")
            await ctx.send("✅ 任務已在通知頻道建立！", ephemeral=True) # 私下回覆指令發起者

            # --- 步驟 6：執行即時檢查 ---
            status_data = await asyncio.to_thread(_get_course_status, course_id, acad_seme)
            
            if status_data is None:
                await target_channel.send(f"❌ 無法抓取課程 `{course_id}` 的初始狀態。爬蟲可能失敗或課號錯誤。")
                return

            current_count = status_data['current']
            max_count = status_data['max']
            new_status = "AVAILABLE" if current_count < max_count else "FULL"

            # --- 步驟 7：更新 JSON 中的狀態並發送公開通知 ---
            monitor_list = self._load_monitor_list()
            for job in monitor_list:
                if job['course_id'] == course_id and job['acad_seme'] == acad_seme:
                    job['last_status'] = new_status
                    break
            self._save_monitor_list(monitor_list) 

            user_mention = f"{new_role.mention}" 

            if new_status == "AVAILABLE":
                embed_title = "🟢 初始狀態：有空位"
                embed_desc = f"監測的課程 **{course_id}** (學期: {acad_seme}) **目前有空位！**"
                embed_color = 0x32CD32
            else: # new_status == "FULL"
                embed_title = "🔴 初始狀態：已額滿"
                embed_desc = f"監測的課程 **{course_id}** (學期: {acad_seme}) **目前已額滿。**"
                embed_color = 0xAAAAAA

            embed = discord.Embed(title=embed_title, description=embed_desc, color=embed_color)
            embed.add_field(name="當前人數 (Sel.)", value=f"**{current_count}** 人", inline=True)
            embed.add_field(name="限制人數 (Max)", value=f"**{max_count}** 人", inline=True)
            
            await target_channel.send(user_mention, embed=embed)

        except asyncio.TimeoutError:
            await ctx.send("⌛ 已逾時，請重新執行指令。", ephemeral=True)
        except Exception as e:
            await ctx.send(f"發生錯誤：{e}", ephemeral=True)


    @monitor.command(name='update', aliases=['更新學期'])
    @commands.has_permissions(manage_roles=True) 
    async def update_monitor_job(self, ctx, course_id: str, new_acad_seme: str):
        """更新一個已存在任務的學期碼。"""
        
        if len(new_acad_seme) != 4 or not new_acad_seme.isdigit():
             return await ctx.send(f"⚠️ 新學期碼格式錯誤。請確保為 4 位數字 (例如: 1141)。", ephemeral=True)

        monitor_list = self._load_monitor_list()
        
        job_found = False
        for job in monitor_list:
            if job['course_id'] == course_id:
                old_seme = job['acad_seme']
                job['acad_seme'] = new_acad_seme
                job['last_status'] = None 
                job_found = True
                break
            
        if job_found:
            self._save_monitor_list(monitor_list)
            await ctx.send(f"✅ **已更新**監測任務：\n**課號:** `{course_id}`\n**學期:** 從 `{old_seme}` 更新為 `{new_acad_seme}`。", ephemeral=True)
        else:
            await ctx.send(f"❌ 錯誤：監測清單中找不到課號 `{course_id}`。請先使用 `#monitor add` 新增。", ephemeral=True)


    @monitor.command(name='remove', aliases=['移除', '刪除'])
    @commands.has_permissions(manage_roles=True) 
    async def remove_monitor_job(self, ctx, course_id: str):
        """移除一個課程人數監測任務 (會移除該課號的所有學期)。"""
        
        if not ctx.guild.me.guild_permissions.manage_roles:
            return await ctx.send("❌ 錯誤：Bot 需要「管理身份組 (Manage Roles)」權限才能刪除身份組。", ephemeral=True)

        monitor_list = self._load_monitor_list()
        initial_count = len(monitor_list)
        
        roles_to_delete = []
        jobs_to_keep = []

        for job in monitor_list:
            if job['course_id'] == course_id:
                if 'role_id' in job:
                    roles_to_delete.append(job['role_id'])
            else:
                jobs_to_keep.append(job)
        
        removed_count = initial_count - len(jobs_to_keep)
        if removed_count == 0:
            return await ctx.send(f"❌ 錯誤：監測清單中找不到課號 `{course_id}`。", ephemeral=True)
            
        self._save_monitor_list(jobs_to_keep)
        
        deleted_roles_count = 0
        for role_id in set(roles_to_delete): 
            role = ctx.guild.get_role(role_id)
            if role:
                try:
                    await role.delete(reason=f"由 {ctx.author} 移除監測任務")
                    deleted_roles_count += 1
                except discord.Forbidden:
                    logging.error(f"無法刪除身份組 {role.name} (ID: {role_id})，權限不足。")
                except Exception as e:
                    logging.error(f"刪除身份組 {role.name} 時發生錯誤: {e}")

        await ctx.send(f"✅ 成功移除課號 `{course_id}` 的 {removed_count} 個監測任務，並刪除了 {deleted_roles_count} 個相關身份組。", ephemeral=True)


    @monitor.command(name='list', aliases=['清單'])
    async def list_monitor_jobs(self, ctx):
        """顯示所有當前的監測任務。"""
        monitor_list = self._load_monitor_list()
        
        if not monitor_list:
            return await ctx.send("目前沒有任何課程監測任務。", ephemeral=True)
            
        embed = discord.Embed(
            title="📚 當前課程人數監測清單",
            description=f"總計 {len(monitor_list)} 個任務。每 {CHECK_INTERVAL_SECONDS/60} 分鐘檢查一次。",
            color=0x4682B4
        )
        
        for job in monitor_list:
            last_status_str = job.get('last_status', '尚未檢查')
            if last_status_str == "AVAILABLE":
                last_status_str = "🟢 有空位"
            elif last_status_str == "FULL":
                last_status_str = "🔴 已額满"
            
            role_mention = f"<@&{job['role_id']}>" if 'role_id' in job else "N/A"

            embed.add_field(
                name=f"課號: {job['course_id']} (學期: {job['acad_seme']})",
                value=(
                    f"目前狀態: **{last_status_str}**\n"
                    f"通知身份組: {role_mention}\n"
                    f"設定者: <@{job['user_id']}>"
                ),
                inline=False
            )
            
        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(EnrollmentMonitor(bot))