import discord
from discord.ext import commands
from core.classes import Cog_Extension
import datetime
import asyncio
# import json # 不再需要，可以移除
import os # 新增，用於讀取環境變數
import logging # ✅ 1. 引入 logging 模組

# with open('Nbot\\setting.json', 'r', encoding = 'utf8') as jfile: # 移除此行
#     jdata = json.load(jfile) # 移除此行

# 從環境變數讀取 CHANNEL_ID
TALK_CHANNEL_ID = os.getenv('CHANNEL_ID')


class Main(Cog_Extension):
    
    @commands.command()
    async def ping(self, ctx):
        # !ping 指令不需要修改
        await ctx.send(f'{round(self.bot.latency*1000)} (ms)')

    @commands.command()
    async def clean(self, ctx, num : int):
        
        # 確保 TALK_CHANNEL_ID 是一個有效的數字
        try:
            talk_channel_id = int(TALK_CHANNEL_ID)
        except (TypeError, ValueError):
            await ctx.send("目前的頻道ID有問題需要更正 汪!")
            return
            
        talk_channel = self.bot.get_channel(talk_channel_id)
        
        if ctx.channel.id == talk_channel_id :
            # 刪除 num 條訊息 + 1 條指令訊息
            deleted = await ctx.channel.purge(limit = num + 1)
            
            # 為了避免在刪除指令訊息時出現錯誤，我們直接發送成功訊息
            await ctx.send(f"成功刪除 {len(deleted) - 1} 條訊息 汪!")

            # 在命令中使用 asyncio.sleep() 來暫停 8 秒
            await asyncio.sleep(8)
            
            # 刪除成功提示訊息
            await ctx.channel.purge(limit = 1)
            
        else :
            # 如果找不到頻道，則只顯示文字，否則使用 mention
            if talk_channel:
                await ctx.send(f"指令要在{talk_channel.mention}才可以用啦 汪!") 
            else:
                await ctx.send(f"指令要在機器人頻道才可以用啦 汪!")


    # ✅ 2. 新增 on_command_error 錯誤監聽器
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        # 優先記錄所有進入此 Cog 的錯誤
        logging.warning(f"Main Cog 捕獲到指令錯誤 (Command: {ctx.command}, Error: {error})")

        # 確保只處理 'clean' 和 'ping' 相關的指令錯誤
        if ctx.command and ctx.command.name in ['clean', 'ping']:
            
            # 處理 #clean 遺漏 'num' 參數的錯誤
            if isinstance(error, commands.MissingRequiredArgument):
                if ctx.command.name == 'clean':
                    await ctx.send(
                        f"⚠️ **參數遺漏錯誤：** 您忘記提供 `要刪除的數量` 參數了！\n\n"
                        f"**👉 正確格式：**\n"
                        f"`#clean [數量]`\n"
                        f"**範例：** `#clean 10`"
                    )
            
            # 處理 #clean 'num' 參數不是數字的錯誤
            elif isinstance(error, commands.BadArgument):
                if ctx.command.name == 'clean':
                    await ctx.send(
                        f"⚠️ **參數類型錯誤：** `數量` 必須是**數字**！\n"
                        f"**範例：** `#clean 10`"
                    )
            
            # 其他錯誤（例如權限不足）將被忽略，並交由 bot.py 的全域處理器記錄
            else:
                pass
        
        else:
            # 讓其他指令的錯誤繼續由 bot.py 或其他 Cog 處理
            if self.bot.extra_events.get('on_command_error', None) is not None:
                 await self.bot.on_command_error(ctx, error)
            else:
                 # 如果沒有其他監聽器，則引發錯誤
                 logging.error(f"Unhandled error in {ctx.command}: {error}")


async def setup(bot):
    await bot.add_cog(Main(bot))