import discord
from discord.ext import commands
import json
import asyncio
import os

with open('setting.json', 'r', encoding='utf8') as jfile:
    jdata = json.load(jfile)

intents = discord.Intents.all() #如果沒有這行機器人沒有權限
bot = commands.Bot(command_prefix='!' , intents = intents)

@bot.command()
async def load(ctx, extension):
    await bot.load_extension(f'cmds.{extension}')
    await ctx.send(f'load {extension} done')

@bot.command()
async def reload(ctx, extension):
    await bot.reload_extension(f'cmds.{extension}')
    await ctx.send(f'Re - load {extension} done')

@bot.command()
async def unload(ctx, extension):
    await bot.unload_extension(f'cmds.{extension}')
    await ctx.send(f'Un - load {extension} done')


async def load_extensions(bot):
    # 設置 cmds 資料夾的絕對路徑
    cmds_dir = './cmds'
    if os.path.exists(cmds_dir):
        for filename in os.listdir(cmds_dir):
            if filename.endswith(".py"):
                try:
                    await bot.load_extension(f'cmds.{filename[:-3]}')
                    print(f'Loaded extension: {filename[:-3]}')
                except Exception as e:
                    print(f'Failed to load extension {filename[:-3]}: {e}')
    else:
        print("The 'cmds' directory does not exist.")

@bot.event #讓機器人上線並提示
async def on_ready():
    channel = bot.get_channel(int(jdata['channel']))
    await channel.send('我上線啦!')
    print(">> bot is online <<")


if __name__ == "__main__":
    # 加載擴展模組
    asyncio.run(load_extensions(bot))
    # 啟動機器人
    bot.run(jdata['token'])