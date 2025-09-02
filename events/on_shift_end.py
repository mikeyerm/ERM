import asyncio
import datetime

import aiohttp
import discord
from bson import ObjectId
from discord.ext import commands
from datamodels.ShiftManagement import ShiftItem
from utils.constants import BLANK_COLOR
from utils.timestamp import td_format
from decouple import config


class OnShiftEnd(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_shift_end(self, object_id: ObjectId):

        document = await self.bot.shift_management.shifts.find_by_id(object_id)
        if not document:
            return
        shift: ShiftItem = await self.bot.shift_management.fetch_shift(object_id)

        url_var = config("BASE_API_URL")
        panel_url_var = config("PANEL_API_URL")

        guild_id = document["Guild"]
        
        async def sync_end_with_apis():
            async with aiohttp.ClientSession() as session:
                tasks = []

                if url_var not in ["", None]:
                    tasks.append(
                        session.get(
                            f"{url_var}/Internal/SyncEndShift/{document['UserID']}/{guild_id}",
                            headers={"Authorization": config("INTERNAL_API_AUTH")},
                            raise_for_status=True,
                        )
                    )

                if panel_url_var not in ["", None]:
                    tasks.append(
                        session.delete(
                            f"{panel_url_var}/{guild_id}/SyncEndShift?ID={document['_id']}",
                            headers={"X-Static-Token": config("PANEL_STATIC_AUTH")},
                            raise_for_status=True,
                        )
                    )

                if tasks:
                    responses = await asyncio.gather(*tasks, return_exceptions=True)
                    for response in responses:
                        if isinstance(response, Exception):
                            self.logger.error(
                                f"End shift API sync failed: {str(response)}"
                            )

        try:
            await sync_end_with_apis()
        except aiohttp.ClientError as e:
            self.logger.error(f"Failed to sync shift end with APIs: {str(e)}")
        except Exception as e:
            self.logger.error(f"Unexpected error during end shift API sync: {str(e)}")

        guild: discord.Guild = self.bot.get_guild(shift.guild)
        if guild is None:
            return

        guild_settings = await self.bot.settings.find_by_id(guild.id)
        if not guild_settings:
            return

        shift_type = shift.type
        custom_shift_type = None
        if shift_type != "Default":
            total_shift_types = guild_settings.get("shift_types", {"types": []})
            for item in total_shift_types["types"]:
                if item["name"] == shift_type:
                    custom_shift_type = item

        assigned_roles = []
        break_roles = []
        if custom_shift_type is None:
            try:
                channel = await guild.fetch_channel(
                    guild_settings.get("shift_management").get("channel", 0)
                )
            except discord.HTTPException:
                channel = None
            nickname_prefix = guild_settings.get("shift_management").get(
                "nickname_prefix", None
            )
            assigned_roles = guild_settings.get("shift_management").get("role", [])
            break_roles = guild_settings.get("shift_management").get("break_roles", [])
        else:
            try:
                channel = await guild.fetch_channel(custom_shift_type.get("channel", 0))
            except discord.HTTPException:
                try:
                    channel = await guild.fetch_channel(
                        guild_settings.get("shift_management").get("channel", 0)
                    )
                except discord.HTTPException:
                    channel = None
            nickname_prefix = custom_shift_type.get("nickname", None)
            assigned_roles = custom_shift_type.get("role", [])
            break_roles = custom_shift_type.get("break_roles", [])

        try:
            staff_member: discord.Member = await guild.fetch_member(shift.user_id)
        except discord.NotFound:
            return

        if not staff_member:
            return
        for role in assigned_roles or []:
            discord_role: discord.Role = guild.get_role(role)
            if discord_role is None:
                continue
            try:
                await staff_member.remove_roles(discord_role, atomic=True)
            except discord.HTTPException:
                pass

        for role in break_roles or []:
            discord_role: discord.Role = guild.get_role(role)
            if discord_role is None:
                continue
            try:
                await staff_member.remove_roles(discord_role, atomic=True)
            except discord.HTTPException:
                pass

        if nickname_prefix is not None:
            try:
                await staff_member.edit(
                    nick=f"{(staff_member.nick or staff_member.display_name).removeprefix(nickname_prefix)}"
                )
            except discord.HTTPException:
                pass

        moderation_counts = {}
        for entry in shift.moderations:
            entry = await self.bot.punishments.fetch_warning(str(entry))

            if entry.warning_type in moderation_counts:
                moderation_counts[entry.warning_type] += 1
            else:
                moderation_counts[entry.warning_type] = 1

          # ✅ Count total shifts for this staff member in this guild
        total_shifts = await self.bot.shift_management.shifts.count_documents({
            "user_id": shift.user_id,
            "guild": shift.guild
        })

        if channel is not None:
            await channel.send(
                embed=discord.Embed(title="Shift Ended", color=BLANK_COLOR)
                .add_field(
                    name="Shift Information",
                    value=(
                        f"> **Staff Member:** {staff_member.mention}\n"
                        f"> **Shift Type:** {shift_type}\n"
                        f"> **Total Shifts:** {total_shifts}\n"   # total_shifts defined within here - Doesn't rely on prior code
                    ),
                    inline=False,
                )

                )
                .add_field(
                    name="Other Information",
                    value=(
                        f"> **Shift Start:** <t:{int(shift.start_epoch)}>\n"
                        f"> **Shift End:** <t:{int(shift.end_epoch)}>\n"
                        f"> **Shift Length:** {td_format(datetime.timedelta(seconds=shift.end_epoch - shift.start_epoch - (sum((br.end_epoch) - (br.start_epoch) for br in shift.breaks)) + (shift.added_time if shift.added_time > (86400 * 7) else 0) - (shift.removed_time if shift.removed_time > (86400 * 7) else 0)))}\n"
                        f"> **Nickname:** `{shift.nickname}`\n"
                    ),
                    inline=False,
                )
                .add_field(
                    name="Moderation Details:",
                    value=(
                        "\n".join(
                            [
                                f"> **{moderation_type.capitalize()}s:** {count}"
                                for moderation_type, count in moderation_counts.items()
                            ]
                        )
                        if moderation_counts
                        else "> No Moderations Found"
                    ),
                    inline=False,
                )
                .set_author(
                    name=guild.name, icon_url=guild.icon.url if guild.icon else ""
                )
                .set_thumbnail(url=staff_member.display_avatar.url)
            )
        shift_reports_enabled = True
        async for document in self.bot.consent.db.find({"_id": staff_member.id}):
            shift_reports_enabled = (
                document.get("shift_reports")
                if document.get("shift_reports") is not None
                else True
            )
        if shift_reports_enabled:
            embed = (
                discord.Embed(title="Shift Report", color=BLANK_COLOR)
                .add_field(
                    name="Shift Information",
                    value=(
                        f"> **Shift Type:** {shift_type}\n"
                        f"> **Shift Start:** <t:{int(shift.start_epoch)}>\n"
                        f"> **Shift End:** <t:{int(shift.end_epoch)}>\n"
                        f"> **Nickname:** `{shift.nickname}`\n"
                    ),
                    inline=False,
                )
                .add_field(
                    name="Total Moderations:",
                    value=(
                        "\n".join(
                            [
                                f"> **{moderation_type.capitalize()}s:** {count}"
                                for moderation_type, count in moderation_counts.items()
                            ]
                        )
                        if moderation_counts
                        else "> No Moderations Found"
                    ),
                    inline=False,
                )
                .add_field(
                    name="Elapsed Time",
                    value=f"> {td_format(datetime.timedelta(seconds=shift.end_epoch - shift.start_epoch - (sum((br.end_epoch) - (br.start_epoch) for br in shift.breaks)) + (shift.added_time if shift.added_time > (86400 * 7) else 0) - (shift.removed_time if shift.removed_time > (86400 * 7) else 0)))}",
                    inline=False,
                )
                .set_thumbnail(url=staff_member.display_avatar.url)
            )
            await staff_member.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(OnShiftEnd(bot))

