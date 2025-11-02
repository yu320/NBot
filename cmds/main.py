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
        description="測試機器人的延遲 (ms)" 
    )
    async def ping(self, ctx: commands.Context):
        """測試機器人的延遲 (ms)"""
        
        # ✅ 1. 檢查 ctx.interaction 是否存在
        # 如果是 / 指令 (ctx.interaction 存在)，則 ephemeral=True
        # 如果是 # 指令 (ctx.interaction 是 None)，則 ephemeral=False (即公開)
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
        
        # ✅ 1. 檢查是否為私人回覆
        is_private = ctx.interaction is not None

        # 確保 TALK_CHANNEL_ID 是一個有效的數字
        try:
            talk_channel_id = int(TALK_CHANNEL_ID)
        except (TypeError, ValueError):
            # ✅ 3. 加入 ephemeral=True
            await ctx.send("目前的頻道ID有問題需要更正 汪!", ephemeral=is_private)
            return
            
        talk_channel = self.bot.get_channel(talk_channel_id)
        
        if ctx.channel.id == talk_channel_id :
            # 刪除 num 條訊息 + 1 條指令訊息
            deleted = await ctx.channel.purge(limit = num + 1)
            
            # ✅ 2. 只有 / 指令的私人回覆才不能被刪除
            #    # 指令的公開回覆仍然可以被刪除
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
            # ✅ 3. 加入 ephemeral=True
            
            if talk_channel:
                await ctx.send(f"指令要在{talk_channel.mention}才可以用啦 汪!", ephemeral=is_private) 
            else:
                await ctx.send(f"指令要在機器人頻道才可以用啦 汪!", ephemeral=is_private)


    # ✅ 3. 錯誤監聽器 (修改為動態私人回覆)
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        logging.warning(f"Main Cog 捕獲到指令錯誤 (Command: {ctx.command}, Error: {error})")

        if ctx.command and ctx.command.name in ['clean', 'ping']:
            
            # 檢查是否為私人回覆
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
                pass
        
        else:
            if self.bot.extra_events.get('on_command_error', None) is not None:
                 await self.bot.on_command_error(ctx, error)
            else:
                 logging.error(f"Unhandled error in {ctx.command}: {error}")


async def setup(bot):
    await bot.add_cog(Main(bot))