import discord
from discord.ext import commands
from core.classes import Cog_Extension
import datetime
import asyncio
# import json # 不再需要，可以移除
import os # 新增，用於讀取環境變數

# with open('Nbot\\setting.json', 'r', encoding = 'utf8') as jfile: # 移除此行
#     jdata = json.load(jfile) # 移除此行

# 從環境變數讀取 CHANNEL_ID
# 確保您的 .env 檔案中有 CHANNEL_ID="YOUR_CHANNEL_ID"
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
            await ctx.send("錯誤：未正確設定 CHANNEL_ID。請檢查您的 .env 檔案。")
            return
            
        talk_channel = self.bot.get_channel(talk_channel_id)
        
        if ctx.channel.id == talk_channel_id :
            # 刪除 num 條訊息 + 1 條指令訊息
            deleted = await ctx.channel.purge(limit = num + 1)
            
            # 為了避免在刪除指令訊息時出現錯誤，我們直接發送成功訊息
            await ctx.send(f"成功刪除 {len(deleted) - 1} 條訊息囉!")

            # 在命令中使用 asyncio.sleep() 來暫停 8 秒
            await asyncio.sleep(8)
            
            # 刪除成功提示訊息
            await ctx.channel.purge(limit = 1)
            
        else :
            # 如果找不到頻道，則只顯示文字，否則使用 mention
            if talk_channel:
                await ctx.send(f"指令要在{talk_channel.mention}才可以用啦!") 
            else:
                await ctx.send(f"指令要在指定的頻道 (ID: {TALK_CHANNEL_ID}) 才可以用啦!")


async def setup(bot):
    await bot.add_cog(Main(bot))