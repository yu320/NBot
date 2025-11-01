import discord
from discord.ext import commands
from core.classes import Cog_Extension 
import os
import requests
import asyncio 

class Calendar(commands.Cog):
    
    def __init__(self, bot):
        # 繼承 Cog_Extension 的 __init__
        super().__init__() 
        self.bot = bot
        # 從環境變數讀取 GAS Web App URL
        self.gas_api_url = os.getenv('CALENDAR_API_URL')
        if not self.gas_api_url:
            print("警告：CALENDAR_API_URL 環境變數未設定，日曆新增功能將無法運作。")

    # =========================================================
    # ✅ 指令錯誤處理函式 (提供清晰的語法教學)
    # =========================================================
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        # 確保只處理 addevent 相關的指令錯誤
        if ctx.command and ctx.command.name in ['addevent', 'addcal', '增加行程', '增加行事曆', '新增行程', '新增行事曆', '增加活動', '新增活動']:
            
            # 遺漏必要參數錯誤 (例如: date_time, title)
            if isinstance(error, commands.MissingRequiredArgument):
                await ctx.send(
                    f"⚠️ **參數遺漏錯誤：** 您忘記提供 `{error.param.name}` 參數了！\n\n"
                    f"**👉 正確格式：**\n"
                    f"`#addevent \"YYYY-MM-DD [HH:MM]\" \"活動標題\" [持續時間(分)] [日曆代號]`\n"
                    f"**範例 (有時間)：** `#addevent \"2025-12-25 10:00\" \"聖誕節派對\" 120 school`\n"
                    f"**範例 (全天)：** `#addevent \"2025-12-24\" \"平安夜\"`"
                )
                
            # 參數類型錯誤 (例如: duration 不是數字)
            elif isinstance(error, commands.BadArgument):
                # 專門針對 duration 錯誤給出提示
                if 'duration' in str(error):
                    await ctx.send(
                        f"⚠️ **參數類型錯誤：** `持續時間` 必須是**數字**！\n"
                        f"請檢查您輸入的參數，確保 **時間和標題** 都用**雙引號 `\"`** 括起來，且 `持續時間` 是數字。"
                    )
                else:
                    await ctx.send(f"⚠️ **指令參數錯誤：** {error}\n請檢查您輸入的參數格式是否正確。")

            # 忽略其他錯誤，讓它繼續傳播給 bot.py 處理
            else:
                pass
        else:
            # 讓其他指令的錯誤繼續由 bot.py 或其他 Cog 處理
            # 這裡使用 self.bot.on_command_error 避免無限遞迴
            if self.bot.extra_events.get('on_command_error', None) is not None:
                 await self.bot.on_command_error(ctx, error)
            else:
                 raise error


    @commands.command(name='addevent', aliases=['addcal','增加行程','增加行事曆','新增行程','新增行事曆',"增加活動","新增活動"])
    # 權限檢查已註釋掉，讓一般用戶也能使用
    # @commands.has_permissions(administrator=True) 
    async def add_calendar_event(self, ctx, date_time: str, title: str, duration: int = 60, calendar_key: str = "default"):
        """
        新增一個 Google 日曆活動到 GAS Web App。
        指令格式: #addevent <YYYY-MM-DD [HH:MM]> <標題> [持續時間(分)] [日曆代號]
        """
        
        if not self.gas_api_url:
            return await ctx.send("❌ 機器人配置錯誤：未設定日曆 API 網址 (CALENDAR_API_URL)。")

        # 構造要發送給 GAS 的資料 (JSON 格式)
        payload = {
            "date_time": date_time,
            "title": title,
            "duration": duration,
            "calendar_id": calendar_key, # 傳遞給 GAS 進行日曆 ID 映射
            "description": f"由 Discord 用戶 {ctx.author.display_name} 在頻道 #{ctx.channel.name} 新增。",
            "location": f"Discord 伺服器: {ctx.guild.name}"
        }

        await ctx.send(f"正在向 Google Calendar 新增活動 `{title}`...")

        try:
            # 使用 asyncio.to_thread 在單獨執行緒中運行 requests.post
            r = await asyncio.to_thread(
                requests.post,
                self.gas_api_url, 
                json=payload, 
                timeout=10
            )
            
            if r.status_code == 200:
                gas_response = r.json()
                
                if gas_response.get("status") == "success":
                    message = gas_response.get("message")
                    link = gas_response.get("link")
                    await ctx.send(f"{message}\n[🔗 查看日曆活動]({link})")
                else:
                    # 增強 GAS 處理失敗的錯誤訊息
                    gas_error_message = gas_response.get('message', '未知錯誤')
                    await ctx.send(
                        f"❌ **日曆 API 處理失敗：** {gas_error_message}\n"
                        f"請檢查您輸入的日期/時間格式，或目標日曆 ID 是否正確，並確認 GAS 已部署最新版本。"
                    )
            else:
                # 增強網路請求失敗的錯誤訊息
                await ctx.send(
                    f"❌ **網路請求失敗：** HTTP 狀態碼 {r.status_code}\n"
                    f"請檢查機器人的網路連線，或確認 GAS Web App 的 URL 是否正確且已部署。"
                )

        except requests.exceptions.Timeout:
            await ctx.send("❌ **連線超時：** 連線到 Google Apps Script 伺服器超時。")
        except Exception as e:
            await ctx.send(f"❌ **程式碼錯誤：** 連線到 GAS 發生非預期錯誤: `{e}`")

async def setup(bot):
    await bot.add_cog(Calendar(bot))