import discord
from discord.ext import commands
from core.classes import Cog_Extension 
import os
import requests
import asyncio 
import logging 
from discord import app_commands # 引入 app_commands

class Calendar(commands.Cog):
    
    def __init__(self, bot):
        super().__init__() 
        self.bot = bot
        self.gas_api_url = os.getenv('CALENDAR_API_URL')
        if not self.gas_api_url:
            logging.warning("警告：CALENDAR_API_URL 環境變數未設定，日曆新增功能將無法運作。")

    # =========================================================
    # ✅ 1. 指令錯誤處理函式 (修復重複報錯，並更新教學提示)
    # =========================================================
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        # 確保只有 'Calendar' Cog 處理自己的指令錯誤
        if ctx.command and ctx.command.cog_name != 'Calendar':
            return

        # (日誌只會記錄 Calendar Cog 的錯誤)
        logging.warning(f"Calendar Cog 捕獲到指令錯誤 (Command: {ctx.command}, Error: {error})")


        
        # 確保只處理 addevent 相關的指令錯誤
        if ctx.command and ctx.command.name in ['addevent', 'addcal', '增加行程', '增加行事曆', '新增行程', '新增行事曆', '增加活動', '新增活動']:
            
            is_private = ctx.interaction is not None

            # 遺漏必要參數錯誤 (例如: date_time, title)
            if isinstance(error, commands.MissingRequiredArgument):
                await ctx.send(
                    f"⚠️ **參數遺漏錯誤：** 您忘記提供 `{error.param.name}` 參數了！\n\n"
                    f"**👉 正確格式：**\n"
                    f"`{ctx.prefix}{ctx.command.name} \"YYYY-MM-DD [HH:MM]\" \"活動標題\" [持續時間(分)] [日曆代號] [地點]`\n" # ⬅️ 地點教學已更新
                    f"**範例 (有時間)：** `{ctx.prefix}{ctx.command.name} \"2025-12-25 10:00\" \"聖誕節派對\" 120 school \"某某會議室\"`\n"
                    f"**範例 (全天)：** `{ctx.prefix}{ctx.command.name} \"2025-12-24\" \"平安夜\"`",
                    ephemeral=is_private 
                )
                
            # 參數類型錯誤
            elif isinstance(error, commands.BadArgument):
                if 'duration' in str(error):
                    await ctx.send(
                        f"⚠️ **參數類型錯誤：** `持續時間` 必須是**數字**！\n"
                        f"請檢查您輸入的參數，確保 **時間和標題** 都用**雙引號 `\"`** 括起來，且 `持續時間` 是數字。",
                        ephemeral=is_private 
                    )
                else:
                    await ctx.send(f"⚠️ **指令參數錯誤：** {error}\n請檢查您輸入的參數格式是否正確。", ephemeral=is_private)

            else:
                pass # 讓其他錯誤傳遞

    # =========================================================
    # ✅ 2. 混合指令：新增地點參數，並修復 / 指令回覆
    # =========================================================
    @commands.hybrid_command(
        name='addevent', 
        aliases=['addcal','增加行程','增加行事曆','新增行程','新增行事曆',"增加活動","新增活動"],
        description="新增一個 Google 日曆活動到 GAS Web App"
    )
    @app_commands.describe(
        date_time="日期與時間 (格式: \"YYYY-MM-DD [HH:MM]\")",
        title="活動標題 (格式: \"我的標題\")",
        duration="持續時間 (分鐘) (預設 60)",
        calendar_key="日曆代號 (例如: default, school) (預設 default)",
        location="地點 (可選)" # ⬅️ / 指令參數說明
    )
    async def add_calendar_event(self, ctx: commands.Context, date_time: str, title: str, duration: int = 60, calendar_key: str = "default", location: str = ""):
        
        is_private = ctx.interaction is not None

        if not self.gas_api_url:
            return await ctx.send("❌ 機器人配置錯誤：未設定日曆 API 網址 (CALENDAR_API_URL)。", ephemeral=is_private)

        # 處理可選的地點參數 (若未提供，則使用 Discord 伺服器名稱)
        final_location = location if location else f"Discord 伺服器: {ctx.guild.name}"

        payload = {
            "date_time": date_time,
            "title": title,
            "duration": duration,
            "calendar_id": calendar_key, 
            "description": f"由 Discord 用戶 {ctx.author.display_name} 在頻道 #{ctx.channel.name} 新增。",
            "location": final_location # ⬅️ 傳遞給 GAS 的 Payload
        }

        # 發送「正在處理」訊息 (此訊息將被 / 指令視為 Interaction Response)
        original_message = await ctx.send(f"正在向 Google Calendar 新增活動 `{title}`...", ephemeral=is_private)

        try:
            # 執行 API 請求
            r = await asyncio.to_thread(
                requests.post,
                self.gas_api_url, 
                json=payload, 
                timeout=10
            )
            
            response_content = ""
            
            if r.status_code == 200:
                gas_response = r.json()
                
                if gas_response.get("status") == "success":
                    message = gas_response.get("message")
                    link = gas_response.get("link") 
                    
                    response_content = f"✅ {message}" + (f"\n[🔗 查看日曆活動]({link})" if link else "")

                else:
                    gas_error_message = gas_response.get('message', '未知錯誤')
                    response_content = (
                        f"❌ **日曆 API 處理失敗：** {gas_error_message}\n"
                        f"請檢查您輸入的日期/時間格式，或目標日曆 ID 是否正確。"
                    )
            else:
                response_content = (
                    f"❌ **網路請求失敗：** HTTP 狀態碼 {r.status_code}\n"
                    f"請檢查機器人的網路連線，或確認 GAS Web App 的 URL 是否正確。"
                )

        except requests.exceptions.Timeout:
            response_content = "❌ **連線超時：** 連線到 Google Apps Script 伺服器超時。"
        except Exception as e:
            error_detail = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
            response_content = f"❌ **程式碼錯誤：** 連線到 GAS 發生非預期錯誤: `{error_detail}`"

        # --- 執行回覆：統一使用編輯函式 (修復 / 指令顯示問題的關鍵) ---
        try:
            # 使用 .edit() 來替換 / 指令的「正在註冊」placeholder
            await original_message.edit(content=response_content, embed=None, view=None)
        except Exception as e:
            # 如果編輯失敗 (例如 Interaction 過期)，則嘗試發送新的訊息
            logging.error(f"編輯 original_message 失敗: {e}")
            if is_private:
                 # / 指令的備用回覆
                 await ctx.followup.send(response_content, ephemeral=True)
            else:
                 # # 指令的備用回覆
                 await ctx.send(response_content)

async def setup(bot):
    await bot.add_cog(Calendar(bot))
