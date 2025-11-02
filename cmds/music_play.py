import discord
from discord.ext import commands
from core.classes import Cog_Extension
import asyncio
import yt_dlp # 您已經安裝了
import re
import os     
import json   
import random 
import logging 
from discord import app_commands # ✅ 1. 引入 app_commands

# --- yt-dlp 和 FFmpeg 設定 ---
YDL_OPTS = {
    # 優先選取壓縮過的格式 (m4a, aac, opus)，減少 RAM 負擔
    'format': 'bestaudio[ext=m4a]/bestaudio[ext=aac]/bestaudio[ext=opus]/bestaudio/best',
    'noplaylist': True, 
    'quiet': True,
    'default_search': 'ytsearch', 
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'extract_flat': True 
}

# FFmpeg 選項
FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

# 從 musiclist.py 引用相同的檔案路徑
MUSIC_FILE = './data/music_list.json'


# --- 音樂播放的主 Cog ---

class MusicPlay(Cog_Extension):
    
    def __init__(self, bot):
        super().__init__(bot)
        # 為每個伺服器(guild)建立獨立的佇列
        self.guild_states = {}

    def get_guild_state(self, ctx):
        """獲取或建立此伺服器的狀態"""
        if ctx.guild.id not in self.guild_states:
            self.guild_states[ctx.guild.id] = {
                'song_queue': [],
                'is_playing': False
            }
        return self.guild_states[ctx.guild.id]

    async def song_finished(self, ctx, error=None):
        """歌曲播放完畢時的回調函式"""
        if error:
            logging.error(f"播放時發生錯誤 (Guild: {ctx.guild.id}): {error}")
            
        state = self.get_guild_state(ctx)
        
        # 標記為未播放，並嘗試播放下一首
        state['is_playing'] = False
        await self.play_next_song(ctx)

    async def play_next_song(self, ctx):
        """
        播放佇列中的下一首歌。
        """
        state = self.get_guild_state(ctx)
        
        if state['is_playing']:
            return
            
        if not state['song_queue']:
            # 佇列已空
            state['is_playing'] = False
            
            #
            # --- 自動離開邏輯 (已註解) ---
            # 未來若要啟用，請將以下 5 行的 '#' 移除
            #
            # await asyncio.sleep(180) # 等待 3 分鐘
            # if not state['is_playing'] and ctx.voice_client:
            #     # 如果 3 分鐘後還是沒歌，自動離開
            #     await ctx.send("播放佇列已空，3 分鐘後將自動離開...")
            #     await ctx.voice_client.disconnect()
            #
            
            # 佇列已空，停止播放，但留在頻道中 (若上面註解保持不動)
            return

        state['is_playing'] = True
        
        # 從佇列取出下一首歌
        song = state['song_queue'].pop(0)
        vc = ctx.voice_client

        if not vc:
            state['is_playing'] = False
            return

        # --- 即時獲取串流 ---
        loop = self.bot.loop or asyncio.get_event_loop()
        
        single_ydl_opts = YDL_OPTS.copy()
        single_ydl_opts['noplaylist'] = True
        
        with yt_dlp.YoutubeDL(single_ydl_opts) as ydl:
            try:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(song['webpage_url'], download=False))
                stream_url = info.get('url')
                if not stream_url:
                    info = await loop.run_in_executor(None, lambda: ydl.extract_info(song['webpage_url'], download=True))
                    stream_url = info.get('url')

                if not stream_url:
                    raise Exception("無法獲取 stream_url")
                    
            except Exception as e:
                await ctx.send(f"❌ 播放 **{song['title']}** 失敗 (可能是地區限制或影片已移除)。\n{e}")
                # 播放失敗，自動跳到下一首
                await self.song_finished(ctx, e) 
                return
        # --- 結束即時獲取 ---

        # 開始播放
        vc.play(
            discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTS),
            after=lambda e: self.bot.loop.create_task(self.song_finished(ctx, e))
        )
        
        # ✅ 播放通知：一律公開
        await ctx.send(f"🎶 正在播放: **{song['title']}** (請求者: {song['requester'].display_name})")

    # =========================================================
    # ✅ 指令：播放音樂 (轉換為 Hybrid)
    # =========================================================
    @commands.hybrid_command(name="play", aliases=['p'], description="播放音樂 (URL 或 搜尋關鍵字)")
    @app_commands.describe(search="YouTube 關鍵字或 URL")
    async def play(self, ctx: commands.Context, *, search: str):
        """
        播放音樂。
        指令格式: #play <URL 或 搜尋關鍵字>
        """
        is_private = ctx.interaction is not None
        state = self.get_guild_state(ctx)

        # 1. 檢查使用者是否在語音頻道
        if not ctx.author.voice:
            return await ctx.send("您必須先加入一個語音頻道！", ephemeral=True) # 錯誤一律私人

        # 2. 獲取/加入語音頻道
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            vc = ctx.voice_client
            if vc.channel != channel:
                await vc.move_to(channel)
        else:
            try:
                vc = await channel.connect()
            except discord.errors.Forbidden:
                return await ctx.send(f"❌ 權限不足：我無法加入頻道 `{channel.name}`。", ephemeral=True)

        # 3. 搜尋 yt-dlp
        # / 指令會用 "思考中"，# 指令會發送公開訊息
        msg = await ctx.send(f"🔎 正在搜尋: `{search}`...", ephemeral=is_private)
        
        loop = self.bot.loop or asyncio.get_event_loop()
        
        playlist_ydl_opts = YDL_OPTS.copy()
        playlist_ydl_opts['noplaylist'] = False
        
        info = None
        error_msg = None
        try:
            with yt_dlp.YoutubeDL(playlist_ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(search, download=False))
        except Exception as e:
            logging.error(f"yt-dlp 搜尋失敗 (Guild: {ctx.guild.id}, Search: {search}): {e}")
            error_msg = f"❌ 搜尋失敗或找不到影片: {e}"
        
        if error_msg:
            if is_private: return await ctx.followup.send(error_msg, ephemeral=True)
            else: return await msg.edit(content=error_msg)

        # 4. 準備歌曲資訊
        songs_to_add = []
        playlist_title = None
        
        if 'entries' in info:
            playlist_title = info.get('title', 'N/A')
            for entry in info['entries']:
                if entry:
                    songs_to_add.append({
                        'title': entry.get('title', 'N/A'),
                        'webpage_url': entry.get('url'), # 'extract_flat' 會將 url 設為 webpage_url
                        'requester': ctx.author
                    })
        elif info: # 確保 info 不是 None
            songs_to_add.append({
                'title': info.get('title', 'N/A'),
                'webpage_url': info.get('webpage_url', info.get('url')), # 獲取頁面 URL
                'requester': ctx.author
            })

        if not songs_to_add:
             error_msg = "❌ 抱歉，無法從您的搜尋中獲取任何歌曲。"
             if is_private: return await ctx.followup.send(error_msg, ephemeral=True)
             else: return await msg.edit(content=error_msg)

        # 5. 加入佇列
        for song in songs_to_add:
             if song['webpage_url']:
                 state['song_queue'].append(song)
             
        if len(songs_to_add) == 1:
            reply_content = f"✅ 已加入佇列: **{songs_to_add[0]['title']}**"
        else:
             reply_content = f"✅ 已將 **{len(songs_to_add)}** 首歌從播放清單 **{playlist_title}** 加入佇列！"

        if is_private: await ctx.followup.send(reply_content, ephemeral=True)
        else: await msg.edit(content=reply_content)

        # 6. 如果目前沒在播放，就開始播放
        if not state['is_playing']:
            await self.play_next_song(ctx)

    # =========================================================
    # ✅ 指令：播放 data/music_list.json (轉換為 Hybrid)
    # =========================================================
    @commands.hybrid_command(name="playlist", aliases=['播放清單音樂', 'pl'], description="播放 data/music_list.json 中的所有音樂 (隨機排序)")
    async def playlist(self, ctx: commands.Context):
        """
        播放 data/music_list.json 中的所有音樂 (隨機排序)。
        指令格式: #playlist
        """
        is_private = ctx.interaction is not None
        state = self.get_guild_state(ctx)

        # 1. 檢查
        if not ctx.author.voice:
            return await ctx.send("您必須先加入一個語音頻道！", ephemeral=True)
        
        # 2. 加入頻道
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            if ctx.voice_client.channel != channel:
                await ctx.voice_client.move_to(channel)
        else:
            try:
                vc = await channel.connect()
            except discord.errors.Forbidden:
                return await ctx.send(f"❌ 權限不足：我無法加入頻道 `{channel.name}`。", ephemeral=True)

        # 3. 載入 music_list.json
        if not os.path.exists(MUSIC_FILE):
            return await ctx.send(f"❌ 錯誤：找不到您的音樂清單檔案 (`{MUSIC_FILE}`)。", ephemeral=is_private)
        
        try:
            with open(MUSIC_FILE, 'r', encoding='utf8') as f:
                music_list = json.load(f)
        except Exception as e:
            return await ctx.send(f"❌ 讀取音樂清單失敗: {e}", ephemeral=is_private)

        if not music_list:
            return await ctx.send("❌ 您的音樂清單是空的！", ephemeral=is_private)

        # 4. 隨機排序並加入佇列
        random.shuffle(music_list)
        
        added_count = 0
        for entry in music_list:
            song = {
                'title': entry.get('title', 'N/A'),
                'webpage_url': entry.get('url'),
                'requester': ctx.author 
            }
            if song['webpage_url']:
                state['song_queue'].append(song)
                added_count += 1
        
        if added_count == 0:
            return await ctx.send("❌ 您的清單中沒有有效的歌曲連結。", ephemeral=is_private)

        await ctx.send(f"✅ 已將 **{added_count}** 首歌 (來自 `music_list.json`) 加入隨機播放佇列！", ephemeral=is_private)

        # 5. 開始播放
        if not state['is_playing']:
            await self.play_next_song(ctx)

    # =========================================================
    # ✅ 指令：離開頻道 (轉換為 Hybrid)
    # =========================================================
    @commands.hybrid_command(name="stop", aliases=['leave', 'dc'], description="停止播放並離開語音頻道")
    async def stop(self, ctx: commands.Context):
        """
        停止播放並離開語音頻道。
        指令格式: #stop
        """
        is_private = ctx.interaction is not None
        
        if not ctx.voice_client:
            return await ctx.send("Bot 目前不在任何語音頻道中。", ephemeral=is_private)

        state = self.get_guild_state(ctx)
        
        state['song_queue'] = []
        state['is_playing'] = False
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            
        await ctx.voice_client.disconnect()
        await ctx.send("👋 已停止播放並離開頻道。", ephemeral=is_private)
        
        if ctx.guild.id in self.guild_states:
            del self.guild_states[ctx.guild.id]

    # =========================================================
    # ✅ 指令：跳過歌曲 (轉換為 Hybrid)
    # =========================================================
    @commands.hybrid_command(name="skip", aliases=['s'], description="跳過目前正在播放的歌曲")
    async def skip(self, ctx: commands.Context):
        """
        跳過目前正在播放的歌曲。
        指令格式: #skip
        """
        is_private = ctx.interaction is not None
        
        if not ctx.voice_client:
            return await ctx.send("Bot 目前不在任何語音頻道中。", ephemeral=is_private)
        
        state = self.get_guild_state(ctx)

        if not state['is_playing']:
            if state['song_queue']:
                 await ctx.send("...佇列卡住，正在啟動下一首。", ephemeral=is_private)
                 await self.play_next_song(ctx)
            else:
                await ctx.send("目前沒有歌曲正在播放。", ephemeral=is_private)
            return

        ctx.voice_client.stop()
        await ctx.send("⏭️ 已跳過目前歌曲。", ephemeral=is_private)


    # =========================================================
    # ✅ 指令：查看佇列 (轉換為 Hybrid)
    # =========================================================
    @commands.hybrid_command(name="queue", aliases=['q'], description="顯示目前的播放佇列")
    async def queue(self, ctx: commands.Context):
        """
        顯示目前的播放佇列。
        指令格式: #queue
        """
        is_private = ctx.interaction is not None
        state = self.get_guild_state(ctx)
        queue = state['song_queue']

        if not queue:
            return await ctx.send("目前播放佇列是空的。", ephemeral=is_private)

        embed = discord.Embed(title="🎶 播放佇列", color=0x1DB954)
        
        for i, song in enumerate(queue[:10]):
            embed.add_field(
                name=f"**{i+1}. {song['title']}**", 
                value=f"請求者: {song['requester'].display_name}", 
                inline=False
            )
        
        if len(queue) > 10:
            embed.set_footer(text=f"...還有 {len(queue) - 10} 首歌在佇列中")

        await ctx.send(embed=embed, ephemeral=is_private)

    # =========================================================
    # ✅ 指令錯誤處理函式 (已修正)
    # =========================================================
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        # ✅ 關鍵修正：如果指令不屬於 'MusicPlay' Cog，就直接退出
        if ctx.command and ctx.command.cog_name != 'MusicPlay':
            return
            
        logging.warning(f"MusicPlay Cog 捕獲到指令錯誤 (Command: {ctx.command}, Error: {error})")

        is_private = ctx.interaction is not None
        
        MUSIC_PLAY_COMMANDS = [
            'play', 'p',
            'playlist', '播放清單音樂', 'pl',
            'stop', 'leave', 'dc',
            'skip', 's',
            'queue', 'q'
        ]

        if ctx.command and ctx.command.name in MUSIC_PLAY_COMMANDS:
            
            if isinstance(error, commands.MissingRequiredArgument):
                if ctx.command.name in ['play', 'p']:
                    await ctx.send(
                        f"⚠️ **您忘記提供歌曲名稱或連結了！**\n\n"
                        f"**👉 正確格式：**\n"
                        f"`{ctx.prefix}{ctx.command.name} [YouTube 關鍵字或 URL]`",
                        ephemeral=is_private
                    )
                else:
                    await ctx.send(f"⚠️ **參數遺漏錯誤：** 您忘記提供 `{error.param.name}` 參數了！", ephemeral=is_private)

            elif isinstance(error, commands.MissingPermissions):
                await ctx.send("❌ **權限不足：** 您沒有權限執行此指令。", ephemeral=is_private, delete_after=10)

            elif isinstance(error, commands.CheckFailure):
                 await ctx.send(f"❌ **指令檢查失敗：** {error}", ephemeral=is_private, delete_after=10)

            else:
                # 其他錯誤會自動上報給 bot.py
                pass
        
        # ✅ 關鍵修正：移除了 'else' 區塊


async def setup(bot):
    await bot.add_cog(MusicPlay(bot))