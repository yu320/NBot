import discord
from discord.ext import commands
from core.classes import Cog_Extension
import datetime
import asyncio
import os 
import logging 
from discord import app_commands # ✅ 1. 引入 app_commands

# 從環境變數讀取 CHANNEL_ID
TALK_CHANNEL_ID = os.getenv('CHANNEL_ID')


class Main(Cog_Extension):
    
    # ✅ 2. 改為 @commands.hybrid_command()
    @commands.hybrid_command(
        name="ping", 
        description="測試機器人的延遲 (ms)" # / 指令需要描述
    )
    async def ping(self, ctx: commands.Context):
        """測試機器人的延遲 (ms)"""
        
        # ✅ 3. 加入 ephemeral=True (私人回覆)
        # 當使用 /ping 時，這則訊息只有使用者自己看得到
        # 當使用 #ping 時，ephemeral 會被自動忽略，訊息會公開
        await ctx.send(f'{round(self.bot.latency*1000)} (ms)', ephemeral=True)

    
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
        
        # 確保 TALK_CHANNEL_ID 是一個有效的數字
        try:
            talk_channel_id = int(TALK_CHANNEL_ID)
        except (TypeError, ValueError):
            # ✅ 3. 加入 ephemeral=True
            await ctx.send("目前的頻道ID有問題需要更正 汪!", ephemeral=True)
            return
            
        talk_channel = self.bot.get_channel(talk_channel_id)
        
        if ctx.channel.id == talk_channel_id :
            # 刪除 num 條訊息 + 1 條指令訊息
            deleted = await ctx.channel.purge(limit = num + 1)
            
            # ✅ 3. 加入 ephemeral=True (私人回覆)
            # 
            # 附註：私人 (ephemeral) 訊息無法被 Bot 在 8 秒後刪除
            # 因此我們移除了 asyncio.sleep(8) 和後續的刪除
            await ctx.send(f"成功刪除 {len(deleted) - 1} 條訊息 汪!", ephemeral=True)
            
        else :
            # ✅ 3. 加入 ephemeral=True
            if talk_channel:
                await ctx.send(f"指令要在{talk_channel.mention}才可以用啦 汪!", ephemeral=True) 
            else:
                await ctx.send(f"指令要在機器人頻道才可以用啦 汪!", ephemeral=True)


    # ✅ 5. 錯誤監聽器 (修改為私人回覆)
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
                        f"`{ctx.prefix}{ctx.command.name} [數量]`\n"
                        f"**範例：** `{ctx.prefix}{ctx.command.name} 10`",
                        ephemeral=True # ✅ 設為私人
                    )
            
            # 處理 #clean 'num' 參數不是數字的錯誤
            elif isinstance(error, commands.BadArgument):
                if ctx.command.name == 'clean':
                    await ctx.send(
                        f"⚠️ **參數類型錯誤：** `數量` 必須是**數字**！\n"
                        f"**範例：** `{ctx.prefix}{ctx.command.name} 10`",
                        ephemeral=True # ✅ 設為私人
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