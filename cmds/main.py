import discord
from discord.ext import commands
from core.classes import Cog_Extension
import datetime
import asyncio
import json

with open('Nbot\\setting.json', 'r', encoding = 'utf8') as jfile:
    jdata = json.load(jfile)


class Main(Cog_Extension):
    
    @commands.command()
    async def ping(self, ctx):
        await ctx.send(f'{round(self.bot.latency*1000)} (ms)')

    @commands.command()
    async def clean(self, ctx,num : int):
        talk_channel_id = int(jdata['channel'])
        talk_channel = self.bot.get_channel(talk_channel_id)
        
        if ctx.channel.id == talk_channel_id :
            await ctx.channel.purge(limit = num+1)
            await ctx.send("成功刪除囉!")
            # 在命令中使用 asyncio.sleep() 來暫停 5 秒
            await asyncio.sleep(5)
            await ctx.channel.purge(limit = 1)
        else :
            await ctx.send(f"指令要在{talk_channel.mention}才可以用啦!") 

async def setup(bot):
    await bot.add_cog(Main(bot))