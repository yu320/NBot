import discord
from discord.ext import commands
from core.classes import Cog_Extension
import datetime
import asyncio
# import json # 不再需要，可以移除
import os 
import logging 
from discord import app_commands # ✅ 1. 引入 app_commands
# with open('Nbot\\setting.json', 'r', encoding = 'utf8') as jfile: # 移除此行
#     jdata = json.load(jfile) # 移除此行

# 從環境變數讀取 CHANNEL_ID
# 確保您的 .env 檔案中有 CHANNEL_ID="YOUR_CHANNEL_ID"
TALK_CHANNEL_ID = os.getenv('CHANNEL_ID')


class Main(Cog_Extension):
    
    # ✅ 2. 改為 @commands.hybrid_command()
    @commands.hybrid_command(
        name="ping", 
        description="測試機器人的延遲 (ms)" # / 指令需要描述
    )
    async def ping(self, ctx: commands.Context):
        """測試機器人的延遲 (ms)"""
        
        # ✅ 3. 檢查是否為私人回覆
        is_private = ctx.interaction is not None
        
        await ctx.send(f'{round(self.bot.latency*1000)} (ms)', ephemeral=is_private)

    
    # ✅ 2. 改為 @commands.hybrid_command()
    @commands.hybrid_command(
        name="clean",
        description="刪除指定數量的訊息 (僅限特定頻道)"
    )
    # ✅ 4. 為 / 指令的「參數」加上描述
    @app_commands.describe(
        num="要刪除的訊息數量"
    )
    async def clean(self, ctx: commands.Context, num : int):
        """刪除指定數量的訊息 (僅限特定頻道)"""
        
        # ✅ 3. 檢查是否為私人回覆
        is_private = ctx.interaction is not None

        # 確保 TALK_CHANNEL_ID 是一個有效的數字
        try:
            talk_channel_id = int(TALK_CHANNEL_ID)
        except (TypeError, ValueError):
            await ctx.send("目前的頻道ID有問題需要更正 汪!", ephemeral=is_private)
            return
            
        talk_channel = self.bot.get_channel(talk_channel_id)
        
        if ctx.channel.id == talk_channel_id :
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
            if talk_channel:
                await ctx.send(f"指令要在{talk_channel.mention}才可以用啦 汪!", ephemeral=is_private) 
            else:
                await ctx.send(f"指令要在機器人頻道才可以用啦 汪!", ephemeral=is_private)


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