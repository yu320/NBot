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
from discord import app_commands # 引入 app_commands

# --- 設定常量 ---
MONITOR_FILE = './data/monitor_list.json' 
CONFIG_FILE = './data/monitor_config.json' 

CHECK_INTERVAL_SECONDS = 180  # 每 3 分鐘檢查一次           
DEFAULT_ACAD_SEME = "1142" # (保留作為初始的備用值)

# --- 讀取全域通知頻道 ID ---
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
            toolkit_key = keys.get('ctl00$MainContent$ToolkitScriptManager1$HiddenField', ';;AjaxControlToolkit, Version=4.1.60919.0, Culture=neutral, PublicKeyToken=28f01b0e84b6d53e:zh-TW:ab75ae50-1505-49da-acca-8b96b9B2ce21188d702e6fb408cb1a:475a4ef5:effe2a26:7e63a579:5546a2b:d2e10b12:37e2e5c9:1d3ed089:751cdd15:dfad98a5:497ef277:a43b07eb:3cf12cf1')
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
# ✅ 修正 1：修改爬蟲核心
# =========================================================
def _get_course_status(course_id: str, acad_seme: str) -> Optional[Dict[str, Any]]: # <-- 返回類型已修改
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
                # 抓取人數 (cells[9])
                current_count_text = cells[9].text.strip()
                current_count = int(current_count_text)
                
                # 🆕 抓取課程名稱 (cells[2])
                course_name_text = cells[2].text.strip()
                
                # 抓取人數上限 (cells[10])
                max_count_text = cells[10].text.strip()
                max_match = re.search(r'(\d+)', max_count_text) 
                max_count = 999 
                if max_match:
                    max_count = int(max_match.group(1))
                elif "限" not in max_count_text:
                    max_count = 999 
                
                # 🆕 修改回傳值，加入 course_name
                return {'current': current_count, 'max': max_count, 'course_name': course_name_text}
                
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
        
        self.notification_channel_id = None
        if MONITOR_NOTIFICATION_CHANNEL_ID_STR and MONITOR_NOTIFICATION_CHANNEL_ID_STR.isdigit():
            self.notification_channel_id = int(MONITOR_NOTIFICATION_CHANNEL_ID_STR)
        else:
            logging.error("MONITOR_CHANNEL_ID 未設定或格式錯誤，課程監測通知將無法發送！")

        os.makedirs('./data', exist_ok=True)
        if not os.path.exists(MONITOR_FILE):
            self._save_monitor_list([])
            
        self.default_acad_seme = DEFAULT_ACAD_SEME
        self._load_config() 
            
        # ✅ 已移除 self.check_enrollment.start()，改至 on_ready 中啟動
        if not self.notification_channel_id:
            logging.warning("課程監測任務**未**啟動，因為缺少 MONITOR_CHANNEL_ID。")

    # =========================================================
    # ✅ 新增：在機器人準備就緒後才啟動背景任務
    # =========================================================
    @commands.Cog.listener()
    async def on_ready(self):
        """當機器人準備就緒時啟動任務"""
        # 防止因重新連線導致重複啟動
        if not self.check_enrollment.is_running():
            if self.notification_channel_id:
                self.check_enrollment.start()
                logging.info("課程監測任務已啟動 (於 on_ready)。")
            
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

    def _load_config(self):
        """啟動時讀取設定檔"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf8') as f:
                    config_data = json.load(f)
                    self.default_acad_seme = config_data.get('DEFAULT_ACAD_SEME', self.default_acad_seme)
                    logging.info(f"已從 {CONFIG_FILE} 載入預設學期: {self.default_acad_seme}")
            else:
                self._save_config()
                logging.info(f"已建立預設設定檔: {CONFIG_FILE}")
        except Exception as e:
            logging.error(f"載入 {CONFIG_FILE} 失敗: {e}")

    def _save_config(self):
        """儲存設定檔"""
        try:
            config_data = {
                'DEFAULT_ACAD_SEME': self.default_acad_seme
            }
            with open(CONFIG_FILE, 'w', encoding='utf8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.error(f"儲存 {CONFIG_FILE} 失敗: {e}")

    # =========================================================
    # 表情符號反應監聽器 (Reaction Listeners)
    # =========================================================
    
    async def _get_job_by_reaction_message(self, message_id: int) -> Optional[Dict[str, Any]]:
        """輔助函式：透過 reaction_message_id 尋找監測任務"""
        monitor_list = self._load_monitor_list()
        for job in monitor_list:
            if job.get('reaction_message_id') == message_id:
                return job
        return None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """當使用者新增表情符號時"""
        
        if payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) != "🔔":
            return
        
        job = await self._get_job_by_reaction_message(payload.message_id)
        if not job:
            return 

        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
            
        role_id = job.get('role_id')
        if not role_id: return
            
        role = guild.get_role(role_id)
        if not role:
            logging.warning(f"表情符號訊息 {payload.message_id}：找不到對應的身份組 ID {role_id}。")
            return
            
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            logging.warning(f"使用者 {payload.user_id} 新增了 🔔，但在伺服器中找不到該成員。")
            return
        except Exception as e:
            logging.error(f"抓取成員 {payload.user_id} 時失敗: {e}")
            return
        
        if not member: 
            return 
        
        try:
            if role not in member.roles:
                await member.add_roles(role, reason="User reacted with 🔔")
                logging.info(f"已將身份組 {role.name} 加入到 {member.display_name}。")
        except discord.Forbidden:
            logging.error(f"Bot權限不足，無法將身份組 {role.name} 加入到 {member.display_name}。")
        except Exception as e:
            logging.error(f"新增身份組時失敗: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """當使用者移除表情符號時"""
        
        if payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) != "🔔":
            return
        
        job = await self._get_job_by_reaction_message(payload.message_id)
        if not job:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
            
        role_id = job.get('role_id')
        if not role_id: return
            
        role = guild.get_role(role_id)
        if not role: return
        
        try:
            member = await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            logging.warning(f"使用者 {payload.user_id} 移除了表情符號，但在伺服器中找不到該成員。")
            return 
        
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="User removed 🔔 reaction")
                logging.info(f"已從 {member.display_name} 移除身份組 {role.name}。")
        except discord.Forbidden:
            logging.error(f"Bot權限不足，無法從 {member.display_name} 移除身份組 {role.name}。")
        except Exception as e:
            logging.error(f"移除身份組時失敗: {e}")

    # =========================================================
    # 背景任務
    # =========================================================
    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def check_enrollment(self):
        await self.bot.wait_until_ready()
        
        monitor_list = self._load_monitor_list()
        list_changed = False 
        
        target_channel = self.bot.get_channel(self.notification_channel_id)
        if not target_channel:
            logging.error(f"找不到指定的通知頻道 ID: {self.notification_channel_id}，任務暫停。")
            return

        for job in monitor_list:
            course_id = job['course_id']
            acad_seme = job['acad_seme']
            role_id = job.get('role_id', None) 
            last_status = job.get('last_status', None) 
            
            if not role_id: 
                logging.warning(f"任務 {course_id} 的 RoleID 遺失，跳過。")
                continue 

            status_data = await asyncio.to_thread(_get_course_status, course_id, acad_seme)
            
            if status_data is None:
                logging.warning(f"課號 {course_id} ({acad_seme}) 爬蟲失敗或未找到數據。")
                continue
                
            current_count = status_data['current']
            max_count = status_data['max']
            # 🆕 從 status_data 獲取課程名稱，如果失敗則使用課號 (course_id) 作為備用
            course_name = status_data.get('course_name', course_id)
            
            new_status = "AVAILABLE" if current_count < max_count else "FULL"
            
            if new_status == last_status:
                continue
                
            list_changed = True
            job['last_status'] = new_status 
            
            # (如果您希望，也可以在這裡將 course_name 存入 job 中，但目前我們只在通知中使用)
            # job['course_name'] = course_name 
            
            user_mention = f"<@&{role_id}>"
            
            if new_status == "AVAILABLE":
                # 🆕 更新日誌和 Embed 訊息
                logging.info(f"課號 {course_id} ({course_name}) 變為 [有空位]。")
                embed = discord.Embed(
                    title="🟢 搶課警報：有空位了！", 
                    description=f"課程 **{course_name}** (`{course_id}`) (學期: {acad_seme}) **有空位了，快搶！**", 
                    color=0x32CD32
                )
                embed.add_field(name="當前人數 (Sel.)", value=f"**{current_count}** 人", inline=True)
                embed.add_field(name="限制人數 (Max)", value=f"**{max_count}** 人", inline=True)
                await target_channel.send(user_mention, embed=embed)
                
            else: # new_status == "FULL"
                # 🆕 更新日誌和 Embed 訊息
                logging.info(f"課號 {course_id} ({course_name}) 變為 [已額滿]。")
                embed = discord.Embed(
                    title="🔴 課程狀態：已額滿", 
                    description=f"課程 **{course_name}** (`{course_id}`) (學期: {acad_seme}) **位置滿了，下次請早。**", 
                    color=0xAAAAAA
                )
                embed.add_field(name="當前人數 (Sel.)", value=f"**{current_count}** 人", inline=True)
                embed.add_field(name="限制人數 (Max)", value=f"**{max_count}** 人", inline=True)
                await target_channel.send(user_mention, embed=embed)

        if list_changed:
            self._save_monitor_list(monitor_list)

        logging.info(f"課程監測輪詢結束，共檢查 {len(monitor_list)} 個任務。")

    # =========================================================
    # 錯誤監聽器
    # =========================================================
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        if ctx.command and ctx.command.cog_name != 'EnrollmentMonitor':
            return
            
        logging.warning(f"課程監測(EnrollmentMonitor) Cog 捕獲到指令錯誤 (指令: {ctx.command}, 錯誤: {error})")

        is_private = ctx.interaction is not None
        
        if ctx.command and ctx.command.name in ['monitor', 'add', 'update', 'remove', 'list', 'setdefault']:
            
            if isinstance(error, commands.MissingPermissions):
                await ctx.send("❌ **權限不足：** 您沒有權限執行此指令。", ephemeral=True, delete_after=10)
            
            elif isinstance(error, commands.BadArgument):
                 await ctx.send(f"⚠️ **參數類型錯誤：** {error}", ephemeral=True)
            
            elif isinstance(error, commands.MissingRequiredArgument):
                 await ctx.send(f"⚠️ **參數遺漏錯誤：** 您忘記提供 `{error.param.name}` 參數了！", ephemeral=True)
            else:
                pass

    # =========================================================
    # 指令：設定監測任務
    # =========================================================
    @commands.hybrid_group(name='monitor', aliases=['監測', '課表監測'], description="管理課程人數監測任務")
    async def monitor(self, ctx: commands.Context):
        is_private = ctx.interaction is not None
        
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(title="📚 課程人數監測管理", description="這是一系列監測指令。", color=0x4682B4)
            embed.add_field(name=f"1. 新增任務 (互動式)", value=f"`{ctx.prefix}monitor add` 或 `/monitor add`", inline=False)
            embed.add_field(name=f"2. 更新學期", value=f"`{ctx.prefix}monitor update <課號> <新學期碼>` 或 `/monitor update ...`", inline=False)
            embed.add_field(name=f"3. 查看清單", value=f"`{ctx.prefix}monitor list` 或 `/monitor list`", inline=False)
            embed.add_field(name=f"4. 移除任務", value=f"`{ctx.prefix}monitor remove <課號>` 或 `/monitor remove ...`", inline=False)
            embed.add_field(name=f"5. 設定預設學期", value=f"`{ctx.prefix}monitor setdefault <學期碼>` 或 `/monitor setdefault ...`", inline=False)
            await ctx.send(embed=embed, ephemeral=is_private)

    @monitor.command(name='setdefault', aliases=['設定預設學期'], description="設定 `/monitor add` 使用的預設學期")
    @app_commands.describe(semester_code="新的預設學期碼 (例如: 1151)")
    async def set_default_semester(self, ctx: commands.Context, semester_code: str):
        is_private = ctx.interaction is not None

        if len(semester_code) != 4 or not semester_code.isdigit():
             return await ctx.send(f"⚠️ 格式錯誤。學期碼必須是 4 位數字 (例如: 1151)。", ephemeral=True)
        
        try:
            old_seme = self.default_acad_seme
            self.default_acad_seme = semester_code
            self._save_config() 
            
            await ctx.send(f"✅ 成功更新預設學期！\n"
                         f"舊預設值: `{old_seme}`\n"
                         f"新預設值: `{self.default_acad_seme}`\n"
                         f"未來使用 `/monitor add` 將自動套用 `{self.default_acad_seme}`。",
                         ephemeral=is_private)
                         
        except Exception as e:
            await ctx.send(f"❌ 儲存設定失敗: {e}", ephemeral=True)

    # =========================================================
    # ✅ 修正 3：修改 add_monitor_job (互動式指令)
    # =========================================================
    @monitor.command(name='add', aliases=['新增'], description="[互動式] 新增一個課程人數監測任務")
    @commands.has_permissions(manage_roles=True) 
    async def add_monitor_job(self, ctx: commands.Context):
        """
        以互動方式新增一個課程人數監測任務 (使用預設學期)。
        """
        
        is_private = ctx.interaction is not None
        
        # --- 輔助函式：(已修正 ctx.interaction.followup) ---
        async def send_reply(message_content: str, ephemeral: bool = True):
            if is_private:
                await ctx.interaction.followup.send(message_content, ephemeral=ephemeral)
            else:
                await ctx.send(message_content, ephemeral=ephemeral)
        # ---
        
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
            # --- 步驟 1：詢問課號 (這是第一個回覆) ---
            prompt = await ctx.send(f"目前預設學期為 `{self.default_acad_seme}`。\n請輸入您要監測的**課號 (Serial No.)**： (30 秒內回應)", ephemeral=is_private)
            
            msg_course_id = await self.bot.wait_for('message', check=check, timeout=30.0)
            course_id = msg_course_id.content.strip()
            
            try:
                await msg_course_id.delete() 
                if not is_private: 
                    await prompt.delete()
            except discord.Forbidden:
                pass 
            
            acad_seme = self.default_acad_seme

            monitor_list = self._load_monitor_list()
            
            if any(job['course_id'] == course_id and job['acad_seme'] == acad_seme for job in monitor_list):
                await send_reply(f"⚠️ 課號 `{course_id}` (學期 {acad_seme}) 已經在監測清單中，請勿重複新增。", ephemeral=True)
                return
            
            # --- 步驟 4：建立身份組 (保持不變) ---
            role_name = f"Mon-{course_id}"
            existing_role = discord.utils.get(ctx.guild.roles, name=role_name)
            if existing_role:
                new_role = existing_role
                logging.info(f"找到已存在的身份組: {role_name}")
            else:
                try:
                    permissions = discord.Permissions.none() 
                    new_role = await ctx.guild.create_role(name=role_name, permissions=permissions, mentionable=True, reason=f"由 {ctx.author} 建立的課程監測")
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
                    await send_reply("❌ 錯誤：Bot 無法建立或移動身份組，請檢查權限設定。", ephemeral=True)
                    return
                except Exception as e:
                    await send_reply(f"建立身份組時發生錯誤：{e}", ephemeral=True)
                    return

            # --- 步驟 5：新增任務 (保持不變) ---
            new_job = {
                "course_id": course_id, "acad_seme": acad_seme, "channel_id": self.notification_channel_id,
                "user_id": ctx.author.id, "role_id": new_role.id, "set_by": ctx.author.display_name,
                "last_status": None, "reaction_message_id": None 
            }
            monitor_list.append(new_job)
            self._save_monitor_list(monitor_list) 
            
            # --- 步驟 6：發送公開訊息，並加上 🔔 (保持不變) ---
            creation_message = await target_channel.send(
                f"✅ 任務已新增！\n"
                f"正在監測課號 `{course_id}` (學期 {acad_seme})。\n"
                f"點擊 🔔 即可加入 {new_role.mention} 身份組以接收通知。"
            )
            await creation_message.add_reaction("🔔")
            
            await send_reply("✅ 任務已在通知頻道建立！", ephemeral=True)

            # --- 步驟 7：執行即時檢查 (保持不變) ---
            status_data = await asyncio.to_thread(_get_course_status, course_id, acad_seme)
            new_status = "ERROR"
            if status_data is None:
                await target_channel.send(f"❌ 無法抓取課程 `{course_id}` 的初始狀態。爬蟲可能失敗或課號錯誤。")
            else:
                current_count = status_data['current']
                max_count = status_data['max']
                new_status = "AVAILABLE" if current_count < max_count else "FULL"

            # --- 步驟 8：更新 JSON (保持不變) ---
            # (我們只修改通知，暫不修改 JSON 存儲)
            monitor_list = self._load_monitor_list() 
            for job in monitor_list:
                if job['course_id'] == course_id and job['acad_seme'] == acad_seme:
                    job['last_status'] = new_status
                    job['reaction_message_id'] = creation_message.id
                    break
            self._save_monitor_list(monitor_list) 

            # --- 步驟 9：發送初始狀態 (🆕 已修改) ---
            if status_data:
                user_mention = f"{new_role.mention}" 
                # 🆕 獲取課程名稱
                course_name = status_data.get('course_name', course_id)
                
                if new_status == "AVAILABLE":
                    embed_title = "🟢 初始狀態：有空位"
                    # 🆕 修改 Embed 描述
                    embed_desc = f"監測的課程 **{course_name}** (`{course_id}`) (學期: {acad_seme}) **目前有空位！**"
                    embed_color = 0x32CD32
                else: # new_status == "FULL"
                    embed_title = "🔴 初始狀態：已額滿"
                    # 🆕 修改 Embed 描述
                    embed_desc = f"監測的課程 **{course_name}** (`{course_id}`) (學期: {acad_seme}) **目前已額滿。**"
                    embed_color = 0xAAAAAA

                embed = discord.Embed(title=embed_title, description=embed_desc, color=embed_color)
                embed.add_field(name="當前人數 (Sel.)", value=f"**{current_count}** 人", inline=True)
                embed.add_field(name="限制人數 (Max)", value=f"**{max_count}** 人", inline=True)
                
                await target_channel.send(user_mention, embed=embed)

        except asyncio.TimeoutError:
            await send_reply("⌛ 已逾時，請重新執行指令。", ephemeral=True)
        except Exception as e:
            await send_reply(f"發生錯誤：{e}", ephemeral=True)
            logging.error(f"add_monitor_job 發生未處理的錯誤: {e}", exc_info=True)

    # --- (update_monitor_job - N) ---
    @monitor.command(name='update', aliases=['更新學期'], description="更新一個已存在任務的學期碼")
    @app_commands.describe(course_id="要更新的課號", new_acad_seme="新的學期碼 (例如 1141)")
    @commands.has_permissions(manage_roles=True) 
    async def update_monitor_job(self, ctx: commands.Context, course_id: str, new_acad_seme: str):
        is_private = ctx.interaction is not None
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
            await ctx.send(f"✅ **已更新**監測任務：\n**課號:** `{course_id}`\n**學期:** 從 `{old_seme}` 更新為 `{new_acad_seme}`。", ephemeral=is_private)
        else:
            await ctx.send(f"❌ 錯誤：監測清單中找不到課號 `{course_id}`。請先使用 `#monitor add` 新增。", ephemeral=True)

    # --- (remove_monitor_job - 保持不變) ---
    @monitor.command(name='remove', aliases=['移除', '刪除'], description="移除一個課程人數監測任務")
    @app_commands.describe(course_id="要移除的課號 (將移除所有學期)")
    @commands.has_permissions(manage_roles=True) 
    async def remove_monitor_job(self, ctx: commands.Context, course_id: str):
        is_private = ctx.interaction is not None
        if not ctx.guild.me.guild_permissions.manage_roles:
            return await ctx.send("❌ 錯誤：Bot 需要「管理身份組 (Manage Roles)」權限才能刪除身份組。", ephemeral=True)
        monitor_list = self._load_monitor_list()
        roles_to_delete = []
        messages_to_clean = [] 
        jobs_to_keep = []
        for job in monitor_list:
            if job['course_id'] == course_id:
                if 'role_id' in job: roles_to_delete.append(job['role_id'])
                if job.get('reaction_message_id'): messages_to_clean.append((job['channel_id'], job['reaction_message_id'], job.get('role_id')))
            else:
                jobs_to_keep.append(job)
        removed_count = len(monitor_list) - len(jobs_to_keep)
        if removed_count == 0:
            return await ctx.send(f"❌ 錯誤：監測清單中找不到課號 `{course_id}`。", ephemeral=True)
        self._save_monitor_list(jobs_to_keep)
        for channel_id, msg_id, role_id in set(messages_to_clean):
            try:
                channel = self.bot.get_channel(channel_id)
                if channel:
                    msg = await channel.fetch_message(msg_id)
                    role_name = f"`@{role_id}`"
                    if role_id:
                        role = ctx.guild.get_role(role_id)
                        if role: role_name = f"`@{role.name}`"
                    await msg.edit(content=f"❌ 此監測任務 (課號 `{course_id}`, 身份組 {role_name}) **已被移除**。\n此訊息的 🔔 表情符號已失效。", embed=None)
                    await msg.clear_reaction("🔔")
            except Exception as e:
                logging.warning(f"清理表情符號訊息 {msg_id} 時失敗: {e}")
        deleted_roles_count = 0
        for role_id in set(roles_to_delete): 
            role = ctx.guild.get_role(role_id)
            if role:
                try:
                    await role.delete(reason=f"由 {ctx.author} 移除監測任務")
                    deleted_roles_count += 1
                except Exception as e:
                    logging.error(f"刪除身份組 {role.name} (ID: {role_id}) 時發生錯誤: {e}")
        await ctx.send(f"✅ 成功移除課號 `{course_id}` 的 {removed_count} 個監測任務，清理了 {len(set(messages_to_clean))} 則反應訊息，並刪除了 {deleted_roles_count} 個相關身份組。", ephemeral=is_private)

    # --- (list_monitor_jobs - 保持不變) ---
    # (我們暫時還沒把 course_name 存入 json，所以 list 不變)
    @monitor.command(name='list', aliases=['清單'], description="顯示所有當前的監測任務")
    async def list_monitor_jobs(self, ctx: commands.Context):
        is_private = ctx.interaction is not None
        monitor_list = self._load_monitor_list()
        if not monitor_list:
            return await ctx.send("目前沒有任何課程監測任務。", ephemeral=is_private)
        
        embed = discord.Embed(
            title="📚 當前課程人數監測清單",
            description=f"總計 {len(monitor_list)} 個任務。 (目前 `/monitor add` 預設學期為: **{self.default_acad_seme}**)",
            color=0x4682B4
        )
        
        for job in monitor_list:
            last_status_str = job.get('last_status', '尚未檢查')
            if last_status_str == "AVAILABLE": last_status_str = "🟢 有空位"
            elif last_status_str == "FULL": last_status_str = "🔴 已額满"
            elif last_status_str == "ERROR": last_status_str = "❌ 抓取失敗"
            
            # 🆕 (未來優化：如果您決定在 check_enrollment 中儲存 course_name，可以在此處顯示)
            # course_name_str = job.get('course_name', '')
            # name_field = f"課號: {job['course_id']} (學期: {job['acad_seme']})\n課程名稱: **{course_name_str}**"
            
            role_mention = f"<@&{job['role_id']}>" if 'role_id' in job else "N/A"
            msg_link = "N/A"
            if job.get('reaction_message_id') and job.get('channel_id'):
                guild_id_str = f"{ctx.guild.id}/" if ctx.guild else ""
                msg_link = f"[點此前往](https://discord.com/channels/{guild_id_str}{job['channel_id']}/{job['reaction_message_id']})"
            
            embed.add_field(
                name=f"課號: {job['course_id']} (學期: {job['acad_seme']})",
                value=(f"目前狀態: **{last_status_str}**\n"
                       f"通知身份組: {role_mention}\n"
                       f"反應訊息: {msg_link}\n"
                       f"設定者: <@{job['user_id']}>"),
                inline=False
            )
        await ctx.send(embed=embed, ephemeral=is_private)

async def setup(bot):
    await bot.add_cog(EnrollmentMonitor(bot))