import discord
from discord.ext import commands
from core.classes import Cog_Extension
import datetime
import asyncio
# import json # 不再需要，可以移除
import os 
import logging 
from discord import app_commands 
from typing import List # 👈 
# with open('Nbot\\setting.json', 'r', encoding = 'utf8') as jfile: # 移除此行
#     jdata = json.load(jfile) # 移除此行

# 移除舊的單一頻道 ID 讀取
# TALK_CHANNEL_ID = os.getenv('CHANNEL_ID') 


class Main(Cog_Extension):

    # 🆕 1. 新增 __init__ 方法來讀取 .env
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.allowed_clean_channels: List[int] = []
        
        # 讀取 .env 中的 CLEAN_ALLOWED_CHANNELS
        allowed_ids_str = os.getenv('CLEAN_ALLOWED_CHANNELS') # e.g., "123,456,789"
        
        if allowed_ids_str:
            try:
                # 將 "123, 456" 這樣的字串轉換為 [123, 456] 這樣的整數列表
                self.allowed_clean_channels = [int(ch_id.strip()) for ch_id in allowed_ids_str.split(',')]
                logging.info(f"[Main Cog] 'clean' 指令已被限制於 {len(self.allowed_clean_channels)} 個頻道: {self.allowed_clean_channels}")
            except ValueError:
                logging.error("[Main Cog] CLEAN_ALLOWED_CHANNELS 格式錯誤. 請使用逗號分隔的 ID (e.g., 123,456).")
        else:
            # 如果 .env 中沒有設定，則 'clean' 指令將在任何地方都無法使用
            logging.error("[Main Cog] 警告：未設定 CLEAN_ALLOWED_CHANNELS. 'clean' 指令將無法在任何頻道使用。")


    # --- PING (保持不變) ---
    @commands.hybrid_command(
        name="ping", 
        description="測試機器人的延遲 (ms)" 
    )
    async def ping(self, ctx: commands.Context):
        """測試機器人的延遲 (ms)"""
        
        # ✅ 3. 檢查是否為私人回覆
        is_private = ctx.interaction is not None
        await ctx.send(f'{round(self.bot.latency*1000)} (ms)', ephemeral=is_private)

    
    # --- CLEAN (已修改為支援多頻道) ---
    @commands.hybrid_command(
        name="clean",
        description="刪除指定數量的訊息 (僅限特定頻道)"
    )
    @app_commands.describe(
        num="要刪除的訊息數量"
    )
    async def clean(self, ctx: commands.Context, num : int):
        """刪除指定數量的訊息 (僅限特定頻道)"""
        
        # ✅ 3. 檢查是否為私人回覆
        is_private = ctx.interaction is not None

        # 🆕 2. 檢查當前頻道 ID 是否在 self.allowed_clean_channels 列表中
        if ctx.channel.id in self.allowed_clean_channels :
            # 刪除 num 條訊息 + 1 條指令訊息
            deleted = await ctx.channel.purge(limit = num + 1)
            
            # ✅ 5. 根據是否私人回覆，決定是否自動刪除
            response_msg = await ctx.send(f"成功刪除 {len(deleted) - 1} 條訊息 汪!", ephemeral=is_private)
            
            if not is_private: # 如果是 # 指令 (公開)
                # 在命令中使用 asyncio.sleep() 來暫停 8 秒
                await asyncio.sleep(8)
                
                # 刪除成功提示訊息
                try:
                    await response_msg.delete()
                except discord.NotFound:
                    pass # 訊息可能已被手動刪除
            
        else :
            # 🆕 3. 建立一個友善的、可點擊的頻道列表
            allowed_mentions = [f"<#{ch_id}>" for ch_id in self.allowed_clean_channels]
            
            if allowed_mentions:
                await ctx.send(f"指令要在 {', '.join(allowed_mentions)} 才可以用啦 汪!", ephemeral=is_private) 
            else:
                await ctx.send(f"指令要在指定的機器人頻道才可以用啦 汪! (管理員尚未設定)", ephemeral=is_private)


    # ✅ 6. 錯誤監聽器 (已修正重複報錯)
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        # ✅ 關鍵修正：如果指令不屬於 'Main' Cog，就直接退出
        if ctx.command and ctx.command.cog_name != 'Main':
            return

        # (日誌只會記錄 Main Cog 的錯誤)
        logging.warning(f"Main Cog 捕獲到指令錯誤 (Command: {ctx.command}, Error: {error})")

        # (只處理 clean 和 ping 的錯誤)
        if ctx.command and ctx.command.name in ['clean', 'ping']:
            
            is_private = ctx.interaction is not None
            
            if isinstance(error, commands.MissingRequiredArgument):
                if ctx.command.name == 'clean':
                    await ctx.send(
                        f"⚠️ **參數遺漏錯誤：** 您忘記提供 `要刪除的數量` 參數了！\n\n"
                        f"**👉 正確格式：**\n"
                        f"`{ctx.prefix}{ctx.command.name} [數量]`\n"
                        f"**範例：** `{ctx.prefix}{ctx.command.name} 10`",
                        ephemeral=is_private
                    )
            
            elif isinstance(error, commands.BadArgument):
                if ctx.command.name == 'clean':
                    await ctx.send(
                        f"⚠️ **參數類型錯誤：** `數量` 必須是**數字**！\n"
                        f"**範例：** `{ctx.prefix}{ctx.command.name} 10`",
                        ephemeral=is_private
                    )
            
            else:
                # 如果是 Main Cog 的其他錯誤 (例如權限不足)，
                # 'pass' 讓錯誤自動上報給 bot.py 的全域處理器
                pass
        
        # ✅ 關鍵修正：移除了手動呼叫 bot.py 處理器的 'else' 區塊


async def setup(bot):
    await bot.add_cog(Main(bot))