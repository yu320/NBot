import discord
from discord.ext import commands
from core.classes import Cog_Extension # 假設 core/classes.py 已經在
import os
import requests
import asyncio # 用於非同步執行 requests.post

class Calendar(commands.Cog):
    
    def __init__(self, bot):
        # 繼承 Cog_Extension 的 __init__
        super().__init__() 
        self.bot = bot
        # 從環境變數讀取 GAS Web App URL
        # CALENDAR_API_URL 必須在步驟二中設定
        self.gas_api_url = os.getenv('CALENDAR_API_URL')
        if not self.gas_api_url:
            print("警告：CALENDAR_API_URL 環境變數未設定，日曆新增功能將無法運作。")

    @commands.command(name='addevent', aliases=['addcal','增加行程','增加行事曆','新增行程','新增行事曆',"增加活動","新增活動"])
    # 建議加上權限限制，例如：只有管理員能用
    # @commands.has_permissions(administrator=True) 
    async def add_calendar_event(self, ctx, date_time: str, title: str, duration: int = 60, calendar_key: str = "default"):
        """
        新增一個 Google 日曆活動到 GAS Web App。
        指令格式: #addevent <YYYY-MM-DD HH:MM> <標題> [持續時間(分)] [日曆代號]
        範例: #addevent 2025-11-05 10:00 期中考準備 90 school
        日曆代號: default, school, dorm (需在 GAS 中設定)
        """
        
        if not self.gas_api_url:
            return await ctx.send("❌ 機器人配置錯誤：未設定日曆 API 網址。")

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
            # 使用 asyncio.to_thread 在單獨執行緒中運行 requests.post，避免阻塞 Discord 事件迴圈
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
                    await ctx.send(f"❌ GAS 處理失敗: {gas_response.get('message', '未知錯誤')}")
            else:
                await ctx.send(f"❌ 網路請求失敗，HTTP 狀態碼: {r.status_code}\n返回內容: {r.text}")

        except Exception as e:
            await ctx.send(f"❌ 連線到 GAS 發生錯誤: {e}")

async def setup(bot):
    await bot.add_cog(Calendar(bot))