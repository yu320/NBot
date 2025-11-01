import discord
from discord.ext import commands
from core.classes import Cog_Extension
import asyncio
import yt_dlp # 您已經安裝了
import re
import os     
import json   
import random 
import logging # ✅ 1. 引入 logging 模組

# --- yt-dlp 和 FFmpeg 設定 ---
# (您的 Dockerfile 已安裝 ffmpeg)

# yt-dlp 選項：搜尋並獲取最佳音訊，不下載
YDL_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True, # 除非是播放清單指令，否則 #play 指令不應處理清單
    'quiet': True,
    'default_search': 'ytsearch', # 將 'ytsearch' 設為預設搜尋
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
    'extract_flat': True # 加快播放清單的處理速度
}

# FFmpeg 選項：在連接時自動重新連接，隱藏終端機輸出
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
        # 結構: { guild_id: { 'queue': [], 'is_playing': False } }
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
            # ✅ 2. print 改 logging
            logging.error(f"播放時發生錯誤 (Guild: {ctx.guild.id}): {error}")
            
        state = self.get_guild_state(ctx)
        
        # 標記為未播放，並嘗試播放下一首
        state['is_playing'] = False
        await self.play_next_song(ctx)

    async def play_next_song(self, ctx):
        """
        播放佇列中的下一首歌。
        (此函式會在播放前才獲取 stream_url)
        """
        state = self.get_guild_state(ctx)
        
        # 如果正在播放，則返回
        if state['is_playing']:
            return
            
        if not state['song_queue']:
            # 佇列已空
            state['is_playing'] = False
            
            #
            # ✅ --- 自動離開邏輯 (已註解) ---
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
            # 以防萬一 bot 斷線了
            state['is_playing'] = False
            return

        # --- 即時獲取串流 ---
        loop = self.bot.loop or asyncio.get_event_loop()
        
        # 使用一個不抽取播放清單的 YDL_OPTS 來獲取單一串流
        single_ydl_opts = YDL_OPTS.copy()
        single_ydl_opts['noplaylist'] = True
        
        with yt_dlp.YoutubeDL(single_ydl_opts) as ydl:
            try:
                # 在獨立線程中運行
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(song['webpage_url'], download=False))
                stream_url = info.get('url')
                if not stream_url:
                    # 如果上面失敗了，嘗試重新抽取 (有時 yt-dlp 需要兩次)
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
            # 播放完畢時，調用 self.song_finished
            after=lambda e: self.bot.loop.create_task(self.song_finished(ctx, e))
        )
        
        await ctx.send(f"🎶 正在播放: **{song['title']}** (請求者: {song['requester'].display_name})")

    # =========================================================
    # 指令：播放音樂
    # =========================================================
    @commands.command(name="play", aliases=['p'])
    async def play(self, ctx, *, search: str):
        """
        播放音樂。
        指令格式: #play <URL 或 搜尋關鍵字>
        """
        state = self.get_guild_state(ctx)

        # 1. 檢查使用者是否在語音頻道
        if not ctx.author.voice:
            return await ctx.send("您必須先加入一個語音頻道！")

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
                return await ctx.send(f"❌ 權限不足：我無法加入頻道 `{channel.name}`。")

        # 3. 搜尋 yt-dlp (在獨立線程中執行以避免阻塞)
        await ctx.send(f"🔎 正在搜尋: `{search}`...")
        
        loop = self.bot.loop or asyncio.get_event_loop()
        
        # 使用允許播放清單的 YDL_OPTS 來檢查
        playlist_ydl_opts = YDL_OPTS.copy()
        playlist_ydl_opts['noplaylist'] = False
        
        with yt_dlp.YoutubeDL(playlist_ydl_opts) as ydl:
            try:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(search, download=False))
            except Exception as e:
                # ✅ 3. print 改 logging
                logging.error(f"yt-dlp 搜尋失敗 (Guild: {ctx.guild.id}, Search: {search}): {e}")
                return await ctx.send(f"❌ 搜尋失敗或找不到影片: {e}")

        # 4. 準備歌曲資訊 (區分播放清單和單曲)
        
        songs_to_add = []
        
        if 'entries' in info:
            # 這是一個播放清單
            await ctx.send(f"🔄 正在處理播放清單: **{info.get('title', 'N/A')}**...")
            for entry in info['entries']:
                if entry:
                    songs_to_add.append({
                        'title': entry.get('title', 'N/A'),
                        'webpage_url': entry.get('url'), # 'extract_flat' 會將 url 設為 webpage_url
                        'requester': ctx.author
                    })
        else:
            # 這是一個單曲
            songs_to_add.append({
                'title': info.get('title', 'N/A'),
                'webpage_url': info.get('webpage_url', info.get('url')), # 獲取頁面 URL
                'requester': ctx.author
            })

        if not songs_to_add:
             return await ctx.send("❌ 抱歉，無法從您的搜尋中獲取任何歌曲。")

        # 5. 加入佇列
        for song in songs_to_add:
             if song['webpage_url']:
                 state['song_queue'].append(song)
             
        if len(songs_to_add) == 1:
            await ctx.send(f"✅ 已加入佇列: **{songs_to_add[0]['title']}**")
        else:
             await ctx.send(f"✅ 已將 **{len(songs_to_add)}** 首歌從播放清單加入佇列！")

        # 6. 如果目前沒在播放，就開始播放
        if not state['is_playing']:
            await self.play_next_song(ctx)

    # =========================================================
    # 指令：播放 data/music_list.json
    # =========================================================
    @commands.command(name="playlist", aliases=['播放清單音樂', 'pl'])
    async def playlist(self, ctx):
        """
        播放 data/music_list.json 中的所有音樂 (隨機排序)。
        指令格式: #playlist
        """
        state = self.get_guild_state(ctx)

        # 1. 檢查使用者是否在語音頻道
        if not ctx.author.voice:
            return await ctx.send("您必須先加入一個語音頻道！")
        
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
                return await ctx.send(f"❌ 權限不足：我無法加入頻道 `{channel.name}`。")

        # 3. 載入 music_list.json
        if not os.path.exists(MUSIC_FILE):
            return await ctx.send(f"❌ 錯誤：找不到您的音樂清單檔案 (`{MUSIC_FILE}`)。")
        
        try:
            with open(MUSIC_FILE, 'r', encoding='utf8') as f:
                music_list = json.load(f)
        except Exception as e:
            return await ctx.send(f"❌ 讀取音樂清單失敗: {e}")

        if not music_list:
            return await ctx.send("❌ 您的音樂清單是空的！")

        # 4. 隨機排序並加入佇列
        random.shuffle(music_list)
        
        added_count = 0
        for entry in music_list:
            # 建立與 #play 指令相容的歌曲物件
            song = {
                'title': entry.get('title', 'N/A'),
                'webpage_url': entry.get('url'), # 根據 musiclist.py, 'url' 欄位是頁面網址
                'requester': ctx.author # 標記是誰啟動了這個播放清單
            }
            
            if song['webpage_url']:
                state['song_queue'].append(song)
                added_count += 1
        
        if added_count == 0:
            return await ctx.send("❌ 您的清單中沒有有效的歌曲連結。")

        await ctx.send(f"✅ 已將 **{added_count}** 首歌 (來自 `music_list.json`) 加入隨機播放佇列！")

        # 5. 如果目前沒在播放，就開始播放
        if not state['is_playing']:
            await self.play_next_song(ctx)

    # =========================================================
    # 指令：離開頻道 (停止)
    # =========================================================
    @commands.command(name="stop", aliases=['leave', 'dc'])
    async def stop(self, ctx):
        """
        停止播放並離開語音頻道。
        指令格式: #stop
        """
        if not ctx.voice_client:
            return await ctx.send("Bot 目前不在任何語音頻道中。")

        state = self.get_guild_state(ctx)
        
        # 清空佇列、停止播放、斷線
        state['song_queue'] = []
        state['is_playing'] = False
        if ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            
        await ctx.voice_client.disconnect()
        await ctx.send("👋 已停止播放並離開頻道。")
        # 清除此伺服器的狀態
        if ctx.guild.id in self.guild_states:
            del self.guild_states[ctx.guild.id]

    # =========================================================
    # 指令：跳過歌曲
    # =========================================================
    @commands.command(name="skip", aliases=['s'])
    async def skip(self, ctx):
        """
        跳過目前正在播放的歌曲。
        指令格式: #skip
        """
        if not ctx.voice_client:
            return await ctx.send("Bot 目前不在任何語音頻道中。")
        
        state = self.get_guild_state(ctx)

        if not state['is_playing']:
            # 如果佇列中有歌但未播放，也幫忙啟動
            if state['song_queue']:
                 await ctx.send("...佇列卡住，正在啟動下一首。")
                 await self.play_next_song(ctx)
            else:
                await ctx.send("目前沒有歌曲正在播放。")
            return

        # 停止目前歌曲 (stop() 會自動觸發 after 回調 -> song_finished -> play_next_song)
        ctx.voice_client.stop()
        await ctx.send("⏭️ 已跳過目前歌曲。")


    # =========================================================
    # 指令：查看佇列
    # =========================================================
    @commands.command(name="queue", aliases=['q'])
    async def queue(self, ctx):
        """
        顯示目前的播放佇列。
        指令格式: #queue
        """
        state = self.get_guild_state(ctx)
        queue = state['song_queue']

        if not queue:
            return await ctx.send("目前播放佇列是空的。")

        embed = discord.Embed(title="🎶 播放佇列", color=0x1DB954)
        
        # 只顯示佇列中的前 10 首歌
        for i, song in enumerate(queue[:10]):
            embed.add_field(
                name=f"**{i+1}. {song['title']}**", 
                value=f"請求者: {song['requester'].display_name}", 
                inline=False
            )
        
        if len(queue) > 10:
            embed.set_footer(text=f"...還有 {len(queue) - 10} 首歌在佇列中")

        await ctx.send(embed=embed)

    # =========================================================
    # ✅ --- (NEW) 指令錯誤處理函式 (提供教學) ---
    # =========================================================
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        # 1. 定義此 Cog 中的所有指令名稱
        MUSIC_PLAY_COMMANDS = [
            'play', 'p',
            'playlist', '播放清單音樂', 'pl',
            'stop', 'leave', 'dc',
            'skip', 's',
            'queue', 'q'
        ]

        # 2. 確保只處理 music_play 相關的指令錯誤
        if ctx.command and ctx.command.name in MUSIC_PLAY_COMMANDS:
            
            # 3. 處理「遺漏參數」錯誤 (最常見的)
            if isinstance(error, commands.MissingRequiredArgument):
                # 唯一需要參數的是 'play'
                if ctx.command.name in ['play', 'p']:
                    await ctx.send(
                        f"⚠️ **您忘記提供歌曲名稱或連結了！**\n\n"
                        f"**👉 正確格式：**\n"
                        f"`{ctx.prefix}{ctx.command.name} [YouTube 關鍵字或 URL]`\n"
                        f"**範例：** `{ctx.prefix}{ctx.command.name} Never Gonna Give You Up`"
                    )
                else:
                    # 備用 (雖然此 Cog 其他指令目前不需要參數)
                    await ctx.send(f"⚠️ **參數遺漏錯誤：** 您忘記提供 `{error.param.name}` 參數了！")

            # 4. 處理「權限不足」錯誤 (例如 @commands.has_permissions)
            elif isinstance(error, commands.MissingPermissions):
                await ctx.send("❌ **權限不足：** 您沒有權限執行此指令。", delete_after=10)

            # 5. 處理指令內部的 Check 失敗 (例如 @commands.check)
            elif isinstance(error, commands.CheckFailure):
                 await ctx.send(f"❌ **指令檢查失敗：** {error}", delete_after=10)

            # 6. 忽略其他錯誤，讓它繼續傳播
            else:
                # ✅ 4. print 改 logging
                # 可以在這裡印出未處理的錯誤，方便偵錯
                logging.warning(f"MusicPlay Cog 中未處理的錯誤: {error}")
                pass
        
        else:
            # 7. 讓其他指令的錯誤繼續由 bot.py 或其他 Cog 處理
            # (這段邏輯是從您的 calendar.py 和 musiclist.py 複製過來的)
            if self.bot.extra_events.get('on_command_error', None) is not None:
                 await self.bot.on_command_error(ctx, error)
            else:
                 # ✅ 5. print 改 logging
                 # 如果沒有其他監聽器，則引發錯誤
                 logging.error(f"來自其他 Cog 的錯誤 (在 MusicPlay 中捕獲): {error}")


async def setup(bot):
    await bot.add_cog(MusicPlay(bot))