import discord
from discord.ext import commands
from core.classes import Cog_Extension
import json
import os
import re
import asyncio
import random 
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging 
from discord import app_commands # ✅ 引入 app_commands

# --- 引入用於獲取影片/歌曲標題的函式庫 ---
try:
    import yt_dlp 
except ImportError:
    # 如果未安裝，則設置為 None
    logging.warning("警告：yt-dlp 未安裝。無法自動獲取音樂標題。")
    yt_dlp = None
# -----------------------------------------------

# 定義常量
MUSIC_FILE = './data/music_list.json'
MUSIC_CHANNEL_ID = os.getenv('MUSIC_CHANNEL_ID')
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
    start_index: int,
    title: str = "🎶 頻道音樂分享清單" 
) -> discord.Embed:
    """根據分頁資料建立 Embed"""
    
    current_page_items = music_list[start_index : start_index + ITEMS_PER_PAGE]
    
    embed = discord.Embed(
        title=title, 
        description=f"總計 {total_items} 筆紀錄。顯示第 **{page} / {total_pages}** 頁。",
        color=0x1DB954 # Spotify 綠色
    )
    
    if not current_page_items:
        embed.description = "找不到任何紀錄。"

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
    def __init__(self, music_list: List[Dict[str, Any]], ctx: commands.Context, total_pages: int, initial_page: int, embed_title: str = "🎶 頻道音樂分享清單"):
        super().__init__(timeout=180) # 3分鐘無操作後按鈕失效
        self.music_list = music_list
        self.ctx = ctx
        self.total_pages = total_pages
        self.current_page = initial_page
        self.embed_title = embed_title 
        self.update_buttons()

    def update_buttons(self):
        """根據當前頁碼啟用/禁用按鈕"""
        if self.total_pages <= 1:
            self.children[0].disabled = True
            self.children[1].disabled = True
        else:
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
                self.music_list, self.current_page, self.total_pages, len(self.music_list), start_index,
                title=self.embed_title
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
                self.music_list, self.current_page, self.total_pages, len(self.music_list), start_index,
                title=self.embed_title
            )
            await interaction.response.edit_message(embed=embed, view=self)


# --- Cog 核心邏輯 ---
class Music(Cog_Extension):

    def __init__(self, bot):
        super().__init__(bot)
        try:
            self.music_channel_id = int(MUSIC_CHANNEL_ID) if MUSIC_CHANNEL_ID else None
        except ValueError:
            self.music_channel_id = None
            logging.warning("警告：MUSIC_CHANNEL_ID 環境變數設定錯誤，請確保它是頻道 ID 的數字。")

        if not os.path.exists(MUSIC_FILE):
            self._save_music_list([])
            
    def _load_music_list(self):
        """從檔案載入音樂清單"""
        try:
            with open(MUSIC_FILE, 'r', encoding='utf8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"載入音樂清單失敗: {e}")
            return []

    def _save_music_list(self, music_list):
        """將音樂清單存入檔案"""
        try:
            with open(MUSIC_FILE, 'w', encoding='utf8') as f:
                json.dump(music_list, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.error(f"儲存音樂清單失敗: {e}")
            
    # =========================================================
    # ✅ 指令錯誤處理函式 (已修正重複報錯)
    # =========================================================
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        # ✅ 關鍵修正：如果指令不屬於 'Music' Cog，就直接退出
        if ctx.command and ctx.command.cog_name != 'Music':
            return
            
        logging.warning(f"MusicList Cog 捕獲到指令錯誤 (Command: {ctx.command}, Error: {error})")

        # 檢查是否為私人回覆
        is_private = ctx.interaction is not None

        # (只處理 Music Cog 自己的指令錯誤)
        if ctx.command and ctx.command.name in [
            'musiclist', '音樂清單', '清單', 
            'importmusic', '匯入音樂', '抓取紀錄',
            'searchmusic', '搜尋音樂', 'searchlist',
            'removesong', '刪除音樂', 'remusic',
            'randomsong', '隨機音樂', 'randommusic'
        ]:
            
            if isinstance(error, commands.BadArgument):
                error_message = f"⚠️ **參數類型錯誤！**"
                if ctx.command.name in ['musiclist', '音樂清單', '清單']:
                     error_message = f"⚠️ **參數類型錯誤：** `頁碼` 必須是**數字**！\n👉 **範例：** `{ctx.prefix}{ctx.command.name} 3`"
                elif ctx.command.name in ['importmusic', '匯入音樂', '抓取紀錄']:
                    error_message = f"⚠️ **參數類型錯誤：** `要檢查的訊息數量` 必須是**數字**！\n👉 **範例：** `{ctx.prefix}{ctx.command.name} 1000`"
                elif ctx.command.name in ['removesong', '刪除音樂', 'remusic']:
                    error_message = f"⚠️ **參數類型錯誤：** `編號` 必須是**數字**！\n👉 **範例：** `{ctx.prefix}{ctx.command.name} 5`"
                await ctx.send(error_message, ephemeral=is_private)
                
            elif isinstance(error, commands.MissingRequiredArgument):
                 await ctx.send(
                    f"⚠️ **參數遺漏錯誤：** 您忘記提供 `{error.param.name}` 參數了！\n"
                    f"**範例：** `{ctx.prefix}{ctx.command.name} 123`",
                    ephemeral=is_private
                )

            elif isinstance(error, commands.MissingPermissions):
                await ctx.send("❌ **權限不足：** 您沒有權限執行此指令。", ephemeral=is_private, delete_after=10)

            else:
                # 其他錯誤 (例如 Cooldown) 會自動上報給 bot.py
                pass
        
        # ✅ 關鍵修正：移除了 'else' 區塊


    # --- 訊息監聽 (防止遺漏) ---
    @commands.Cog.listener()
    async def on_message(self, msg):
        if msg.author == self.bot.user or msg.guild is None:
            return
        
        if self.music_channel_id and msg.channel.id == self.music_channel_id:
            url_regex = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
            urls = re.findall(url_regex, msg.content)

            if urls:
                music_list = self._load_music_list()
                
                for url in urls:
                    if any(entry['url'] == url for entry in music_list):
                        await msg.channel.send(f"⚠️ 這個連結已在清單中：`{url}`", delete_after=5)
                        continue
                        
                    title = await asyncio.to_thread(_get_video_title, url) 
                        
                    music_entry = {
                        "title": title, 
                        "url": url,
                        "posted_by": msg.author.display_name,
                        "timestamp": msg.created_at.isoformat()
                    }
                    music_list.insert(0, music_entry) 
                    self._save_music_list(music_list)
                    
                    await msg.channel.send(f"✅ 已將音樂 `{title}` (分享者: {msg.author.display_name}) 儲存。", delete_after=8)
                    
        
    # --- ✅ 指令：顯示清單 (轉換為 Hybrid) ---
    @commands.hybrid_command(name='musiclist', aliases=['音樂清單', '清單'], description="顯示已記錄的音樂清單 (使用按鈕分頁)")
    @app_commands.describe(page="要顯示的頁碼 (預設 1)")
    async def show_music_list(self, ctx: commands.Context, page: int = 1):
        """
        顯示已記錄的音樂清單，每頁10筆，使用按鈕分頁。
        指令格式: #musiclist [頁碼]
        """
        is_private = ctx.interaction is not None
        
        music_list = self._load_music_list()

        if not music_list:
            return await ctx.send("目前音樂清單中沒有任何紀錄。", ephemeral=is_private)
        
        total_items = len(music_list)
        total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        
        if page < 1: page = 1
        if page > total_pages: page = total_pages

        start_index = (page - 1) * ITEMS_PER_PAGE
        
        embed = _create_music_list_embed(
            music_list, page, total_pages, total_items, start_index
        )
        
        view = MusicListView(music_list, ctx, total_pages, page)
        
        await ctx.send(embed=embed, view=view, ephemeral=is_private)


    # --- ✅ 指令：匯入歷史紀錄 (轉換為 Hybrid) ---
    @commands.hybrid_command(name='importmusic', aliases=['匯入音樂', '抓取紀錄'], description="匯入音樂頻道中尚未紀錄的歷史連結")
    @app_commands.describe(limit="要檢查的訊息數量 (預設 500)")
    async def import_previous_records(self, ctx: commands.Context, limit: int = 500):
        """
        匯入音樂頻道中尚未紀錄的歷史連結。
        指令格式: #importmusic [要檢查的訊息數量] (預設 500 筆)
        """
        is_private = ctx.interaction is not None
        
        if not self.music_channel_id:
            return await ctx.send("❌ 錯誤：未設定 MUSIC_CHANNEL_ID，無法執行匯入。", ephemeral=True) 
        
        target_channel = self.bot.get_channel(self.music_channel_id)
        if not target_channel:
            return await ctx.send("❌ 錯誤：找不到指定的音樂分享頻道。", ephemeral=True)

        try:
            msg = await ctx.send(f"⏳ 正在檢查最近 **{limit}** 筆歷史訊息，請稍候...", ephemeral=is_private)
        except discord.errors.Forbidden:
            return

        music_list = self._load_music_list()
        existing_urls = {entry['url'] for entry in music_list}
        
        imported_count = 0
        checked_count = 0 
        
        edit_content = "" # 準備回覆的內容
        
        try:
            async for message in target_channel.history(limit=limit, oldest_first=True):
                checked_count += 1 
                if message.author == self.bot.user:
                    continue

                url_regex = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
                urls = re.findall(url_regex, message.content)
                
                for url in urls:
                    if url not in existing_urls:
                        title = await asyncio.to_thread(_get_video_title, url)
                        
                        music_entry = {
                            "title": title, 
                            "url": url,
                            "posted_by": message.author.display_name,
                            "timestamp": message.created_at.isoformat() 
                        }
                        
                        music_list.append(music_entry) 
                        existing_urls.add(url)
                        imported_count += 1
                        
                        if imported_count % 20 == 0:
                            self._save_music_list(music_list)

        except discord.errors.Forbidden:
            edit_content = f"❌ **權限錯誤：** 機器人沒有權限讀取此頻道的**訊息歷史 (Read Message History)**！"
        except Exception as e:
            edit_content = f"❌ 發生未知錯誤: {e}"

        # 最終儲存
        self._save_music_list(music_list)
        
        if imported_count > 0:
             music_list.sort(key=lambda x: datetime.fromisoformat(x['timestamp']), reverse=True)
             self._save_music_list(music_list)

        if not edit_content: # 如果沒出錯
            edit_content = f"✅ 歷史紀錄匯入完成！已檢查 **{checked_count} / {limit}** 筆訊息，並成功匯入 **{imported_count}** 個新的音樂連結。"
        
        # 回覆
        if is_private:
            await ctx.followup.send(edit_content, ephemeral=True)
        else:
            await msg.edit(content=edit_content)

    
    # --- ✅ 指令：搜尋音樂 (轉換為 Hybrid) ---
    @commands.hybrid_command(name='searchmusic', aliases=['搜尋音樂', 'searchlist'], description="搜尋音樂清單中標題包含關鍵字的歌曲")
    @app_commands.describe(keyword="要搜尋的標題關鍵字")
    async def search_music_list(self, ctx: commands.Context, *, keyword: str):
        """
        搜尋音樂清單中標題包含關鍵字的歌曲。
        指令格式: #searchmusic <關鍵字>
        """
        is_private = ctx.interaction is not None
        music_list = self._load_music_list()
        if not music_list:
            return await ctx.send("目前音樂清單中沒有任何紀錄。", ephemeral=is_private)

        search_results = [
            entry for entry in music_list 
            if keyword.lower() in entry.get('title', '').lower()
        ]
        
        custom_title = f"🔎 搜尋 '{keyword}' 的結果"

        if not search_results:
            embed = discord.Embed(
                title=custom_title,
                description=f"在 **{len(music_list)}** 筆紀錄中，找不到標題包含 `{keyword}` 的歌曲。",
                color=0xFF0000 
            )
            return await ctx.send(embed=embed, ephemeral=is_private)
        
        total_items = len(search_results)
        total_pages = (total_items + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
        page = 1 
        start_index = 0

        embed = _create_music_list_embed(
            search_results, page, total_pages, total_items, start_index,
            title=custom_title
        )
        
        view = MusicListView(search_results, ctx, total_pages, page, embed_title=custom_title) 
        
        await ctx.send(embed=embed, view=view, ephemeral=is_private)


    # --- ✅ 指令：刪除歌曲 (轉換為 Hybrid) ---
    @commands.hybrid_command(name='removesong', aliases=['刪除音樂', 'remusic'], description="[僅限管理員] 從音樂清單中刪除指定編號的歌曲")
    @app_commands.describe(number="要刪除的歌曲編號 (見 #musiclist)")
    @commands.has_permissions(administrator=True) 
    async def remove_song(self, ctx: commands.Context, number: int):
        """
        從音樂清單中刪除指定編號的歌曲 (僅限管理員)。
        指令格式: #removesong <編號>
        """
        is_private = ctx.interaction is not None
        music_list = self._load_music_list()
        
        # 將 1-based 編號轉為 0-based 索引
        index = number - 1
        
        if 0 <= index < len(music_list):
            # 彈出該歌曲
            removed_song = music_list.pop(index)
            # 儲存變更
            self._save_music_list(music_list)
            
            await ctx.send(
                f"✅ **已刪除歌曲：**\n"
                f"編號 **{number}**: `{removed_song.get('title', 'N/A')}`\n"
                f"*(分享者: {removed_song.get('posted_by')})*",
                ephemeral=is_private
            )
        else:
            await ctx.send(
                f"❌ **刪除失敗：** 編號 `{number}` 無效。\n"
                f"請使用 `#musiclist` 查詢編號，目前清單總共有 **{len(music_list)}** 首歌。",
                ephemeral=True # 錯誤一律私人
            )

    # --- ✅ 指令：隨機歌曲 (轉換為 Hybrid) ---
    @commands.hybrid_command(name='randomsong', aliases=['隨機音樂', 'randommusic'], description="從音樂清單中隨機挑選一首歌")
    async def random_song(self, ctx: commands.Context):
        """
        從音樂清單中隨機挑選一首歌。
        指令格式: #randomsong
        """
        is_private = ctx.interaction is not None
        music_list = self._load_music_list()
        if not music_list:
            return await ctx.send("目前音樂清單中沒有任何紀錄。", ephemeral=is_private)

        song = random.choice(music_list)
        
        embed = discord.Embed(
            title=f"🎶 隨機點播",
            description=f"**{song.get('title', '標題不詳')}**",
            color=0x1DB954 
        )
        embed.add_field(name="分享者", value=song.get('posted_by', '匿名'), inline=True)
        embed.add_field(name="時間", value=song.get('timestamp', '時間不詳').split('T')[0], inline=True)
        embed.add_field(name="連結", value=f"[點此開啟]({song['url']})", inline=False)
        embed.set_footer(text=f"由 {ctx.author.display_name} 點播")
        
        await ctx.send(embed=embed, ephemeral=is_private)


async def setup(bot):
    await bot.add_cog(Music(bot))