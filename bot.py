import discord
from discord.ext import commands, tasks
import json # 雖然您不再使用 setting.json，但這個 import 仍然保留，以防您在其他地方使用
import asyncio
import os
import requests
from dotenv import load_dotenv # 引入 load_dotenv

# --- 讀取 .env 檔案 ---
load_dotenv()

# --- 核心設定 (從環境變數讀取) ---
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='#' , intents = intents)

# 從環境變數獲取配置
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
UPTIME_KUMA_URL = os.getenv('UPTIME_KUMA_URL')

# 設定心跳間隔 (秒)。建議比 Uptime Kuma 要求的間隔短一點。
HEARTBEAT_INTERVAL_SECONDS = 240 # 例如，每 4 分鐘 (240 秒) 發送一次

# --- PM2 擴展指令 (保持不變) ---
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


# --- Uptime Kuma 心跳任務 ---
@tasks.loop(seconds=HEARTBEAT_INTERVAL_SECONDS)
async def send_heartbeat():
    """定期向 Uptime Kuma 發送 HTTP 請求以保持監控器為 'Up' 狀態"""
    if UPTIME_KUMA_URL:
        try:
            # 使用 requests 發送 GET 請求 (在單獨線程中運行以避免阻塞)
            await asyncio.to_thread(requests.get, UPTIME_KUMA_URL, timeout=10)
            # print(f"Heartbeat sent successfully to Uptime Kuma.") # 可以取消註釋來檢查
        except Exception as e:
            print(f"Failed to send heartbeat to Uptime Kuma: {e}")


# --- 啟動擴展模組 (保持不變) ---
async def load_extensions(bot):
    # 設置 cmds 資料夾的相對路徑
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


@bot.event # 讓機器人上線並提示
async def on_ready():
    """機器人準備就緒時執行的事件"""
    print(">> bot is online <<")
    
    # # 1. 發送 Discord 頻道上線通知 (確保 CHANNEL_ID 存在)
    if CHANNEL_ID:
        channel = bot.get_channel(int(CHANNEL_ID))
        if channel:
            await channel.send('我上線了 汪!')
        else:
            print(f"Warning: Channel ID {CHANNEL_ID} not found.")

    # 2. 啟動 Uptime Kuma 心跳任務
    if UPTIME_KUMA_URL and not send_heartbeat.is_running():
        send_heartbeat.start()
        print("Uptime Kuma heartbeat task started.")


if __name__ == "__main__":
    # 確保 Token 存在再啟動
    if DISCORD_TOKEN:
        # 加載擴展模組
        asyncio.run(load_extensions(bot))
        # 啟動機器人
        bot.run(DISCORD_TOKEN)
    else:

        print("Error: DISCORD_TOKEN not found in environment variables. Bot startup aborted.")


