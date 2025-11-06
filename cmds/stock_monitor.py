import discord
from discord.ext import commands, tasks
from core.classes import Cog_Extension 
import json
import os
import asyncio
import logging
from datetime import time, datetime, timedelta
from typing import List, Dict, Any, Optional

# (修正點 1：引入 Python 內建的時區函式庫)
from zoneinfo import ZoneInfo

# --- 引入股票所需的核心函式庫 ---
import requests
import pandas as pd
# --------------------------------

# --- 設定常量 ---
STOCK_LIST_FILE = './data/stock_list.json' # 儲存股票代碼的檔案
PROXIMITY_THRESHOLD = 0.01 # 接近 MA20 的閾值 (1%)

# (修正點 2：建立一個明確的 "Asia/Taipei" 時區物件)
TAIWAN_TZ = ZoneInfo("Asia/Taipei")

# (修正點 3：將 "天真" 時間改為 "帶有時區" 的時間)
CHECK_TIME_TW = time(13, 0, 0, tzinfo=TAIWAN_TZ) # 每天台灣時間 12:00:00 執行

# 讀取通知頻道 ID 和身分組 ID
STOCK_MONITOR_CHANNEL_ID_STR = os.getenv('STOCK_MONITOR_CHANNEL_ID') 
STOCK_MONITOR_ROLE_ID_STR = os.getenv('STOCK_MONITOR_ROLE_ID') 


# =========================================================
# 股票資料核心處理函式 (保持不變)
# =========================================================

def _load_stock_list() -> List[str]:
    """
    從 JSON 檔案讀取股票清單。如果檔案不存在，會建立一個預設的範例檔案。
    """
    default_list = ["2330.TW", "AAPL"] 
    os.makedirs('./data', exist_ok=True)
    try:
        if not os.path.exists(STOCK_LIST_FILE):
             with open(STOCK_LIST_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_list, f, indent=2)
             logging.warning(f"警告: 找不到 {STOCK_LIST_FILE} 檔案。已建立包含 {default_list} 的範例檔案。")
             return default_list

        with open(STOCK_LIST_FILE, 'r', encoding='utf-8') as f:
            stock_list = json.load(f)
            if not isinstance(stock_list, list):
                logging.error(f"錯誤: {STOCK_LIST_FILE} 內的格式不是一個列表 (Array)。")
                return []
            return stock_list
            
    except Exception as e:
        logging.error(f"讀取 {STOCK_LIST_FILE} 失敗: {e}")
        return []

def _save_stock_list(stock_list: List[str]):
    """將股票清單存入檔案"""
    try:
        with open(STOCK_LIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(stock_list, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"儲存 {STOCK_LIST_FILE} 失敗: {e}")


def _fetch_stock_data(stock_id: str, range_='3mo', interval_='1d') -> Optional[pd.DataFrame]:
    """
    從 Yahoo Finance 抓取股票數據 (在獨立線程中執行)。
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_id}"
    params = {'range': range_, 'interval': interval_, 'region': 'TW', 'lang': 'zh-Hant-TW'}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36'}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        quote = result['indicators']['quote'][0]
        if not timestamps:
            logging.warning(f"[{stock_id}] 找不到資料。")
            return None
            
        dates = [datetime.fromtimestamp(ts) for ts in timestamps]
        clean_quote = {}
        for key in ['open', 'high', 'low', 'close', 'volume']:
            clean_quote[key] = [val if val is not None else float('nan') for val in quote[key]]
            
        df = pd.DataFrame({
            'Open': clean_quote['open'],
            'High': clean_quote['high'],
            'Low': clean_quote['low'],
            'Close': clean_quote['close'],
            'Volume': clean_quote['volume']
        }, index=pd.to_datetime(dates))
        df.dropna(inplace=True) 
        
        return df
    except Exception as e:
        logging.error(f"[錯誤] 抓取 {stock_id} 時發生錯誤: {e}")
        return None

def _analyze_signals(stock_id: str, df: pd.DataFrame, threshold_percent: float) -> List[Dict[str, Any]]:
    """
    分析股票訊號並返回通知列表。
    """
    signals = []
    
    if len(df) < 20:
        logging.info(f"[{stock_id}] 資料量不足 20 天，跳過分析。")
        return signals
        
    df['MA20'] = df['Close'].rolling(window=20).mean()
    
    try:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
    except IndexError:
        logging.warning(f"[{stock_id}] 資料量不足 2 天，無法比較。")
        return signals
        
    latest_date_str = latest.name.strftime('%Y-%m-%d')
    ma20 = latest['MA20']
    
    if pd.isna(ma20):
        logging.warning(f"[{stock_id}] MA20 數值為空，跳過。")
        return signals

    # 1. K棒「接觸」MA20
    if latest['Low'] <= ma20 <= latest['High']:
        signals.append({
            'type': '接觸',
            'title': 'K棒接觸 MA20',
            'detail': f"K棒 (H:{latest['High']:.2f} L:{latest['Low']:.2f}) 已碰觸 MA20 ({ma20:.2f})。",
            'color': discord.Color.gold()
        })
        
    # 2. "快接觸到" 
    else:
        # 快要漲碰到
        lower_bound = ma20 * (1.0 - threshold_percent)
        if (latest['High'] < ma20) and (latest['High'] >= lower_bound):
            distance = ma20 - latest['High']
            signals.append({
                'type': '接近',
                'title': '快要漲碰到 MA20',
                'detail': f"K棒高點 ({latest['High']:.2f}) 接近 MA20 ({ma20:.2f}), 僅差 {distance:.2f}。",
                'color': discord.Color.orange()
            })
            
        # 快要跌碰到
        upper_bound = ma20 * (1.0 + threshold_percent)
        if (latest['Low'] > ma20) and (latest['Low'] <= upper_bound):
            distance = latest['Low'] - ma20
            signals.append({
                'type': '接近',
                'title': '快要跌碰到 MA20',
                'detail': f"K棒低點 ({latest['Low']:.2f}) 接近 MA20 ({ma20:.2f}), 僅差 {distance:.2f}。",
                'color': discord.Color.orange()
            })

    # 3. K棒「穿越」MA20
    if not pd.isna(prev['MA20']):
        if latest['Close'] > ma20 and prev['Close'] < prev['MA20']:
            signals.append({
                'type': '穿越',
                'title': '🟡 黃金交叉 (站上 MA20)',
                'detail': f"收盤價 ({latest['Close']:.2f}) 站上 MA20 ({ma20:.2f})。",
                'color': discord.Color.green()
            })
        elif latest['Close'] < ma20 and prev['Close'] > prev['MA20']:
            signals.append({
                'type': '穿越',
                'title': '⚫ 死亡交叉 (跌破 MA20)',
                'detail': f"收盤價 ({latest['Close']:.2f}) 跌破 MA20 ({ma20:.2f})。",
                'color': discord.Color.red()
            })
            
    return signals


# =========================================================
# StockMonitor Cog 核心邏輯
# =========================================================

class StockMonitor(Cog_Extension):
    
    def __init__(self, bot):
        super().__init__(bot)
        
        self.notification_channel_id = None
        if STOCK_MONITOR_CHANNEL_ID_STR and STOCK_MONITOR_CHANNEL_ID_STR.isdigit():
            self.notification_channel_id = int(STOCK_MONITOR_CHANNEL_ID_STR)
        else:
            logging.error("STOCK_MONITOR_CHANNEL_ID 未設定或格式錯誤，股票監測通知將無法發送！")

        self.role_mention_tag = ""
        if STOCK_MONITOR_ROLE_ID_STR and STOCK_MONITOR_ROLE_ID_STR.isdigit():
            # 將 ID 轉換為 Discord 的 @身分組 格式
            self.role_mention_tag = f"<@&{STOCK_MONITOR_ROLE_ID_STR}>"
            logging.info(f"股票通知將會 @身分組 ID: {STOCK_MONITOR_ROLE_ID_STR}")
        else:
            logging.warning("STOCK_MONITOR_ROLE_ID 未設定或格式錯誤，通知將不會 @身分組。")

        # 啟動定時任務
        if self.notification_channel_id:
            self.daily_stock_check.start()
            # (修正點 4：在啟動日誌中顯示時區，確保無誤)
            logging.info(f"股票監測任務已啟動，預計每天 {CHECK_TIME_TW.isoformat()} (時區: {CHECK_TIME_TW.tzinfo}) 執行。")
        else:
            logging.warning("股票監測任務**未**啟動，因為缺少 STOCK_MONITOR_CHANNEL_ID。")
            
    def cog_unload(self):
        self.daily_stock_check.cancel()
        
    # --- 定時任務：每天 12:00 檢查 ---
    @tasks.loop(time=CHECK_TIME_TW)
    async def daily_stock_check(self):
        await self.bot.wait_until_ready()
        
        # (修正點 5：使用帶有時區的 "now" 來檢查星期)
        now_in_taiwan = datetime.now(TAIWAN_TZ)
        today = now_in_taiwan.weekday()
        
        if today >= 5: # 5: 星期六, 6: 星期日
            logging.info(f"本日 ({now_in_taiwan.strftime('%A')}) 為週末，跳過股票定時檢查任務。")
            return
        
        stock_list = _load_stock_list()
        target_channel = self.bot.get_channel(self.notification_channel_id)

        if not stock_list or not target_channel:
             logging.warning("股票清單為空或頻道不存在，定時檢查任務跳過。")
             return

        # 這裡的日誌現在一定會在 12:00 (台灣時間) 觸發
        logging.info(f"開始執行 {len(stock_list)} 支股票的定時檢查...")
        
        all_signals = [] # 儲存所有股票的訊號
        
        # 1. 批次抓取並分析
        for stock_id in stock_list:
            # 在獨立線程中執行耗時的 I/O 操作 (網路請求和 Pandas 計算)
            df = await asyncio.to_thread(_fetch_stock_data, stock_id)
            
            if df is not None:
                signals = await asyncio.to_thread(_analyze_signals, stock_id, df, PROXIMITY_THRESHOLD)
                
                if signals:
                    all_signals.extend([(stock_id, s) for s in signals])
            
            # 暫停 1 秒，避免 API 頻率限制
            await asyncio.sleep(1) 

        # 2. 統整並發送通知
        if all_signals:
            
            embed_title = f"📢 每日股票訊號報告 ({now_in_taiwan.strftime('%Y-%m-%d')})"
            embed = discord.Embed(
                title=embed_title,
                description=f"總共發現 **{len(all_signals)}** 個技術訊號。",
                color=discord.Color.blue()
            )
            
            for stock_id, signal in all_signals:
                embed.add_field(
                    name=f"📈 {stock_id}: {signal['title']}",
                    value=signal['detail'],
                    inline=False
                )
            
            # 設置底部資訊和時間戳
            embed.set_footer(text=f"分析基準: 3個月數據 / 1% 接近閾值")
            embed.timestamp = now_in_taiwan
            
            content = f"📢 {self.role_mention_tag} 發現 **{len(all_signals)}** 個股票訊號！" if self.role_mention_tag else "📢 發現股票訊號！"
            await target_channel.send(content=content, embed=embed)
            logging.info(f"成功發送 {len(all_signals)} 個股票訊號通知。")
            
        else:
            logging.info("所有監測股票均未發現新訊號。")
            
        logging.info("股票定時檢查任務結束。")

    # =========================================================
    # 指令群組：管理股票清單 (保持不變)
    # =========================================================
    
    @commands.hybrid_group(name='stock', aliases=['股票'], description="管理每日股票監測清單")
    async def stock(self, ctx: commands.Context):
        is_private = ctx.interaction is not None
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(title="📈 股票監測管理", description="管理每日定時檢查的股票代碼清單。", color=0x3498DB)
            embed.add_field(name=f"1. 新增股票", value=f"`{ctx.prefix}stock add <代碼>`", inline=False)
            embed.add_field(name=f"2. 移除股票", value=f"`{ctx.prefix}stock remove <代碼>`", inline=False)
            embed.add_field(name=f"3. 查看清單", value=f"`{ctx.prefix}stock list`", inline=False)
            embed.add_field(name=f"4. 手動檢查", value=f"`{ctx.prefix}stock check [代碼(選填)]`", inline=False)
            await ctx.send(embed=embed, ephemeral=is_private)
    
    @stock.command(name='add', aliases=['新增'], description="新增股票代碼到監測清單")
    async def stock_add(self, ctx: commands.Context, stock_id: str):
        is_private = ctx.interaction is not None
        stock_list = _load_stock_list()
        stock_id = stock_id.upper()
        
        if stock_id in stock_list:
            return await ctx.send(f"⚠️ 股票代碼 `{stock_id}` 已在清單中。", ephemeral=is_private)
            
        # 檢查代碼是否有效 (嘗試抓取一筆數據)
        msg = await ctx.send(f"🔎 正在驗證 `{stock_id}` 代碼...", ephemeral=is_private)
        df = await asyncio.to_thread(_fetch_stock_data, stock_id, range_='5d')
        
        if df is None or df.empty:
            error_msg = f"❌ 股票代碼 `{stock_id}` 無效或找不到資料。"
            if is_private: await ctx.followup.send(error_msg, ephemeral=True)
            else: await msg.edit(content=error_msg)
            return

        stock_list.append(stock_id)
        _save_stock_list(stock_list)
        
        success_msg = f"✅ 成功新增股票代碼 `{stock_id}` 到監測清單！"
        if is_private: await ctx.followup.send(success_msg, ephemeral=True)
        else: await msg.edit(content=success_msg)


    @stock.command(name='remove', aliases=['移除', '刪除'], description="移除股票代碼")
    async def stock_remove(self, ctx: commands.Context, stock_id: str):
        is_private = ctx.interaction is not None
        stock_list = _load_stock_list()
        stock_id = stock_id.upper()
        
        if stock_id not in stock_list:
            return await ctx.send(f"⚠️ 股票代碼 `{stock_id}` 不在清單中。", ephemeral=is_private)

        stock_list.remove(stock_id)
        _save_stock_list(stock_list)
        
        await ctx.send(f"✅ 成功移除股票代碼 `{stock_id}`。", ephemeral=is_private)

    @stock.command(name='list', aliases=['清單'], description="顯示監測清單")
    async def stock_list_command(self, ctx: commands.Context):
        is_private = ctx.interaction is not None
        stock_list = _load_stock_list()

        if not stock_list:
            return await ctx.send("目前監測清單為空。", ephemeral=is_private)

        stock_str = "\n".join([f"• `{s}`" for s in stock_list])
        
        embed = discord.Embed(
            title="📋 當前股票監測清單",
            description=f"總計 **{len(stock_list)}** 支股票。定時檢查時間：台灣時間 **{CHECK_TIME_TW.strftime('%H:%M')}**。",
            color=discord.Color.blue()
        )
        embed.add_field(name="監測代碼列表", value=stock_str, inline=False)
        embed.set_footer(text=f"使用 /stock add 新增，/stock remove 移除。")
        embed.timestamp = datetime.now()
        
        await ctx.send(embed=embed, ephemeral=is_private)
        
    @stock.command(name='check', aliases=['檢查'], description="手動檢查所有或單一股票的訊號")
    async def stock_check_manual(self, ctx: commands.Context, stock_id: Optional[str] = None):
        is_private = ctx.interaction is not None
        stock_list = _load_stock_list()
        
        if not stock_list:
            return await ctx.send("目前監測清單為空。", ephemeral=is_private)
            
        target_channel = self.bot.get_channel(self.notification_channel_id)
        if not target_channel:
             return await ctx.send("❌ 錯誤：通知頻道未設定或無效。", ephemeral=is_private)

        
        target_list = []
        if stock_id:
            stock_id = stock_id.upper()
            if stock_id in stock_list:
                target_list.append(stock_id)
            else:
                 return await ctx.send(f"⚠️ 代碼 `{stock_id}` 不在清單中。", ephemeral=is_private)
        else:
            target_list = stock_list
            
        # 遵循耗時指令 SOP
        msg = await ctx.send(f"🔎 正在手動檢查 **{len(target_list)}** 支股票的最新訊號...", ephemeral=is_private)
        
        all_signals = [] 
        
        for s_id in target_list:
            df = await asyncio.to_thread(_fetch_stock_data, s_id)
            
            if df is not None:
                signals = await asyncio.to_thread(_analyze_signals, s_id, df, PROXIMITY_THRESHOLD)
                
                if signals:
                    all_signals.extend([(s_id, s) for s in signals])
            
            await asyncio.sleep(1) # 暫停 1 秒

        
        reply_content = ""
        now_in_taiwan = datetime.now(TAIWAN_TZ)
        
        if all_signals:
            embed_title = f"🔔 手動檢查報告：發現 {len(all_signals)} 個訊號"
            embed = discord.Embed(
                title=embed_title,
                description=f"檢查時間：{now_in_taiwan.strftime('%Y-%m-%d %H:%M:%S')}",
                color=discord.Color.red() if any(s[1]['type'] == '穿越' for s in all_signals) else discord.Color.blue()
            )
            
            for stock_id, signal in all_signals:
                embed.add_field(
                    name=f"📈 {stock_id}: {signal['title']}",
                    value=signal['detail'],
                    inline=False
                )
            
            content = f"📢 {self.role_mention_tag} 發現 **{len(all_signals)}** 個股票訊號！" if self.role_mention_tag else "📢 發現股票訊號！"
            
            # 發送到通知頻道 (公開)
            await target_channel.send(content=content, embed=embed)
            reply_content = f"✅ 手動檢查完成，已將報告發送至通知頻道。"
            
        else:
             reply_content = f"✅ 手動檢查完成，未發現新訊號。"

        if is_private: await ctx.followup.send(reply_content, ephemeral=True)
        else: await msg.edit(content=reply_content)

async def setup(bot):
    await bot.add_cog(StockMonitor(bot))
