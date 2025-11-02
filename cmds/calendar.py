import discord
from discord.ext import commands
from core.classes import Cog_Extension 
import os
import requests
import asyncio 
import logging 
from discord import app_commands # ✅ 1. 引入 app_commands

class Calendar(commands.Cog):
    
    def __init__(self, bot):
        # 繼承 Cog_Extension
        super().__init__() 
        self.bot = bot
        # 從環境變數讀取 GAS Web App URL
        self.gas_api_url = os.getenv('CALENDAR_API_URL')
        if not self.gas_api_url:
            logging.warning("警告：CALENDAR_API_URL 環境變數未設定，日曆新增功能將無法運作。")

    # =========================================================
    # ✅ 指令錯誤處理函式 (已修正重複報錯)
    # =========================================================
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        # ✅ 關鍵修正：如果指令不屬於 'Calendar' Cog，就直接退出
        if ctx.command and ctx.command.cog_name != 'Calendar':
            return

        # (日誌只會記錄 Calendar Cog 的錯誤)
        logging.warning(f"Calendar Cog 捕獲到指令錯誤 (Command: {ctx.command}, Error: {error})")

        # 確保只處理 addevent 相關的指令錯誤
        if ctx.command and ctx.command.name in ['addevent', 'addcal', '增加行程', '增加行事曆', '新增行程', '新增行事曆', '增加活動', '新增活動']:
            
            # 檢查是否為私人回覆
            is_private = ctx.interaction is not None

            # 遺漏必要參數錯誤 (例如: date_time, title)
            if isinstance(error, commands.MissingRequiredArgument):
                await ctx.send(
                    f"⚠️ **參數遺漏錯誤：** 您忘記提供 `{error.param.name}` 參數了！\n\n"
                    f"**👉 正確格式：**\n"
                    f"`{ctx.prefix}{ctx.command.name} \"YYYY-MM-DD [HH:MM]\" \"活動標題\" [持續時間(分)] [日曆代號]`\n"
                    f"**範例 (有時間)：** `{ctx.prefix}{ctx.command.name} \"2025-12-25 10:00\" \"聖誕節派對\" 120 school`\n"
                    f"**範例 (全天)：** `{ctx.prefix}{ctx.command.name} \"2025-12-24\" \"平安夜\"`",
                    ephemeral=is_private 
                )
                
            # 參數類型錯誤 (例如: duration 不是數字)
            elif isinstance(error, commands.BadArgument):
                # 專門針對 duration 錯誤給出提示
                if 'duration' in str(error):
                    await ctx.send(
                        f"⚠️ **參數類型錯誤：** `持續時間` 必須是**數字**！\n"
                        f"請檢查您輸入的參數，確保 **時間和標題** 都用**雙引號 `\"`** 括起來，且 `持續時間` 是數字。",
                        ephemeral=is_private 
                    )
                else:
                    await ctx.send(f"⚠️ **指令參數錯誤：** {error}\n請檢查您輸入的參數格式是否正確。", ephemeral=is_private)

            # 忽略其他錯誤，讓它繼續傳播 (上報給 bot.py)
            else:
                pass
        
        # ✅ 關鍵修正：移除了手動呼叫 bot.py 處理器的 'else' 區塊


    # ✅ 2. 改為 @commands.hybrid_command()
    @commands.hybrid_command(
        name='addevent', 
        aliases=['addcal','增加行程','增加行事曆','新增行程','新增行事曆',"增加活動","新增活動"],
        description="新增一個 Google 日曆活動到 GAS Web App"
    )
    # ✅ 3. 為 / 指令的「參數」加上描述
    @app_commands.describe(
        date_time="日期與時間 (格式: \"YYYY-MM-DD [HH:MM]\")",
        title="活動標題 (格式: \"我的標題\")",
        duration="持續時間 (分鐘) (預設 60)",
        calendar_key="日曆代號 (例如: default, school) (預設 default)"
    )
    async def add_calendar_event(self, ctx: commands.Context, date_time: str, title: str, duration: int = 60, calendar_key: str = "default"):
        """
        新增一個 Google 日曆活動到 GAS Web App。
        指令格式: #addevent <YYYY-MM-DD [HH:MM]> <標題> [持續時間(分)] [日曆代號]
        """
        
        # ✅ 檢查是否為私人回覆
        is_private = ctx.interaction is not None

        if not self.gas_api_url:
            return await ctx.send("❌ 機器人配置錯誤：未設定日曆 API 網址 (CALENDAR_API_URL)。", ephemeral=is_private)

        # 構造要發送給 GAS 的資料 (JSON 格式)
        payload = {
            "date_time": date_time,
            "title": title,
            "duration": duration,
            "calendar_id": calendar_key, # 傳遞給 GAS 進行日曆 ID 映射
            "description": f"由 Discord 用戶 {ctx.author.display_name} 在頻道 #{ctx.channel.name} 新增。",
            "location": f"Discord 伺服器: {ctx.guild.name}"
        }

        # 發送「正在處理」訊息
        original_message = await ctx.send(f"正在向 Google Calendar 新增活動 `{title}`...", ephemeral=is_private)

        try:
            # 使用 asyncio.to_thread 在單獨執行緒中運行 requests.post
            r = await asyncio.to_thread(
                requests.post,
                self.gas_api_url, 
                json=payload, 
                timeout=10
            )
            
            response_content = "" # 準備回覆的內容
            
            if r.status_code == 200:
                gas_response = r.json()
                
                if gas_response.get("status") == "success":
                    message = gas_response.get("message")
                    link = gas_response.get("link") # 這裡會收到 null (None)
                    
                    response_content = f"{message}" + (f"\n[🔗 查看日曆活動]({link})" if link else "")

                else:
                    # 增強 GAS 處理失敗的錯誤訊息
                    gas_error_message = gas_response.get('message', '未知錯誤')
                    response_content = (
                        f"❌ **日曆 API 處理失敗：** {gas_error_message}\n"
                        f"請檢查您輸入的日期/時間格式，或目標日曆 ID 是否正確。"
                    )
            else:
                # 增強網路請求失敗的錯誤訊息
                response_content = (
                    f"❌ **網路請求失敗：** HTTP 狀態碼 {r.status_code}\n"
                    f"請檢查機器人的網路連線，或確認 GAS Web App 的 URL 是否正確。"
                )

        except requests.exceptions.Timeout:
            response_content = "❌ **連線超時：** 連線到 Google Apps Script 伺服器超時。"
        except Exception as e:
            response_content = f"❌ **程式碼錯誤：** 連線到 GAS 發生非預期錯誤: `{e}`"

        # --- ✅ 執行回覆 ---
        if is_private:
            # / 指令 (私人)：使用 followup 編輯「思考中」訊息
            await ctx.followup.send(response_content, ephemeral=True)
        else:
            # # 指令 (公開)：編輯原始訊息
            await original_message.edit(content=response_content)

async def setup(bot):
    await bot.add_cog(Calendar(bot))