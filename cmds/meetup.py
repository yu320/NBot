import discord
from discord.ext import commands, tasks
from core.classes import Cog_Extension
import json
import os
import asyncio
import logging
import re
import urllib.parse 
from discord import app_commands
from typing import List, Dict, Any, Optional
from datetime import datetime

# --- 設定常量 ---
MEETUP_FILE = './data/meetup_list.json' 
MEETUP_ROLE_PREFIX = "Eat-" 
MEETUP_REACTION_EMOJI = "✋" 

#
# ✅ (安全版) 填入您在 Discord 伺服器中建立的身份組名稱
#
REQUIRED_ROLE_NAME = "宿宿好夥伴" 


class Meetup(Cog_Extension):
    
    def __init__(self, bot):
        super().__init__(bot)
        
        os.makedirs('./data', exist_ok=True)
        if not os.path.exists(MEETUP_FILE):
            self._save_meetup_list([])
            
    # --- JSON 輔助函式 ---
    def _load_meetup_list(self) -> List[Dict[str, Any]]:
        try:
            with open(MEETUP_FILE, 'r', encoding='utf8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"載入 {MEETUP_FILE} 失敗: {e}")
            return []

    def _save_meetup_list(self, meetup_list: List[Dict[str, Any]]):
        try:
            with open(MEETUP_FILE, 'w', encoding='utf8') as f:
                json.dump(meetup_list, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.error(f"儲存 {MEETUP_FILE} 失敗: {e}")

    # --- 輔助函式：透過 Message ID 尋找戰鬥邀請 ---
    def _find_meetup(self, message_id: int) -> Optional[Dict[str, Any]]:
        meetup_list = self._load_meetup_list()
        for meetup in meetup_list:
            if meetup.get('message_id') == message_id:
                return meetup
        return None

    # --- 輔助函式：產生 Google Map 連結 ---
    def _generate_google_maps_link(self, query: str) -> str:
        encoded_query = urllib.parse.quote(query)
        return f"https://www.google.com/maps/search/?api=1&query={encoded_query}"

    # --- 輔助函式：建立戰鬥邀請 Embed ---
    def _create_meetup_embed(
        self, 
        ctx: commands.Context, 
        title: str, 
        location: str, 
        location_url: str,
        time: Optional[str] = None, 
        description: Optional[str] = None,
        status: str = "SCHEDULED" 
    ) -> discord.Embed:
        
        if status == "CANCELED":
            embed_color = discord.Color.red()
            embed_title = f"❌ [已取消] {title}"
        else:
            embed_color = discord.Color.green()
            embed_title = f"🎉 {title}"

        embed = discord.Embed(
            title=embed_title,
            color=embed_color
        )
        embed.set_author(name=f"主揪： {ctx.author.display_name}", icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
        embed.add_field(name="📍 地點", value=f"[{location}]({location_url})", inline=False)
        if time:
            embed.add_field(name="⏰ 時間", value=time, inline=False)
        if description:
            embed.add_field(name="📝 備註", value=description, inline=False)
        if status == "SCHEDULED":
             embed.add_field(
                name="如何報名", 
                value=f"點擊下方的 {MEETUP_REACTION_EMOJI} 表情符號即可加入身份組！", 
                inline=False
            )
        embed.set_footer(text=f"戰鬥邀請發起於: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        return embed

    # =========================================================
    # 1. 錯誤處理 (Error Handler) - ✅ 已更新
    # =========================================================
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        
        if ctx.command and ctx.command.cog_name != 'Meetup':
            return 
            
        logging.warning(f"Meetup Cog 捕獲到指令錯誤 (指令: {ctx.command}, 錯誤: {error})")
        is_private = ctx.interaction is not None
        
        if ctx.command and (ctx.command.name == 'eat' or (ctx.command.root_parent and ctx.command.root_parent.name == 'eat')):
            
            #
            # ✅ 這就是您要求的修改：
            #
            if isinstance(error, commands.MissingRequiredArgument):
                
                param_name_tw = "參數" # 預設
                if error.param.name == 'title':
                    param_name_tw = "戰鬥邀請標題"
                elif error.param.name == 'location':
                    param_name_tw = "地點"
                elif error.param.name == 'message_id':
                    param_name_tw = "戰鬥邀請訊息ID"
                elif error.param.name == 'new_location':
                    param_name_tw = "新地點"

                prefix = ctx.prefix if ctx.prefix else "#"
                
                # 基礎錯誤訊息
                error_msg = f"⚠️ **參數遺漏錯誤：** 您忘記提供「**{param_name_tw}**」(`{error.param.name}`) 參數了！\n\n"
                
                # --- 根據不同的子指令，提供不同的教學範例 ---
                
                # 1. 如果是在 `add` 指令出錯 (例如: #eat add)
                if ctx.command.name == 'add':
                    error_msg += (
                        f"**👉 正確格式：**\n"
                        f"`{prefix}eat add \"[標題]\" \"[地點]\" [時間(選填)] [備註(選填)]`\n\n"
                        f"**範例 (僅標題地點)：**\n"
                        f"`{prefix}eat add \"晚餐團\" \"斗六麥當勞\"`\n\n"
                        f"**範例 (完整)：**\n"
                        f"`{prefix}eat add \"聖誕派對\" \"學生餐廳\" \"12/25 18:00\" \"要交換禮物\"`\n\n"
                        f"**💡 提醒：** 如果您的標題或地點包含**空格** (例如: 斗六 麥當勞)，請務必使用**雙引號 `\" \"`** 將它包起來。"
                    )
                
                # 2. 如果是在 `edit_location` 指令出錯
                elif ctx.command.name == 'edit_location':
                     error_msg += (
                        f"**👉 正確格式：**\n"
                        f"`{prefix}eat edit_location [戰鬥邀請訊息ID] \"[新地點]\"`\n\n"
                        f"**範例：**\n"
                        f"`{prefix}eat edit_location 1234567890 \"斗六肯德基\"`\n\n"
                        f"**💡 提醒：** 同樣，如果新地點包含空格，請使用雙引號 `\" \"`。"
                    )
                
                # 3. 如果是在 `cancel` 指令出錯
                elif ctx.command.name == 'cancel':
                     error_msg += (
                        f"**👉 正確格式：**\n"
                        f"`{prefix}eat cancel [戰鬥邀請訊息ID]`\n\n"
                        f"**範例：**\n"
                        f"`{prefix}eat cancel 1234567890`"
                    )
                
                await ctx.send(error_msg, ephemeral=is_private)

            
            elif isinstance(error, commands.BadArgument):
                error_msg = f"⚠️ **參數類型錯誤！**"
                # 檢查是否為 message_id 轉換失敗
                if 'message_id' in str(error): 
                     error_msg = f"⚠️ **參數類型錯誤：** `戰鬥邀請訊息ID` 必須是純數字。\n請在戰鬥邀請卡片上按右鍵 -> `複製訊息 ID`。"
                
                await ctx.send(error_msg, ephemeral=is_private)

            elif isinstance(error, commands.MissingRole):
                await ctx.send(f"❌ **權限不足：** 您需要擁有「{error.missing_role}」身份組才能發起戰鬥邀請。", ephemeral=True)

            elif isinstance(error, commands.MissingPermissions):
                await ctx.send("❌ **權限不足：** 您需要「管理伺服器」權限才能修改或取消戰鬥邀請。", ephemeral=True)
            
            else:
                pass # 其他錯誤上報給 bot.py

    # =========================================================
    # 2. 關鍵字監聽 (Keyword Listener)
    # =========================================================
    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author == self.bot.user:
            return
        if "想要吃" in msg.content or "想去吃" in msg.content or "吃" in msg.content  or "想去" in msg.content or "攀岩" in msg.content or "要去" in msg.content:# 檢查關鍵字
            try:
                await msg.channel.send(f"想揪團了嗎？ {msg.author.mention} \n試試看使用 `/eat add` 或 `{self.bot.command_prefix}eat add` 來發起一個戰鬥邀請吧！", delete_after=15)
            except discord.Forbidden:
                pass 
            except Exception as e:
                logging.warning(f"Meetup on_message 回覆失敗: {e}")

    # =========================================================
    # 3. 表情符號監聽 (Reaction Listeners)
    # =========================================================
    
    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, action: str):
        if payload.user_id == self.bot.user.id:
            return
        if str(payload.emoji) != MEETUP_REACTION_EMOJI:
            return
        meetup = self._find_meetup(payload.message_id)
        if not meetup:
            return 
        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
        role_id = meetup.get('role_id')
        if not role_id: return
        role = guild.get_role(role_id)
        if not role:
            logging.warning(f"Meetup {payload.message_id}：找不到對應的身份組 ID {role_id}。")
            return
        try:
            member = payload.member or await guild.fetch_member(payload.user_id)
        except discord.NotFound:
            return
        except Exception as e:
            logging.error(f"Meetup: 抓取成員 {payload.user_id} 時失敗: {e}")
            return
        if not member: 
            return 
        try:
            if action == 'add' and (role not in member.roles):
                await member.add_roles(role, reason="Meetup Reaction Join")
            elif action == 'remove' and (role in member.roles):
                await member.remove_roles(role, reason="Meetup Reaction Leave")
        except discord.Forbidden:
            logging.error(f"[Meetup] Bot權限不足，無法操作身份組 {role.name}。")
        except Exception as e:
            logging.error(f"[Meetup] 操作身份組時失敗: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload, action='add')

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload, action='remove')

    # =========================================================
    # 4. 指令群組 (Hybrid Command Group)
    # =========================================================
    
    @commands.hybrid_group(name='eat', aliases=['約吃飯', '吃飯'], description="管理戰鬥邀請")
    async def eat(self, ctx: commands.Context):
        is_private = ctx.interaction is not None
        if ctx.invoked_subcommand is None:
            prefix = ctx.prefix
            embed = discord.Embed(title="🍜 戰鬥邀請管理", description="這是一系列管理戰鬥邀請的指令。", color=0xFF8C00)
            embed.add_field(name=f"1. 發起戰鬥邀請 (需 {REQUIRED_ROLE_NAME} 身份組)", value=f"`{prefix}eat add [標題] [地點] [時間(選填)] [備註(選填)]`", inline=False)
            embed.add_field(name="2. 修改地點 (僅限發起人/管理員)", value=f"`{prefix}eat edit_location [戰鬥邀請訊息ID] [新地點]`", inline=False)
            embed.add_field(name="3. 取消戰鬥邀請 (僅限發起人/管理員)", value=f"`{prefix}eat cancel [戰鬥邀請訊息ID]`", inline=False)
            await ctx.send(embed=embed, ephemeral=is_private)

    # --- 4.1 子指令：add (發起戰鬥邀請) ---
    @eat.command(name='add', aliases=['發起', 'create'], description="發起一個新的戰鬥邀請")
    @app_commands.describe(
        title="戰鬥邀請標題 (例如: 晚餐團)",
        location="地點 (例如: 麥當勞 斗六中山店)",
        time="時間 (選填, 例如: 18:00)",
        description="備註 (選填, 例如: 吃完去逛夜市)"
    )
    @commands.has_role(REQUIRED_ROLE_NAME) 
    async def add_meetup(self, ctx: commands.Context, title: str, location: str, time: Optional[str] = None, *, description: Optional[str] = None):
        
        is_private = ctx.interaction is not None
        
        if not ctx.guild.me.guild_permissions.manage_roles:
            return await ctx.send("❌ 錯誤：Bot 需要「管理身份組」權限才能建立戰鬥邀請。", ephemeral=True) 

        role_name = f"{MEETUP_ROLE_PREFIX}{title}"
        existing_role = discord.utils.get(ctx.guild.roles, name=role_name)
        
        if existing_role:
            return await ctx.send(f"❌ 錯誤：身份組 `{role_name}` 已經存在，請換一個戰鬥邀請標題。", ephemeral=True)
            
        try:
            new_role = await ctx.guild.create_role(
                name=role_name, 
                permissions=discord.Permissions.none(), 
                mentionable=True, 
                reason=f"由 {ctx.author} 發起的戰鬥邀請"
            )
        except discord.Forbidden:
            return await ctx.send("❌ 錯誤：Bot 權限不足，無法建立身份組。", ephemeral=True)
        except Exception as e:
            return await ctx.send(f"❌ 建立身份組時發生未知錯誤: {e}", ephemeral=True)

        location_url = self._generate_google_maps_link(location)
        embed = self._create_meetup_embed(ctx, title, location, location_url, time, description, status="SCHEDULED")
        
        try:
            meetup_message = await ctx.send(embed=embed)
            await meetup_message.add_reaction(MEETUP_REACTION_EMOJI)
        except discord.Forbidden:
            await ctx.send("❌ 錯誤：Bot 無法在此頻道發送訊息或新增反應。", ephemeral=True)
            await new_role.delete(reason="Meetup message send failed")
            return
            
        new_meetup_data = {
            "message_id": meetup_message.id,
            "channel_id": ctx.channel.id,
            "role_id": new_role.id,
            "creator_id": ctx.author.id,
            "title": title
        }
        meetup_list = self._load_meetup_list()
        meetup_list.append(new_meetup_data)
        self._save_meetup_list(meetup_list)
        
        await ctx.send("✅ 戰鬥邀請已成功發起！", ephemeral=True)


    # --- 4.2 子指令：edit_location (修改地點) ---
    @eat.command(name='edit_location', aliases=['修改地點'], description="修改一個已發起戰鬥邀請的地點")
    @app_commands.describe(
        message_id="戰鬥邀請訊息的 ID (在訊息上按右鍵 -> 複製訊息 ID)",
        new_location="新的地點 (例如: 肯德基 斗六店)"
    )
    async def edit_location(self, ctx: commands.Context, message_id: str, *, new_location: str):
        is_private = ctx.interaction is not None
        
        try:
            msg_id_int = int(message_id)
        except ValueError:
            return await ctx.send("❌ 錯誤：訊息 ID 必須是純數字。", ephemeral=True)

        meetup = self._find_meetup(msg_id_int)
        if not meetup:
            return await ctx.send("❌ 錯誤：找不到此戰鬥邀請 ID。", ephemeral=is_private)
            
        if not (ctx.author.id == meetup['creator_id'] or ctx.author.guild_permissions.manage_guild):
            return await ctx.send("❌ 權限不足：只有戰鬥邀請發起人或伺服器管理員才能修改。", ephemeral=is_private)
            
        try:
            target_channel = self.bot.get_channel(meetup['channel_id'])
            if not target_channel:
                 return await ctx.send(f"❌ 錯誤：找不到原始頻道 (ID: {meetup['channel_id']})。", ephemeral=is_private)
                 
            meetup_message = await target_channel.fetch_message(msg_id_int)
            new_location_url = self._generate_google_maps_link(new_location)
            
            if not meetup_message.embeds:
                 return await ctx.send(f"❌ 錯誤：原始訊息沒有 Embed。", ephemeral=is_private)
                 
            old_embed = meetup_message.embeds[0]
            old_embed.set_field_at(
                index=0, 
                name="📍 地點", 
                value=f"[{new_location}]({new_location_url})", 
                inline=False
            )
            await meetup_message.edit(embed=old_embed)
            
            await target_channel.send(f"📢 {MEETUP_REACTION_EMOJI} 戰鬥邀請「{meetup['title']}」的地點已更新！ <@&{meetup['role_id']}>", delete_after=300)
            await ctx.send("✅ 地點已成功更新。", ephemeral=is_private)

        except discord.NotFound:
            await ctx.send("❌ 錯誤：找不到原始的戰鬥邀請訊息。", ephemeral=is_private)
        except Exception as e:
            await ctx.send(f"❌ 更新時發生錯誤: {e}", ephemeral=is_private)
            logging.error(f"Meetup edit_location 失敗: {e}", exc_info=True)


    # --- 4.3 子指令：cancel (取消戰鬥邀請) ---
    @eat.command(name='cancel', aliases=['取消'], description="取消一個已發起的戰鬥邀請")
    @app_commands.describe(
        message_id="戰鬥邀請訊息的 ID (在訊息上按右鍵 -> 複製訊息 ID)"
    )
    async def cancel_meetup(self, ctx: commands.Context, message_id: str):
        is_private = ctx.interaction is not None
        
        try:
            msg_id_int = int(message_id)
        except ValueError:
            return await ctx.send("❌ 錯誤：訊息 ID 必須是純數字。", ephemeral=True)

        meetup = self._find_meetup(msg_id_int)
        if not meetup:
            return await ctx.send("❌ 錯誤：找不到此戰鬥邀請 ID。", ephemeral=is_private)
            
        if not (ctx.author.id == meetup['creator_id'] or ctx.author.guild_permissions.manage_guild):
            return await ctx.send("❌ 權限不足：只有戰鬥邀請發起人或伺服器管理員才能取消。", ephemeral=is_private)
            
        try:
            role = ctx.guild.get_role(meetup['role_id'])
            if role:
                await role.delete(reason=f"Meetup canceled by {ctx.author}")
                
            target_channel = self.bot.get_channel(meetup['channel_id'])
            if target_channel:
                meetup_message = await target_channel.fetch_message(msg_id_int)
                
                if meetup_message.embeds:
                    old_embed = meetup_message.embeds[0]
                    class FakeAuthor:
                        def __init__(self, creator_id, guild):
                            self.id = creator_id
                            self.guild = guild
                            self.display_name = f"User (ID: {creator_id})"
                            self.avatar = None
                            try:
                                member = guild.get_member(creator_id)
                                if member:
                                    self.display_name = member.display_name
                                    self.avatar = member.avatar
                            except: pass
                    class FakeContext:
                         def __init__(self, author):
                            self.author = author
                    fake_author = FakeAuthor(meetup['creator_id'], ctx.guild)
                    fake_ctx = FakeContext(fake_author)
                    title = meetup.get('title', old_embed.title)
                    location = old_embed.fields[0].value if old_embed.fields else "N/A"
                    time = old_embed.fields[1].value if len(old_embed.fields) > 1 else None
                    desc = old_embed.fields[2].value if len(old_embed.fields) > 2 else None
                    canceled_embed = self._create_meetup_embed(
                        fake_ctx, title, location, "#", time, desc, status="CANCELED"
                    )
                    await meetup_message.edit(embed=canceled_embed)
                    await meetup_message.clear_reactions()
                
            meetup_list = self._load_meetup_list()
            meetup_list = [m for m in meetup_list if m['message_id'] != msg_id_int]
            self._save_meetup_list(meetup_list)
            
            await ctx.send(f"✅ 已成功取消戰鬥邀請「{meetup['title']}」並刪除身份組。", ephemeral=is_private)

        except discord.NotFound:
            await ctx.send("❌ 錯誤：找不到原始的戰鬥邀請訊息或身份組。", ephemeral=is_private)
        except discord.Forbidden:
             await ctx.send("❌ 錯誤：Bot 權限不足。", ephemeral=is_private)
        except Exception as e:
            await ctx.send(f"❌ 取消時發生錯誤: {e}", ephemeral=is_private)
            logging.error(f"Meetup cancel 失敗: {e}", exc_info=True)


async def setup(bot):
    await bot.add_cog(Meetup(bot))
