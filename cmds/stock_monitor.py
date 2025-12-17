import discord
from discord.ext import commands, tasks
from core.classes import Cog_Extension 
import json
import os
import asyncio
import logging
from datetime import time, datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

# (修正點 1：引入 Python 內建的時區函式庫)
from zoneinfo import ZoneInfo

# --- 引入股票所需的核心函式庫 ---
import requests
import pandas as pd
import numpy as np # 新增 numpy 用於計算指標
# --------------------------------

# --- 設定常量 ---
STOCK_LIST_FILE = './data/stock_list.json' # 儲存股票代碼的檔案
PROXIMITY_THRESHOLD = 0.01 # 接近 MA20 的閾值 (1%)

# --- 新增指標參數 ---
RSI_PERIOD = 14            # RSI 計算週期
RSI_OVERBOUGHT = 70        # RSI 超買界線
RSI_OVERSOLD = 30          # RSI 超賣界線
VOLUME_ANOMALY_MULTIPLIER = 2.5 # 爆量判定倍數 (大於 5日均量 的 2.5 倍)

# (修正點 2：建立一個明確的 "Asia/Taipei" 時區物件)
TAIWAN_TZ = ZoneInfo("Asia/Taipei")

# (修正點 3：將 "天真" 時間改為 "帶有時區" 的時間)
# (修正點 6：將時間改為 13:45，確保台股已收盤)
# Note: 依照您的要求保留原始設定 12:00
CHECK_TIME_TW = time(12,00, 0, tzinfo=TAIWAN_TZ) # 每天台灣時間 13:45 執行

# 讀取通知頻道 ID 和身分組 ID
STOCK_MONITOR_CHANNEL_ID_STR = os.getenv('STOCK_MONITOR_CHANNEL_ID') 
STOCK_MONITOR_ROLE_ID_STR = os.getenv('STOCK_MONITOR_ROLE_ID') 


# =========================================================
# 股票資料核心處理函式
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


def _fetch_stock_data(stock_id: str, range_='3mo', interval_='1d') -> Tuple[Optional[pd.DataFrame], str]:
    """
    從 Yahoo Finance 抓取股票數據 (在獨立線程中執行)。
    更新：回傳 (DataFrame, StockName)
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_id}"
    params = {'range': range_, 'interval': interval_, 'region': 'TW', 'lang': 'zh-Hant-TW'}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36'}
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        result = data['chart']['result'][0]
        
        # --- 新增：嘗試提取股票名稱 ---
        meta = result.get('meta', {})
        stock_name = meta.get('shortName', stock_id) # 若抓不到名稱則用代碼代替
        
        timestamps = result['timestamp']
        quote = result['indicators']['quote'][0]
        if not timestamps:
            logging.warning(f"[{stock_id}] 找不到資料。")
            return None, stock_name
            
        dates = [datetime.fromtimestamp(ts) for ts in timestamps]
        clean_quote = {}
        for key in ['open', 'high', 'low', 'close', 'volume']:
            clean_quote[key] = [val if val is not None else float('nan') for val in quote.get(key, [])]
            
        df = pd.DataFrame({
            'Open': clean_quote['open'],
            'High': clean_quote['high'],
            'Low': clean_quote['low'],
            'Close': clean_quote['close'],
            'Volume': clean_quote['volume']
        }, index=pd.to_datetime(dates))
        df.dropna(inplace=True) 
        
        return df, stock_name
    except Exception as e:
        logging.error(f"[錯誤] 抓取 {stock_id} 時發生錯誤: {e}")
        return None, stock_id

def _calculate_rsi(series, period=14):
    """計算 RSI 指標"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)

    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def _analyze_signals(stock_id: str, stock_name: str, df: pd.DataFrame, threshold_percent: float) -> List[Dict[str, Any]]:
    """
    分析股票訊號並返回通知列表。
    更新：加入 RSI 與 成交量分析
    """
    signals = []
    
    if len(df) < 20:
        logging.info(f"[{stock_id}] 資料量不足 20 天，跳過分析。")
        return signals
        
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA5_Vol'] = df['Volume'].rolling(window=5).mean()
    df['RSI'] = _calculate_rsi(df['Close'], RSI_PERIOD)
    
    try:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
    except IndexError:
        logging.warning(f"[{stock_id}] 資料量不足 2 天，無法比較。")
        return signals
        
    ma20 = latest['MA20']
    rsi = latest['RSI']
    vol = latest['Volume']
    ma5_vol = latest['MA5_Vol']
    
    if pd.isna(ma20):
        logging.warning(f"[{stock_id}] MA20 數值為空，跳過。")
        return signals

    # 1. K棒「接觸」MA20
    if latest['Low'] <= ma20 <= latest['High']:
        signals.append({
            'type': '接觸',
            'title': f'{stock_id} ({stock_name}): K棒接觸 MA20',
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
                'title': f'{stock_id} ({stock_name}): 快要漲碰到 MA20',
                'detail': f"K棒高點 ({latest['High']:.2f}) 接近 MA20 ({ma20:.2f}), 僅差 {distance:.2f}。",
                'color': discord.Color.orange()
            })
            
        # 快要跌碰到
        upper_bound = ma20 * (1.0 + threshold_percent)
        if (latest['Low'] > ma20) and (latest['Low'] <= upper_bound):
            distance = latest['Low'] - ma20
            signals.append({
                'type': '接近',
                'title': f'{stock_id} ({stock_name}): 快要跌碰到 MA20',
                'detail': f"K棒低點 ({latest['Low']:.2f}) 接近 MA20 ({ma20:.2f}), 僅差 {distance:.2f}。",
                'color': discord.Color.orange()
            })

    # 3. K棒「穿越」MA20
    if not pd.isna(prev['MA20']):
        if latest['Close'] > ma20 and prev['Close'] < prev['MA20']:
            signals.append({
                'type': '穿越',
                'title': f'{stock_id} ({stock_name}): 🟡 黃金交叉 (站上 MA20)',
                'detail': f"收盤價 ({latest['Close']:.2f}) 站上 MA20 ({ma20:.2f})。",
                'color': discord.Color.green()
            })
        elif latest['Close'] < ma20 and prev['Close'] > prev['MA20']:
            signals.append({
                'type': '穿越',
                'title': f'{stock_id} ({stock_name}): ⚫ 死亡交叉 (跌破 MA20)',
                'detail': f"收盤價 ({latest['Close']:.2f}) 跌破 MA20 ({ma20:.2f})。",
                'color': discord.Color.red()
            })

    # 4. RSI 強弱指標
    if not pd.isna(rsi):
        if rsi > RSI_OVERBOUGHT:
            signals.append({
                'type': 'RSI',
                'title': f'{stock_id} ({stock_name}): 🔥 RSI 過熱 (超買)',
                'detail': f"RSI 目前為 **{rsi:.1f}** (>70)，注意回檔風險。",
                'color': discord.Color.dark_red()
            })
        elif rsi < RSI_OVERSOLD:
            signals.append({
                'type': 'RSI',
                'title': f'{stock_id} ({stock_name}): ❄️ RSI 過冷 (超賣)',
                'detail': f"RSI 目前為 **{rsi:.1f}** (<30)，可能醞釀反彈。",
                'color': discord.Color.dark_blue()
            })

    # 5. 成交量異常 (爆量)
    if ma5_vol > 0:
        vol_ratio = vol / ma5_vol
        if vol_ratio >= VOLUME_ANOMALY_MULTIPLIER:
            signals.append({
                'type': '量能',
                'title': f'{stock_id} ({stock_name}): 🌋 成交量異常 (爆量)',
                'detail': f"今日成交量 ({int(vol):,}) 為 5日均量 的 **{vol_ratio:.1f} 倍**。",
                'color': discord.Color.purple()
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

        # 
        # ✅ 修正 1：移除 __init__ 中的 .start()
        #
        # 啟動定時任務 (已移至 on_ready 監聽器中)
        if not self.notification_channel_id:
            logging.warning("股票監測任務**無法**啟動，因為缺少 STOCK_MONITOR_CHANNEL_ID。")
            
    #
    # ✅ 修正 2：新增 on_ready 監聽器來啟動任務
    #
    @commands.Cog.listener()
    async def on_ready(self):
        """當此 Cog 所在的 Bot 準備就緒時"""
        
        # 確保只在 Bot 準備好後才啟動任務
        # 並且檢查任務是否已在運行 (防止重複啟動)
        if not self.daily_stock_check.is_running():
            if self.notification_channel_id:
                self.daily_stock_check.start()
                logging.info(f"股票監測任務已在 on_ready 中啟動，預計每天 {CHECK_TIME_TW.isoformat()} (時區: {CHECK_TIME_TW.tzinfo}) 執行。")

    def cog_unload(self):
        self.daily_stock_check.cancel()
        
    # --- 定時任務：每天 13:45 檢查 ---
    @tasks.loop(time=CHECK_TIME_TW)
    async def daily_stock_check(self):
        #
        # ✅ 修正 3：移除 wait_until_ready()
        #
        
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

        # 這裡的日誌現在一定會在 13:45 (台灣時間) 觸發
        logging.info(f"開始執行 {len(stock_list)} 支股票的定時檢查...")
        
        all_signals = [] # 儲存所有股票的訊號
        
        # 1. 批次抓取並分析
        for stock_id in stock_list:
            # 在獨立線程中執行耗時的 I/O 操作 (網路請求和 Pandas 計算)
            # 更新：同時接收 stock_name
            df, stock_name = await asyncio.to_thread(_fetch_stock_data, stock_id)
            
            if df is not None:
                # 更新：傳入 stock_name
                signals = await asyncio.to_thread(_analyze_signals, stock_id, stock_name, df, PROXIMITY_THRESHOLD)
                
                if signals:
                    all_signals.extend(signals) # 直接 extend signals 列表
            
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
            
            for signal in all_signals:
                embed.add_field(
                    name=signal['title'], # 標題已包含名稱
                    value=signal['detail'],
                    inline=False
                )
            
            # 設置底部資訊和時間戳
            embed.set_footer(text=f"分析基準: MA20 / RSI(14) / 爆量(>2.5倍)")
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
            embed.add_field(name=f"5. 即時報價", value=f"`{ctx.prefix}stock price <代碼>`", inline=False)
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
        df, stock_name = await asyncio.to_thread(_fetch_stock_data, stock_id, range_='5d')
        
        if df is None or df.empty:
            error_msg = f"❌ 股票代碼 `{stock_id}` 無效或找不到資料。"
            if is_private: await ctx.followup.send(error_msg, ephemeral=True)
            else: await msg.edit(content=error_msg)
            return

        stock_list.append(stock_id)
        _save_stock_list(stock_list)
        
        success_msg = f"✅ 成功新增 `{stock_id}` ({stock_name}) 到監測清單！"
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
            # 更新：解包名稱
            df, stock_name = await asyncio.to_thread(_fetch_stock_data, s_id)
            
            if df is not None:
                # 更新：傳入名稱
                signals = await asyncio.to_thread(_analyze_signals, s_id, stock_name, df, PROXIMITY_THRESHOLD)
                
                if signals:
                    all_signals.extend(signals)
            
            await asyncio.sleep(1) # 暫停 1 秒

        
        reply_content = ""
        now_in_taiwan = datetime.now(TAIWAN_TZ)
        
        if all_signals:
            embed_title = f"🔔 手動檢查報告：發現 {len(all_signals)} 個訊號"
            embed = discord.Embed(
                title=embed_title,
                description=f"檢查時間：{now_in_taiwan.strftime('%Y-%m-%d %H:%M:%S')}",
                color=discord.Color.red() if any(s['type'] == '穿越' for s in all_signals) else discord.Color.blue()
            )
            
            for signal in all_signals:
                embed.add_field(
                    name=signal['title'],
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

    # --- 新增功能：即時報價 ---
    @stock.command(name='price', aliases=['報價', '查詢'], description="查詢股票即時報價、MA20 與 RSI")
    async def stock_price(self, ctx: commands.Context, stock_id: str):
        await ctx.defer() # 避免操作超時
        is_private = ctx.interaction is not None
        stock_id = stock_id.upper()
        
        # 抓取資料
        df, stock_name = await asyncio.to_thread(_fetch_stock_data, stock_id)
        
        if df is None or df.empty:
            return await ctx.send(f"❌ 找不到股票 `{stock_id}` 的資料。", ephemeral=is_private)

        # 計算所有指標
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['RSI'] = _calculate_rsi(df['Close'], RSI_PERIOD)
        df['MA5_Vol'] = df['Volume'].rolling(window=5).mean()
        
        latest = df.iloc[-1]
        prev_close = df.iloc[-2]['Close']
        
        price = latest['Close']
        change = price - prev_close
        pct_change = (change / prev_close) * 100
        ma20 = latest['MA20']
        rsi = latest['RSI']
        vol_ratio = latest['Volume'] / latest['MA5_Vol'] if latest['MA5_Vol'] > 0 else 0
        
        # 設定顏色 (台股紅漲綠跌)
        color = discord.Color.red() if change > 0 else discord.Color.green()
        if change == 0: color = discord.Color.light_grey()
        
        embed = discord.Embed(title=f"📊 {stock_id} ({stock_name}) 即時看板", color=color)
        
        # 股價區塊
        embed.add_field(name="💰 現價", value=f"**{price:.2f}**\n({change:+.2f} | {pct_change:+.2f}%)", inline=True)
        
        # MA20 區塊
        ma_status = "✅站上" if price > ma20 else "🔻跌破"
        embed.add_field(name="📏 MA20", value=f"{ma20:.2f}\n({ma_status} {(price/ma20-1)*100:+.2f}%)", inline=True)
        
        # RSI 區塊
        rsi_status = "🔥過熱" if rsi > 70 else "❄️過冷" if rsi < 30 else "中性"
        embed.add_field(name="📈 RSI(14)", value=f"**{rsi:.1f}**\n({rsi_status})", inline=True)
        
        # 成交量區塊
        vol_str = f"{int(latest['Volume']):,}"
        vol_status = "🌋 **爆量**" if vol_ratio >= 2.5 else "正常"
        embed.add_field(name="📊 成交量", value=f"{vol_str}\n({vol_status})", inline=False)
        
        embed.set_footer(text=f"最後更新：{datetime.now(TAIWAN_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
        
        await ctx.send(embed=embed, ephemeral=is_private)

async def setup(bot):
    await bot.add_cog(StockMonitor(bot))