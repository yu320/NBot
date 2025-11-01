import discord
from discord.ext import commands
from core.classes import Cog_Extension
import json
import os
import re
import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional

# --- 引入用於獲取影片/歌曲標題的函式庫 ---
try:
    import yt_dlp 
except ImportError:
    # 如果未安裝，則設置為 None
    print("警告：yt-dlp 未安裝。無法自動獲取音樂標題。")
    yt_dlp = None
# -----------------------------------------------

# 定義常量
MUSIC_FILE = 'music_list.json'
MUSIC_CHANNEL_ID = os.getenv('MUSIC_CHANNEL_ID')
# 移除 MUSIC_IMPORT_ROLE_NAME 相關邏輯，將權限開放給所有人
ITEMS_PER_PAGE = 10 

# --- 輔助函式：獲取標題 ---
def _get_video_title(url: str) -> str:
    """嘗試使用 yt-dlp 獲取影片或網頁的標題 (在獨立線程中執行)"""
    if not yt_dlp:
        return "(yt-dlp未安裝，無法獲取標題)"

    ydl_opts = {
        'quiet': True, 'no_warnings': True, 'forcetitle': True, 
        'skip_download': True, 'simulate': True, 'format': 'best', 
        'extract_flat': 'in_playlist', 'retries': 3
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False, timeout=5)
            return info.get('title', '無法獲取標題')
    except Exception as e:
        # 降級嘗試：嘗試用 requests 獲取 HTML <title>
        try:
            import requests
            r = requests.get(url, timeout=5)
            title_match = re.search(r'<title>(.*?)</title>', r.text, re.IGNORECASE)
            if title_match:
                return title_match.group(1).strip()
            return f"(非標準連結或標題獲取失敗)"
        except Exception:
            return f"(標題獲取失敗)"

# --- 輔助函式：建立分頁 Embed ---
def _create_music_list_embed(
    music_list: List[Dict[str, Any]], 
    page: int, 
    total_pages: int, 
    total_items: int,
    start_index: int
) -> discord.Embed:
    """根據分頁資料建立 Embed"""
    
    current_page_items = music_list[start_index : start_index + ITEMS_PER_PAGE]
    
    embed = discord.Embed(
        title="🎶 頻道音樂分享清單",
        description=f"總計 {total_items} 筆紀錄。顯示第 **{page} / {total_pages}** 頁。",
        color=0x1DB954 # Spotify 綠色
    )
    
    for i, entry in enumerate(current_page_items): 
        display_num = start_index + i + 1
        
        try:
            # 嘗試解析並格式化時間
            dt_obj = datetime.fromisoformat(entry.get('timestamp', datetime.now().isoformat()))
            formatted_time = dt_obj.strftime("%Y-%m-%d %H:%M:%S")
        except:
            formatted_time = entry.get('timestamp', "時間不詳")
        
        field_name = f"**{display_num}. {entry.get('title', '歌名不詳')}**"
        
        field_value = (
            f"**分享者:** {entry.get('posted_by', '匿名')}\n"
            f"**時間:** {formatted_time}\n"
            f"**連結:** [點此開啟]({entry['url']})"
        )
        
        embed.add_field(
            name=field_name,
            value=field_value,
            inline=False
        )
        
    embed.set_footer(text=f"紀錄於: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return embed


# --- View：處理按鈕互動 ---
class MusicListView(discord.ui.View):
    def __init__(self, music_list: List[Dict[str, Any]], ctx: commands.Context, total_pages: int, initial_page: int):
        super().__init__(timeout=180) # 3分鐘無操作後按鈕失效
        self.music_list = music_list
        self.ctx = ctx
        self.total_pages = total_pages
        self.current_page = initial_page
        self.update_buttons()

    def update_buttons(self):
        """根據當前頁碼啟用/禁用按鈕"""
        self.children[0].disabled = self.current_page == 1 # 上一頁
        self.children[1].disabled = self.current_page == self.total_pages # 下一頁

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """只允許最初發起指令的使用者操作"""
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("只有發起指令的人可以翻頁。", ephemeral=True)
            return False
        return True

    def _get_page_params(self) -> int:
        """計算分頁參數 (起始索引)"""
        start_index = (self.current_page - 1) * ITEMS_PER_PAGE
        return start_index

    # --- 按鈕定義：上一頁 ---
    @discord.ui.button(label="上一頁", style=discord.ButtonStyle.blurple, emoji="◀️")
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 1:
            self.current_page -= 1
            self.update_buttons()
            start_index = self._get_page_params()
            embed = _create_music_list_embed(
                self.music_list, self.current_page, self.total_pages, len(self.music_list), start_index
            )
            await interaction.response.edit_message(embed=embed, view=self)

    # --- 按鈕定義：下一頁 ---
    @discord.ui.button(label="下一頁", style=discord.ButtonStyle.blurple, emoji="▶️")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.update_buttons()
            start_index = self._get_page_params()
            embed = _create_music_list_embed(
                self.music_list, self.current_page, self.total_pages, len(self.music_list), start_index
            )
            await interaction.response.edit_message(embed=embed, view=self)


# --- Cog 核心邏輯 ---
class Music(Cog_Extension):

    def __init__(self, bot):
        super().__init__(bot)
        # 確保 MUSIC_CHANNEL_ID 已設定
        try:
            self.music_channel_id = int(MUSIC_CHANNEL_ID) if MUSIC_CHANNEL_ID else None
        except ValueError:
            self.music_channel_id = None
            print("警告：MUSIC_CHANNEL_ID 環境變數設定錯誤，請確保它是頻道 ID 的數字。")

        # 確保音樂清單檔案存在
        if not os.path.exists(MUSIC_FILE):
            self._save_music_list([])
            
    def _load_music_list(self):
        """從檔案載入音樂清單"""
        try:
            with open(MUSIC_FILE, 'r', encoding='utf8') as f:
                return json.load(f)
        except Exception as e:
            print(f"載入音樂清單失敗: {e}")
            return []

    def _save_music_list(self, music_list):
        """將音樂清單存入檔案"""
        try:
            # 使用 ensure_ascii=False 以正確儲存中文
            with open(MUSIC_FILE, 'w', encoding='utf8') as f:
                json.dump(music_list, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"儲存音樂清單失敗: {e}")
            
    # =========================================================
    # ✅ 指令錯誤處理函式 (保持不變)
    # =========================================================
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        # 確保只處理 musiclist 或 importmusic 相關的指令錯誤
        if ctx.command and ctx.command.name in ['musiclist', '音樂清單', '清單', 'importmusic', '匯入音樂', '抓取紀錄']:
            
            # 參數類型錯誤 (例如: 頁碼或 limit 不是數字)
            if isinstance(error, commands.BadArgument):
                
                # 針對 #musiclist 頁碼錯誤
                if ctx.command.name in ['musiclist', '音樂清單', '清單']:
                     await ctx.send(
                        f"⚠️ **參數類型錯誤：** `頁碼` 必須是**數字**！\n\n"
                        f"**👉 正確格式：**\n"
                        f"`{ctx.prefix}{ctx.command.name} [頁碼]`\n"
                        f"**範例：** `{ctx.prefix}{ctx.command.name} 3`"
                    )
                
                # 針對 #importmusic limit 錯誤
                elif ctx.command.name in ['importmusic', '匯入音樂', '抓取紀錄']:
                    await ctx.send(
                        f"⚠️ **參數類型錯誤：** `要檢查的訊息數量` 必須是**數字**！\n\n"
                        f"**👉 正確格式：**\n"
                        f"`{ctx.prefix}{ctx.command.name} [要檢查的訊息數量]`\n"
                        f"**範例：** `{ctx.prefix}{ctx.command.name} 1000` (預設 500)"
                    )
                
            # 忽略其他錯誤，讓它繼續傳播
            else:
                pass
        
        else:
            # 讓其他指令的錯誤繼續由 bot.py 或其他 Cog 處理
            if self.bot.extra_events.get('on_command_error', None) is not None:
                 await self.bot.on_command_error(ctx, error)
            else:
                 # 如果沒有其他監聽器，則引發錯誤
                 print(f"Unhandled error in {ctx.command}: {error}")


    # --- 訊息監聽 (保持不變) ---
    @commands.Cog.listener()
    async def on_message(self, msg):
        # 忽略機器人自己的訊息和私訊
        if msg.author == self.bot.user or msg.guild is None:
            return
        
        # 僅在指定的音樂分享頻道進行操作
        if self.music_channel_id and msg.channel.id == self.music_channel_id:
            # 偵測訊息中的所有 URL
            url_regex = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
            urls = re.findall(url_regex, msg.content)

            if urls:
                music_list = self._load_music_list()
                
                for url in urls:
                    # 檢查連結是否已存在，避免重複儲存
                    if any(entry['url'] == url for entry in music_list):
                        await msg.channel.send(f"⚠️ 這個連結已在清單中：`{url}`", delete_after=5)
                        continue
                        
                    # 異步獲取標題
                    title = await asyncio.to_thread(_get_video_title, url) 
                        
                    # 紀錄音樂資訊
                    music_entry = {
                        "title": title, 
                        "url": url,
                        "posted_by": msg.author.display_name,
                        "timestamp": msg.created_at.isoformat() # 使用訊息的發送時間
                    }
                    # 將新紀錄添加到列表的開頭 (確保最新的在前面)
                    music_list.insert(0, music_entry) 
                    self._save_music_list(music_list)
                    
                    await msg.channel.send(f"✅ 已將音樂 `{title}` (分享者: {msg.author.display_name}) 儲存。", delete_after=8)
                    
        # 確保指令仍然可以執行
        await self.bot.process_commands(msg)

    # --- 指令：顯示清單 (使用按鈕分頁) ---
    @commands.command(name='musiclist', aliases=['音樂清單', '清單'])
    async def show_music_list(self, ctx, page: int = 1):
        """
        顯示已記錄的音樂清單，每頁10筆，使用按鈕分頁。
        指令格式: #musiclist [頁碼]
        """
        music_list = self._load_music_list()

        if not music_list:
            return await ctx.send("目前音樂清單中沒有任何紀錄。", delete_after=10)
        
        total_items = len(music_list)
        total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        
        # 限制頁碼範圍
        if page < 1: page = 1
        if page > total_pages: page = total_pages

        start_index = (page - 1) * ITEMS_PER_PAGE
        
        # 建立 Embed 和 View
        embed = _create_music_list_embed(
            music_list, page, total_pages, total_items, start_index
        )
        
        view = MusicListView(music_list, ctx, total_pages, page)
        
        await ctx.send(embed=embed, view=view)


    # --- 指令：匯入歷史紀錄 (新增「抓取中」回應) ---
    @commands.command(name='importmusic', aliases=['匯入音樂', '抓取紀錄'])
    async def import_previous_records(self, ctx, limit: int = 500):
        """
        匯入音樂頻道中尚未紀錄的歷史連結。
        指令格式: #importmusic [要檢查的訊息數量] (預設 500 筆)
        """
        if not self.music_channel_id:
            return await ctx.send("❌ 錯誤：未設定 MUSIC_CHANNEL_ID，無法執行匯入。請聯繫管理員設定。", delete_after=15)
        
        target_channel = self.bot.get_channel(self.music_channel_id)
        if not target_channel:
            return await ctx.send("❌ 錯誤：找不到指定的音樂分享頻道。", delete_after=15)

        # 1. 延遲回覆，讓 Discord 知道操作正在進行
        await ctx.defer() 
        
        # 2. ⬇️ 新增：發送一個明確的「抓取中」回應 ⬇️
        # 這會替換 Discord 的「機器人正在思考...」訊息
        await ctx.followup.send(f"🔎 開始檢查音樂頻道中最新的 **{limit}** 則訊息。請稍候，這可能需要一些時間。", ephemeral=False) 

        # ... (抓取邏輯開始) ...
        music_list = self._load_music_list()
        existing_urls = {entry['url'] for entry in music_list}
        
        imported_count = 0
        
        # 透過 channel.history 迭代抓取訊息
        async for msg in target_channel.history(limit=limit, oldest_first=True):
            if msg.author == self.bot.user:
                continue

            url_regex = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
            urls = re.findall(url_regex, msg.content)
            
            for url in urls:
                if url not in existing_urls:
                    # 避免在主線程中等待標題獲取
                    title = await asyncio.to_thread(_get_video_title, url)
                    
                    music_entry = {
                        "title": title, 
                        "url": url,
                        "posted_by": msg.author.display_name,
                        "timestamp": msg.created_at.isoformat() # 使用歷史訊息的發送時間
                    }
                    
                    music_list.append(music_entry) 
                    existing_urls.add(url)
                    imported_count += 1
                    
                    # 為了避免頻繁寫入檔案，每 20 筆儲存一次
                    if imported_count % 20 == 0:
                        self._save_music_list(music_list)

        # 最終儲存所有變更
        self._save_music_list(music_list)
        
        if imported_count > 0:
             # 重新載入並按照 timestamp 重新排序一次，確保時間順序正確 (最新的在最前面)
             music_list.sort(key=lambda x: datetime.fromisoformat(x['timestamp']), reverse=True)
             self._save_music_list(music_list)


        # 3. ⬇️ 最後的成功回應 ⬇️
        # 這是第二個 followup 訊息，會以新的訊息顯示在頻道中
        await ctx.followup.send(f"✅ 歷史紀錄匯入完成！已檢查最近 **{limit}** 筆訊息，並成功匯入 **{imported_count}** 個新的音樂連結。", ephemeral=False)

async def setup(bot):
    await bot.add_cog(Music(bot))