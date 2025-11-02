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
# ✅ 1. 將 Bot 改為 commands.AutoShardedBot 
# (對於混合指令，使用 AutoShardedBot 或 Bot 皆可，這裡保持 Bot)
bot = commands.Bot(command_prefix='#' , intents = intents)

# 從環境變數獲取配置
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
UPTIME_KUMA_URL = os.getenv('UPTIME_KUMA_URL')

# 設定心跳間隔 (秒)。建議比 Uptime Kuma 要求的間隔短一點。
HEARTBEAT_INTERVAL_SECONDS = 240 # 例如，每 4 分鐘 (240 秒) 發送一次

# --- PM2 擴展指令 (保持不變) ---
@bot.command()
@commands.is_owner() # 建議加上擁有者限制
async def load(ctx, extension):
    await bot.load_extension(f'cmds.{extension}')
    await ctx.send(f'load {extension} done')

@bot.command()
@commands.is_owner() # 建議加上擁有者限制
async def reload(ctx, extension):
    await bot.reload_extension(f'cmds.{extension}')
    await ctx.send(f'Re - load {extension} done')

@bot.command()
@commands.is_owner() # 建議加上擁有者限制
async def unload(ctx, extension):
    await bot.unload_extension(f'cmds.{extension}')
    await ctx.send(f'Un - load {extension} done')


# --- Uptime Kuma 心跳任務 ---
@tasks.loop(seconds=HEARTBEAT_INTERVAL_SECONDS)
async def send_heartbeat():
    """定期向 Uptime Kuma 發送 HTTP 請求以保持監控器為 'Up' 狀態，並傳送延遲數值"""
    if UPTIME_KUMA_URL:
        try:
            # 1. 計算延遲 (ping)
            latency_ms = round(bot.latency * 1000)
            
            # 2. 構造帶有 ping 參數的 URL
            heartbeat_url_with_ping = f"{UPTIME_KUMA_URL}{latency_ms}"
            
            # 使用 requests 發送 GET 請求 (在單獨線程中運行以避免阻塞)
            await asyncio.to_thread(requests.get, heartbeat_url_with_ping, timeout=10) 
            logging.info(f"Heartbeat sent successfully (Ping: {latency_ms}ms).") 
        except Exception as e:
            logging.warning(f"Failed to send heartbeat to Uptime Kuma: {e}")

# --- 啟動擴展模組 (保持不變) ---
async def load_extensions(bot):
    # 設置 cmds 資料夾的相對路徑
    cmds_dir = './cmds'
    if os.path.exists(cmds_dir):
        for filename in os.listdir(cmds_dir):
            if filename.endswith(".py"):
                try:
                    await bot.load_extension(f'cmds.{filename[:-3]}')
                    logging.info(f'Loaded extension: {filename[:-3]}')
                except Exception as e:
                    logging.error(f'Failed to load extension {filename[:-3]}: {e}')
    else:
        logging.error("The 'cmds' directory does not exist.")


@bot.event # 讓機器人上線並提示
async def on_ready():
    """機器人準備就緒時執行的事件"""
    
    # (您要求的日誌修改)
    logging.info(f">> bot is online  {bot.user.name} <<")
    
    # # 1. 發送 Discord 頻道上線通知
    if CHANNEL_ID:
        channel = bot.get_channel(int(CHANNEL_ID))
        if channel:
            await channel.send('我上線了 汪!')
        else:
            logging.warning(f"Channel ID {CHANNEL_ID} not found.")

    # 2. 啟動 Uptime Kuma 心跳任務
    if UPTIME_KUMA_URL and not send_heartbeat.is_running():
        send_heartbeat.start()
        logging.info("Uptime Kuma heartbeat task started.")

    # ✅ --- 3. 新增此區塊以同步 / 指令 ---
    try:
        # bot.tree.sync() 會讀取所有 hybrid_command 並註冊
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} application (/) commands.")
    except Exception as e:
        logging.error(f"Failed to sync application commands: {e}")


# --- 全域錯誤處理器 (捕捉 CommandNotFound 等) ---
@bot.event
async def on_command_error(ctx, error):
    """
    捕捉所有未被 Cog 處理的錯誤 (例如：指令未找到)。
    """
    
    # 1. 處理「指令未找到」錯誤
    if isinstance(error, commands.CommandNotFound):
        # 記錄為警告 (Warning)，因為這通常是使用者輸入錯誤
        logging.warning(
            f"指令未找到 (CommandNotFound): {ctx.author} (ID: {ctx.author.id}) "
            f"在頻道 #{ctx.channel.name} (Guild: {ctx.guild.name}) "
            f"嘗試使用: '{ctx.message.content}'"
        )
        # (當使用 / 時，CommandNotFound 通常不會觸發，這是 # 指令專用的)
    
    # 2. 處理其他所有未被 Cog 捕捉的「真正」錯誤
    else:
        # 將其記錄為嚴重錯誤 (Error)，並提供詳細上下文
        logging.error(
            f"未處理的全域錯誤 (Unhandled Global Error)!\n"
            f"指令: {ctx.command}\n"
            f"觸發者: {ctx.author} (ID: {ctx.author.id})\n"
            f"訊息: '{ctx.message.content}'\n"
            f"錯誤類型: {type(error).__name__}\n"
            f"錯誤訊息: {error}",
            exc_info=True # 附加完整的錯誤追蹤 (Traceback)
        )
        # 嘗試以私人訊息回覆使用者發生錯誤
        try:
            await ctx.send(f"❌ 發生了一個未知的內部錯誤，已通知管理員。", ephemeral=True)
        except discord.errors.InteractionResponded:
             await ctx.followup.send(f"❌ 發生了一個未知的內部錯誤，已通知管理員。", ephemeral=True)
        except Exception as e:
            logging.error(f"Failed to send error message to user: {e}")


if __name__ == "__main__":
    # 設定 logging 的基本配置
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # 確保 Token 存在再啟動
    if DISCORD_TOKEN:
        # 加載擴展模組
        asyncio.run(load_extensions(bot))
        # 啟動機器人
        bot.run(DISCORD_TOKEN)
    else:
        logging.critical("Error: DISCORD_TOKEN not found in environment variables. Bot startup aborted.")