# 檔案名稱: cmds/help.py

import discord
from discord.ext import commands
from core.classes import Cog_Extension # 引入您的核心 Cog
from discord import app_commands
import os
from typing import Dict, List

class Help(Cog_Extension):
    
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        # 立即移除 discord.py 預設的 help 指令
        # 這樣我們的自訂 help 指令才能生效
        self.bot.remove_command('help')

    # =========================================================
    # ✅ 核心指令：Help (已升級為 Hybrid)
    # =========================================================
    @commands.hybrid_command(
        name="help", 
        aliases=['說明', '幫助', 'h'], 
        description="顯示所有可用的指令說明"
    )
    async def help_command(self, ctx: commands.Context):
        """顯示所有可用的指令說明"""
        
        is_private = ctx.interaction is not None
        
        # 獲取當前使用的前綴 (在 bot.py 中設定為 '#')
        prefix = ctx.prefix if ctx.prefix else "#"

        # 1. 建立主 Embed
        embed = discord.Embed(
            title="🤖 NBot 指令說明",
            description=f"您可以使用 `{prefix}指令` (公開) 或 `/指令` (私人) 來呼叫。\n(標示 `[Admin]` 的指令僅限管理員或特定頻道使用)",
            color=discord.Color.from_rgb(114, 137, 218) # Discord 藍
        )
        if self.bot.user and self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        # 2. 定義您希望的 Cog 順序與顯示名稱
        #    (您可以調整這裡的順序)
        cog_display_map: Dict[str, str] = {
            "MusicPlay": "🎵 音樂播放",
            "Music": "📀 音樂清單管理",
            "Calendar": "📅 日曆行程",
            "EnrollmentMonitor": "📚 課程監測",
            "IPCrawler": "📈 IP 流量監測",
            "Main": "⚙️ 核心功能",
            # "Help": "🤖 幫助" # (我們通常不在 help 中顯示 help)
        }

        # 3. 遍歷所有已載入的 Cogs
        all_cogs: Dict[str, commands.Cog] = self.bot.cogs
        
        for cog_name, display_name in cog_display_map.items():
            if cog_name in all_cogs:
                cog = all_cogs[cog_name]
                
                # 獲取該 Cog 底下的所有 Hybrid 指令
                # (commands.HybridCommandGroup 也算是 HybridCommand)
                commands_list: List[commands.HybridCommand] = [
                    cmd for cmd in cog.get_commands() 
                    if isinstance(cmd, (commands.HybridCommand, commands.HybridGroup))
                ]
                
                if not commands_list:
                    continue # 如果這個 Cog 沒有 Hybrid 指令，就跳過

                command_text_lines = []
                for cmd in commands_list:
                    # 獲取指令的簡短說明 (優先使用 description)
                    description = cmd.description or cmd.short_doc or "沒有說明"
                    
                    # 處理指令群組 (例如 monitor)
                    if isinstance(cmd, commands.HybridGroup):
                        # 獲取子指令
                        sub_cmds = [
                            f"`{prefix}{cmd.name} {sub.name}`" 
                            for sub in cmd.commands 
                            if isinstance(sub, commands.Command)
                        ]
                        
                        if sub_cmds:
                            # 顯示主指令和它所有的子指令
                            command_text_lines.append(f"**`{prefix}{cmd.name}`**: {description}")
                            command_text_lines.append(f"└ 子指令: {', '.join(sub_cmds)}")
                        else:
                            # 雖然是群組，但可能沒有子指令 (例如 /monitor 本身)
                            command_text_lines.append(f"`{prefix}{cmd.name}` - {description}")
                    else:
                        # 這是一般的 Hybrid 指令 (例如 play)
                        command_text_lines.append(f"`{prefix}{cmd.name}` - {description}")

                if command_text_lines:
                    embed.add_field(
                        name=display_name,
                        value="\n".join(command_text_lines),
                        inline=False
                    )

        embed.set_footer(text=f"©宿宿小夥伴 | {ctx.guild.name if ctx.guild else 'DM 中'} | 使用 {prefix}help 或 /help")

        # 4. 發送回覆
        await ctx.send(embed=embed, ephemeral=is_private)

# =========================================================
# 載入 Cog 的必要函式
# =========================================================
async def setup(bot):
    await bot.add_cog(Help(bot))
