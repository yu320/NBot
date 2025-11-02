import discord
from discord.ext import commands, tasks
import json
import asyncio
import os
import requests
from dotenv import load_dotenv # 引入 load_dotenv
import logging # 引入 logging 模組

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


# --- # --- Uptime Kuma 心跳任務 ---
@tasks.loop(seconds=HEARTBEAT_INTERVAL_SECONDS)
async def send_heartbeat():
    """定期向 Uptime Kuma 發送 HTTP 請求以保持監控器為 'Up' 狀態，並傳送延遲數值"""
    if UPTIME_KUMA_URL:
        try:
            # 1. 計算延遲 (ping)
            # bot.latency 單位為秒，乘以 1000 得到毫秒 (ms)
            # 這裡的 bot 變數是在檔案頂層定義的 commands.Bot 實例
            latency_ms = round(bot.latency * 1000)
            
            # 2. 構造帶有 ping 參數的 URL
            # Uptime Kuma Push API 支持在 URL 中添加 ?status=up&ping=<ms>
            heartbeat_url_with_ping = f"{UPTIME_KUMA_URL}?status=up&msg=OK&ping={latency_ms}"
            
            # 使用 requests 發送 GET 請求 (在單獨線程中運行以避免阻塞)
            await asyncio.to_thread(requests.get, heartbeat_url_with_ping, timeout=10) 
            logging.info(f"Heartbeat sent successfully (Ping: {latency_ms}ms).") # 新增 logging
        except Exception as e:
            logging.warning(f"Failed to send heartbeat to Uptime Kuma: {e}") # ✅ 2. print 改 logging

# --- 啟動擴展模組 (保持不變) ---
async def load_extensions(bot):
    # 設置 cmds 資料夾的相對路徑
    cmds_dir = './cmds'
    if os.path.exists(cmds_dir):
        for filename in os.listdir(cmds_dir):
            if filename.endswith(".py"):
                try:
                    await bot.load_extension(f'cmds.{filename[:-3]}')
                    # ✅ 3. print 改 logging
                    logging.info(f'Loaded extension: {filename[:-3]}')
                except Exception as e:
                    # ✅ 4. print 改 logging
                    logging.error(f'Failed to load extension {filename[:-3]}: {e}')
    else:
        # ✅ 5. print 改 logging
        logging.error("The 'cmds' directory does not exist.")


@bot.event # 讓機器人上線並提示
async def on_ready():
    """機器人準備就緒時執行的事件"""
    logging.info(">> bot is online <<")
    
    # # 1. 發送 Discord 頻道上線通知 (確保 CHANNEL_ID 存在)
    if CHANNEL_ID:
        channel = bot.get_channel(int(CHANNEL_ID))
        if channel:
            await channel.send('我上線了 汪!')
        else:
            logging.warning(f"Channel ID {CHANNEL_ID} not found.")

    # 2. 啟動 Uptime Kuma 心跳任務
    if UPTIME_KUMA_URL and not send_heartbeat.is_running():
        send_heartbeat.start()
        # ✅ 7. print 改 logging
        logging.info("Uptime Kuma heartbeat task started.")


if __name__ == "__main__":
    # ✅ 8. 設定 logging 的基本配置
    # 這樣您的日誌才會顯示 INFO 等級
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # 確保 Token 存在再啟動
    if DISCORD_TOKEN:
        # 加載擴展模組
        asyncio.run(load_extensions(bot))
        # 啟動機器人
        bot.run(DISCORD_TOKEN)
    else:
        # ✅ 9. print 改 logging
        logging.critical("Error: DISCORD_TOKEN not found in environment variables. Bot startup aborted.")