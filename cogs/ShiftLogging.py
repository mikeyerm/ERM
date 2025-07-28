import datetime
from io import BytesIO
import logging

import discord
import pytz
from decouple import config
from discord import app_commands
from discord.ext import commands

from datamodels.ShiftManagement import ShiftItem
from erm import (
    credentials_dict,
    is_management,
    is_staff,
    is_admin,
    management_predicate,
    scope,
)
from menus import (
    CustomExecutionButton,
    CustomSelectMenu,
    RequestGoogleSpreadsheet,
    ShiftMenu,
    AdministratedShiftMenu,
)
from utils.autocompletes import shift_type_autocomplete, all_shift_type_autocomplete
from utils.constants import BLANK_COLOR, GREEN_COLOR, ORANGE_COLOR, RED_COLOR
from utils.paginators import SelectPagination, CustomPage
from utils.timestamp import td_format
from utils.utils import (
    get_elapsed_time,
    new_failure_embed,
    require_settings,
    log_command_usage,
)


class ShiftLogging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_group(
        name="duty"
    ) # hey, maybe dont delete this next time noagonzales.
    async def duty(self, ctx):
        pass
    

    @commands.guild_only()
    @duty.command(
        name="time",
        description="Allows you to check your shift time, as well as past data.",
        extras={"category": "Shift Management"},
        with_app_command=True,
    )
    @is_staff()
    @require_settings()
    @app_commands.describe(member = "The staff member to view shifts for.", shift_type="The type of shift to view.")
    @app_commands.autocomplete(shift_type=shift_type_autocomplete)
    async def duty_time(self, ctx, member: discord.Member = None, shift_type: str = "Default"):
        if self.bot.shift_management_disabled:
            return await new_failure_embed(
                ctx,
                "Maintenance",
                "This command is currently disabled as ERM is currently undergoing maintenance updates. This command will be turned off briefly to ensure that no data is lost during the maintenance.",
            )

        bot = self.bot
        if not member:
            member = ctx.author

        configItem = await bot.settings.find_by_id(ctx.guild.id)
        if not configItem.get("shift_management", {}).get("enabled", False):
            return await new_failure_embed(ctx, "Not Enabled", "Shift Logging is not enabled on this server.")

        shift_types = configItem.get("shift_types", {}).get("types", [])
        selected_shift_type = None
        shift_type_value = (shift_type or "").lower()

        msg = None

        if shift_types and len(shift_types) > 1:
            if shift_type_value != "all" and shift_type_value not in [st["name"].lower() for st in shift_types]:
                view = CustomSelectMenu(
                    ctx.author.id,
                    [
                        discord.SelectOption(label=st["name"], value=st["name"]) for st in shift_types
                    ] + [
                        discord.SelectOption(label="All", value="all", description="All shift types")
                    ],
                )
                msg = await ctx.reply(
                    embed=discord.Embed(title="Incorrect Shift Type",
                                        description="The shift type provided is not valid.",
                                        color=BLANK_COLOR),
                    view=view,
                )
                timeout = await view.wait()
                if timeout:
                    return
                shift_type_value = view.value.lower()

        if shift_type_value == "all":
            selected_shift_type = None
        else:
            selected_shift_type = next((st for st in shift_types if st["name"].lower() == shift_type_value), None)
            if not selected_shift_type:
                return await new_failure_embed(ctx, "Error", "Invalid shift type selected.")

        total_seconds = 0
        active_shift = await bot.shift_management.get_current_shift(member, ctx.guild.id)
        shifts = []
        query = {"UserID": member.id, "Guild": ctx.guild.id}
        if selected_shift_type:
            query["Type"] = selected_shift_type["name"]

        storage_item = [i async for i in bot.shift_management.shifts.db.find(query)]
        for s in storage_item:
            if s["EndEpoch"] != 0:
                shifts.append(s)
                total_seconds += get_elapsed_time(s)

        selected_quota = configItem.get("shift_management", {}).get("quota", 0)
        for role in sorted(member.roles, key=lambda r: r.position, reverse=True):
            role_quota = next(
                (r for r in configItem.get("shift_management", {}).get("role_quotas", []) if r["role"] == role.id),
                None)
            if role_quota:
                selected_quota = role_quota["quota"]
                break

        met_quota = total_seconds >= selected_quota if selected_quota > 0 else None

        embed = discord.Embed(
            title=(f"Total Shifts" if member == ctx.author else f"{member.name}'s Total Shifts"),
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

        if active_shift:
            embed.add_field(name="Ongoing Shift",
                            value=td_format(datetime.timedelta(seconds=get_elapsed_time(active_shift))), inline=False)


        # we need support for old python versions
        newline = "\n"

        embed.add_field(
            name=f"Shift Time [{len(shifts)}]",
            value=f"{td_format(datetime.timedelta(seconds=total_seconds))} {'{}*Met Quota*'.format(newline) if met_quota else '{}*Not Met Quota*'.format(newline) if met_quota is not None else ''}",
        )

        embed.set_thumbnail(url=member.display_avatar.url)

        if msg:
            await msg.edit(embed=embed, view=None)
        else:
            await ctx.reply(embed=embed)

    @duty.command(
        name="admin",
        description="Allows for you to administrate someone else's shift",
        extras={"category": "Shift Management"},
    )
    @require_settings()
    @is_admin()
    @app_commands.autocomplete(type=shift_type_autocomplete)
    async def duty_admin(
        self, ctx, member: discord.Member, type: str = "Default", force: str = "false"
    ):
        if self.bot.shift_management_disabled is True:
            return await new_failure_embed(
                ctx,
                "Maintenance",
                "This command is currently disabled as ERM is currently undergoing maintenance updates. This command will be turned off briefly to ensure that no data is lost during the maintenance.",
            )

        settings = await self.bot.settings.find_by_id(ctx.guild.id)
        if not settings.get("shift_management", {}).get("enabled", False):
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description="Shift Logging is not enabled on this server.",
                    color=BLANK_COLOR,
                )
            )
        msg = None
        shift_types = settings.get("shift_types", {}).get("types", [])
        if shift_types:
            if type.lower() not in [t["name"].lower() for t in shift_types]:
                msg = await ctx.send(
                    embed=discord.Embed(
                        title="Incorrect Shift Type",
                        description="The shift type provided is not valid.",
                        color=BLANK_COLOR,
                    ),
                    view=(
                        view := CustomSelectMenu(
                            ctx.author.id,
                            [
                                discord.SelectOption(
                                    label=i["name"],
                                    value=i["name"],
                                    description=i["name"],
                                )
                                for i in shift_types
                            ],
                        )
                    ),
                )
                timeout = await view.wait()
                if timeout:
                    return

                if view.value:
                    type = view.value

            shift_type_item = None
            for item in shift_types:
                if item["name"].lower() == type.lower():
                    shift_type_item = item

            if shift_type_item:
                if shift_type_item.get("access_roles") is not None:
                    item = shift_type_item
                    access_roles = item.get("access_roles") or []
                    if len(access_roles) > 0:
                        access = False
                        for role in access_roles:
                            if role in [i.id for i in member.roles]:
                                access = True
                                break
                        if access is False and force.lower() != "true":
                            if not msg:
                                return await ctx.send(
                                    embed=discord.Embed(
                                        title="Access Denied",
                                        description="This individual does not have access to this shift type.",
                                        color=BLANK_COLOR,
                                    )
                                )
                            else:
                                return await msg.edit(
                                    embed=discord.Embed(
                                        title="Access Denied",
                                        description="This individual does not have access to this shift type.",
                                        color=BLANK_COLOR,
                                    ),
                                    view=None,
                                )
                        elif access is False and force.lower() == "true":
                            pass

        shift = await self.bot.shift_management.get_current_shift(member, ctx.guild.id)
        await log_command_usage(
            self.bot, ctx.guild, ctx.author, f"Duty Admin for {member.name}"
        )
        previous_shifts = [
            i
            async for i in self.bot.shift_management.shifts.db.find(
                {"UserID": member.id, "Guild": ctx.guild.id, "EndEpoch": {"$ne": 0}}
            )
        ]
        embed = discord.Embed(color=BLANK_COLOR)

        embed.add_field(
            name="Current Statistics",
            value=(
                f"> **Total Shift Duration:** {td_format(datetime.timedelta(seconds=sum([get_elapsed_time(item) for item in previous_shifts])))}\n"
                f"> **Total Shifts:** {len(previous_shifts)}\n"
                f"> **Average Shift Duration:** {td_format(datetime.timedelta(seconds=(sum([get_elapsed_time(item) for item in previous_shifts]).__truediv__(len(previous_shifts) or 1))))}\n"
            ),
            inline=False,
        )

        embed.set_author(
            name=ctx.guild.name,
            icon_url=ctx.guild.icon,
        )

        if shift:
            if (shift.get("Breaks", [{}]) or [{}])[-1].get("EndEpoch", 1) == 0:
                status = "break"
            else:
                status = "on"
        else:
            status = "off"

        contained_document = None
        if status == "on":
            contained_document: ShiftItem = await self.bot.shift_management.fetch_shift(
                shift["_id"]
            )
            embed.colour = GREEN_COLOR
            embed.add_field(
                name="Current Shift",
                value=(
                    f"> **Started:** <t:{int(contained_document.start_epoch)}:R>\n"
                    f"> **Breaks:** {len(contained_document.breaks)}\n"
                    f"> **Elapsed Time:** {td_format(datetime.timedelta(seconds=get_elapsed_time(shift)))}"
                ),
                inline=False,
            )
            embed.title = (
                f"{self.bot.emoji_controller.get_emoji('ShiftStarted')} **On-Duty**"
            )
        elif status == "break":
            contained_document: ShiftItem = await self.bot.shift_management.fetch_shift(
                shift["_id"]
            )

            current_break = None
            for break_item in contained_document.breaks:
                if break_item.end_epoch == 0:
                    current_break = break_item
                    break

            if current_break:
                break_start_time = (
                    f"> **Break Started:** <t:{int(current_break.start_epoch)}:R>\n"
                )
            else:
                break_start_time = "> **Break Started:** No ongoing break\n"

            embed.colour = ORANGE_COLOR
            embed.add_field(
                name="Current Shift",
                value=(
                    f"> **Shift Started:** <t:{int(contained_document.start_epoch)}:R>\n"
                    f"{break_start_time}"
                    f"> **Breaks:** {len(contained_document.breaks)}\n"
                    f"> **Elapsed Time:** {td_format(datetime.timedelta(seconds=get_elapsed_time(shift)))}"
                ),
                inline=False,
            )
            embed.title = (
                f"{self.bot.emoji_controller.get_emoji('ShiftBreak')} **On-Break**"
            )
        else:
            embed.colour = RED_COLOR
            embed.title = (
                f"{self.bot.emoji_controller.get_emoji('ShiftEnded')} **Off-Duty**"
            )
        try:
            view = AdministratedShiftMenu(
                self.bot,
                status,
                ctx.author.id,
                member.id,
                (shift_type_item or {}).get("name") or type,
                shift,
                contained_document,
            )
        except UnboundLocalError:
            view = AdministratedShiftMenu(
                self.bot,
                status,
                ctx.author.id,
                member.id,
                type,
                shift,
                contained_document,
            )

        if not msg:
            view.message = await ctx.send(embed=embed, view=view)
        else:
            await msg.edit(embed=embed, view=view)
            view.message = msg

    @commands.guild_only()
    @duty.command(
        name="manage",
        description="Manage your own shift in an easy way!",
        extras={"category": "Shift Management"},
    )
    @is_staff()
    @require_settings()
    @app_commands.autocomplete(type=shift_type_autocomplete)
    async def duty_manage(self, ctx, *, type: str = "Default"):
        settings = await self.bot.settings.find_by_id(ctx.guild.id)
        if not settings.get("shift_management", {}).get("enabled", False):
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description="Shift Logging is not enabled on this server.",
                    color=BLANK_COLOR,
                )
            )

        shift_types = settings.get("shift_types", {}).get("types", [])
        msg = None
        shift_type_item = None
        if shift_types:
            if type.lower() not in [t["name"].lower() for t in shift_types]:
                msg = await ctx.send(
                    embed=discord.Embed(
                        title="Incorrect Shift Type",
                        description="The shift type provided is not valid.",
                        color=BLANK_COLOR,
                    ),
                    view=(
                        view := CustomSelectMenu(
                            ctx.author.id,
                            [
                                discord.SelectOption(
                                    label=i["name"],
                                    value=i["name"],
                                    description=i["name"],
                                )
                                for i in shift_types
                            ],
                        )
                    ),
                )
                timeout = await view.wait()
                if timeout:
                    return

                if view.value:
                    type = view.value

            for item in shift_types:
                if item["name"].lower() == type.lower():
                    shift_type_item = item

            if shift_type_item:
                if shift_type_item.get("access_roles") is not None:
                    item = shift_type_item
                    access_roles = item.get("access_roles") or []
                    if len(access_roles) > 0:
                        access = False
                        for role in access_roles:
                            if role in [i.id for i in ctx.author.roles]:
                                access = True
                                break
                        if access is False:
                            if not msg:
                                return await ctx.send(
                                    embed=discord.Embed(
                                        title="Access Denied",
                                        description="You do not have access to this shift type.",
                                        color=BLANK_COLOR,
                                    )
                                )
                            else:
                                return await msg.edit(
                                    embed=discord.Embed(
                                        title="Access Denied",
                                        description="You do not have access to this shift type.",
                                        color=BLANK_COLOR,
                                    ),
                                    view=None,
                                )

        if self.bot.shift_management_disabled is True:
            return await new_failure_embed(
                ctx,
                "Maintenance",
                "This command is currently disabled as ERM is currently undergoing maintenance updates. This command will be turned off briefly to ensure that no data is lost during the maintenance.",
            )
        try:
            maximum_staff = settings.get("shift_management", {}).get("maximum_staff", 0)
            # print(f"Maximum Staff: {maximum_staff}")
        except AttributeError:
            # print("Attribute Error")
            return

        try:
            on_duty_staff = await self.bot.shift_management.shifts.db.count_documents(
                {"Guild": ctx.guild.id, "EndEpoch": 0}
            )
            # print(f"Staff on Duty: {on_duty_staff}")
        except AttributeError:
            # print("Attribute Error")
            return
        # if author is on duty then bypass the limit
        shift_zero = [
            i
            async for i in self.bot.shift_management.shifts.db.find(
                {"Guild": ctx.guild.id, "EndEpoch": 0, "UserID": ctx.author.id}
            )
        ]

        if len(shift_zero) == 0:
            if (on_duty_staff) >= (maximum_staff or 0) and (maximum_staff or 0) != 0:
                return await ctx.send(
                    embed=discord.Embed(
                        title="Staff Limit Reached",
                        description="The maximum amount of staff members on duty has been reached.",
                        color=BLANK_COLOR,
                    )
                )

        shift = await self.bot.shift_management.get_current_shift(
            ctx.author, ctx.guild.id
        )
        # view = ModificationSelectMenu(ctx.author.id)
        previous_shifts = [
            i
            async for i in self.bot.shift_management.shifts.db.find(
                {"UserID": ctx.author.id, "Guild": ctx.guild.id, "EndEpoch": {"$ne": 0}}
            )
        ]
        embed = discord.Embed(color=BLANK_COLOR)

        embed.add_field(
            name="Current Statistics",
            value=(
                f"> **Total Shift Duration:** {td_format(datetime.timedelta(seconds=sum([get_elapsed_time(item) for item in previous_shifts])))}\n"
                f"> **Total Shifts:** {len(previous_shifts)}\n"
                f"> **Average Shift Duration:** {td_format(datetime.timedelta(seconds=(sum([get_elapsed_time(item) for item in previous_shifts]).__truediv__(len(previous_shifts) or 1))))}\n"
            ),
            inline=False,
        )

        embed.set_author(
            name=ctx.guild.name,
            icon_url=ctx.guild.icon,
        )

        if shift:
            if (shift.get("Breaks", [{}]) or [{}])[-1].get("EndEpoch", 1) == 0:
                status = "break"
            else:
                status = "on"
        else:
            status = "off"

        contained_document = None
        if status == "on":
            contained_document: ShiftItem = await self.bot.shift_management.fetch_shift(
                shift["_id"]
            )
            embed.colour = GREEN_COLOR
            embed.add_field(
                name="Current Shift",
                value=(
                    f"> **Started:** <t:{int(contained_document.start_epoch)}:R>\n"
                    f"> **Breaks:** {len(contained_document.breaks)}\n"
                    f"> **Elapsed Time:** {td_format(datetime.timedelta(seconds=get_elapsed_time(shift)))}"
                ),
                inline=False,
            )
            embed.title = (
                f"{self.bot.emoji_controller.get_emoji('ShiftStarted')} **On-Duty**"
            )
        elif status == "break":
            print("On Break status called")
            contained_document: ShiftItem = await self.bot.shift_management.fetch_shift(
                shift["_id"]
            )

            logging.info(f"All Breaks: {contained_document.breaks}")

            current_break = None
            for break_item in contained_document.breaks:
                logging.info(
                    f"Checking break: {break_item}"
                )  # Debugging log to print each break
                if (
                    break_item.end_epoch == 0
                ):  # Assuming end_epoch is 0 if the break hasn't ended yet
                    current_break = break_item
                    break

            if current_break:
                break_start_time = (
                    f"> **Break Started:** <t:{int(current_break.start_epoch)}:R>\n"
                )
            else:
                break_start_time = "> **Break Started:** No ongoing break\n"
            embed.colour = ORANGE_COLOR
            embed.add_field(
                name="Current Shift",
                value=(
                    f"> **Shift Started:** <t:{int(contained_document.start_epoch)}:R>\n"
                    f"{break_start_time}"
                    f"> **Breaks:** {len(contained_document.breaks)}\n"
                    f"> **Elapsed Time:** {td_format(datetime.timedelta(seconds=get_elapsed_time(shift)))}"
                ),
                inline=False,
            )
            embed.title = (
                f"{self.bot.emoji_controller.get_emoji('ShiftBreak')} **On-Break**"
            )
        else:
            embed.colour = RED_COLOR
            embed.title = (
                f"{self.bot.emoji_controller.get_emoji('ShiftEnded')} **Off-Duty**"
            )

        view = ShiftMenu(
            self.bot,
            status,
            ctx.author.id,
            shift_type_item["name"] if shift_type_item else type,
            starting_document=shift,
            starting_container=contained_document,
        )

        if not msg:
            view.message = await ctx.send(embed=embed, view=view)
        else:
            await msg.edit(embed=embed, view=view)
            view.message = msg

    @duty.command(
        name="active",
        description="Get all members of the server currently on shift.",
        extras={"category": "Shift Management"},
    )
    @require_settings()
    @app_commands.autocomplete(type=all_shift_type_autocomplete)
    @is_staff()
    async def duty_active(self, ctx: commands.Context, *, type: str = None):
        if self.bot.shift_management_disabled is True:
            return await new_failure_embed(
                ctx,
                "Maintenance",
                "This command is currently disabled as ERM is currently undergoing maintenance updates. This command will be turned off briefly to ensure that no data is lost during the maintenance.",
            )

        bot = self.bot
        configItem = await bot.settings.find_by_id(ctx.guild.id)
        if not configItem.get("shift_management", {}).get("enabled", False):
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description="Shift Logging is not enabled on this server.",
                )
            )

        shift_type = None
        if configItem.get("shift_types"):
            shift_types = configItem.get("shift_types")
            if len(shift_types.get("types")) > 1:
                shift_types = shift_types.get("types")

                view = CustomSelectMenu(
                    ctx.author.id,
                    [
                        discord.SelectOption(
                            label=i["name"],
                            value=i["name"],
                            description=i["name"],
                        )
                        for i in shift_types
                    ]
                    + [
                        discord.SelectOption(
                            label="All",
                            value="all",
                            description="Data from all shift types",
                        )
                    ],
                )
                type_value = (type or "").lower()
                if (
                    type_value not in [i["name"].lower() for i in shift_types]
                    and type_value != "all"
                ):
                    msg = await ctx.reply(
                        embed=discord.Embed(
                            title="Incorrect Shift Type",
                            description="The shift type provided is not valid.",
                            color=BLANK_COLOR,
                        ),
                        view=view,
                    )

                    timeout = await view.wait()
                    if timeout:
                        return

                    type_value = view.value.lower()
                else:
                    type_value = type_value.lower()

                if type_value:
                    if type_value == "all":
                        shift_type = None
                    else:
                        shift_type_str = type_value
                        shift_list = [
                            i
                            for i in shift_types
                            if i["name"].lower() == shift_type_str
                        ]
                        if shift_list:
                            shift_type = shift_list[0]
                        else:
                            shift_type = shift_types[0] # default to zero - instead of error

                else:
                    return

        embed = discord.Embed(title="Active Shifts", color=BLANK_COLOR)
        embed.description = f"**Total Shifts**"
        embed.set_author(
            name=f"{ctx.guild.name}",
            icon_url=ctx.guild.icon,
        )

        embeds = []
        embeds.append(embed)

        all_staff = []
        staff_members = []

        if not shift_type:
            async for sh in bot.shift_management.shifts.db.find(
                {"Guild": ctx.guild.id, "EndEpoch": 0}
            ):
                if sh["Guild"] == ctx.guild.id:
                    member = discord.utils.get(ctx.guild.members, id=sh["UserID"])
                    if member:
                        if member not in staff_members:
                            staff_members.append(member)
        else:
            async for shift in bot.shift_management.shifts.db.find(
                {"Guild": ctx.guild.id, "Type": shift_type["name"], "EndEpoch": 0}
            ):
                s = shift
                member = discord.utils.get(ctx.guild.members, id=shift["UserID"])
                if member:
                    if member not in staff_members:
                        staff_members.append(member)

        for member in staff_members:
            sh = await bot.shift_management.get_current_shift(member, ctx.guild.id)

            time_delta = datetime.timedelta(seconds=get_elapsed_time(sh))

            break_seconds = 0
            if "Breaks" in sh.keys():
                for item in sh["Breaks"]:
                    if item["EndEpoch"] == 0:
                        break_seconds += (
                            ctx.message.created_at.replace(tzinfo=pytz.UTC).timestamp()
                            - item["StartEpoch"]
                        )

            all_staff.append(
                {
                    "id": sh["UserID"],
                    "total_seconds": time_delta.total_seconds(),
                    "break_seconds": break_seconds,
                }
            )

        sorted_staff = sorted(all_staff, key=lambda x: x["total_seconds"], reverse=True)
        added_staff = []
        for index, staff in enumerate(sorted_staff):
            # # print(staff)
            member = discord.utils.get(ctx.guild.members, id=staff["id"])
            if not member:
                continue

            if (
                len((embeds[-1].description or "").splitlines()) >= 16
                and member.id not in added_staff
            ):
                embed = discord.Embed(title="Active Shifts", color=BLANK_COLOR)
                embed.description = f"**Total Shifts**"
                embed.set_author(
                    name=f"{ctx.guild.name}",
                    icon_url=ctx.guild.icon,
                )
                added_staff.append(member.id)
                embeds.append(embed)
            if member.id not in added_staff:
                embeds[
                    -1
                ].description += f"\n**{index+1}.** {member.mention} • {td_format(datetime.timedelta(seconds=staff['total_seconds']))}{(' **(Currently on break: {})**'.format(td_format(datetime.timedelta(seconds=staff['break_seconds'])))) if staff['break_seconds'] > 0 else ''}"

        paginator = SelectPagination(
            bot,
            ctx.author.id,
            [
                CustomPage(embeds=[embed], identifier=str(index + 1))
                for index, embed in enumerate(embeds)
            ],
        )

        if len(embeds) == 1:
            if embeds[0].description == "**Total Shifts**":
                try:
                    return await msg.edit(
                        embed=discord.Embed(
                            title="No Active Shifts",
                            description="No active shifts have been found in this server.",
                            color=BLANK_COLOR,
                        ),
                        view=None,
                    )
                except UnboundLocalError:
                    return await ctx.send(
                        embed=discord.Embed(
                            title="No Active Shifts",
                            description="No active shifts have been found in this server.",
                            color=BLANK_COLOR,
                        )
                    )
            try:
                return await msg.edit(embed=embed, view=None)
            except UnboundLocalError:
                return await ctx.reply(embed=embed)
        try:
            await msg.edit(embed=embeds[0], view=paginator.get_current_view())
        except UnboundLocalError:
            await ctx.reply(embed=embeds[0], view=paginator.get_current_view())

    @commands.guild_only()
    @duty.command(
        name="leaderboard",
        description="Get the total time worked for the whole of the staff team.",
        extras={"category": "Shift Management"},
        aliases=["lb"],
    )
    @require_settings()
    @app_commands.autocomplete(type=all_shift_type_autocomplete)
    @is_staff()
    async def shift_leaderboard(self, ctx: commands.Context, *, type: str = None):
        if self.bot.shift_management_disabled is True:
            return await new_failure_embed(
                ctx,
                "Maintenance",
                "This command is currently disabled as ERM is currently undergoing maintenance updates. This command will be turned off briefly to ensure that no data is lost during the maintenance.",
            )

        bot = self.bot
        configItem = await bot.settings.find_by_id(ctx.guild.id)
        if not configItem.get("shift_management", {}).get("enabled", False):
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description="Shift Logging is not enabled on this server.",
                )
            )

        shift_type = None
        msg = None
        if configItem.get("shift_types"):
            shift_types = configItem.get("shift_types")
            if len(shift_types.get("types")) > 1:
                shift_types = shift_types.get("types")

                view = CustomSelectMenu(
                    ctx.author.id,
                    [
                        discord.SelectOption(
                            label=i["name"],
                            value=i["name"],
                            description=i["name"],
                        )
                        for i in shift_types
                    ]
                    + [
                        discord.SelectOption(
                            label="All",
                            value="all",
                            description="Data from all shift types",
                        )
                    ],
                )
                valid_shift_types = [i["name"].lower() for i in shift_types] + ["all"]
                if not (type or "").lower() in valid_shift_types:
                    msg = await ctx.reply(
                        embed=discord.Embed(
                            title="Incorrect Shift Type",
                            description="The shift type provided is not valid.",
                            color=BLANK_COLOR,
                        ),
                        view=view,
                    )

                    timeout = await view.wait()
                    if timeout:
                        return

                    type_value = view.value
                else:
                    type_value = type

                if type_value:
                    if type_value.lower() == "all":
                        shift_type = 0
                    else:
                        shift_type_str = type_value
                        shift_list = [
                            i
                            for i in shift_types
                            if i["name"].lower() == shift_type_str.lower()
                        ]
                        if len(shift_list) > 0:
                            shift_type = shift_list[0]
                        else:
                            shift_type = shift_types[0] # default to zero - instead of error
                else:
                    return

        pipeline = [
            {"$match": {"Guild": ctx.guild.id, "EndEpoch": {"$ne": 0}}},
            {
                "$group": {
                    "_id": "$UserID",
                    "total_seconds": {
                        "$sum": {
                            "$add": [
                                {"$subtract": ["$EndEpoch", "$StartEpoch"]},
                                "$AddedTime",
                                {"$multiply": ["$RemovedTime", -1]},
                            ]
                        }
                    },
                    "moderations": {
                        "$sum": {
                            "$cond": [
                                {"$isArray": "$Moderations"},
                                {"$size": "$Moderations"},
                                0,
                            ]
                        }
                    },
                    "lowest_time": {"$min": "$StartEpoch"},
                    "breaks": {"$push": "$Breaks"},
                }
            },
        ]

        if shift_type != 0 and shift_type is not None:
            pipeline[0]["$match"]["Type"] = shift_type["name"]

        all_staff = {}
        async for doc in bot.shift_management.shifts.db.aggregate(pipeline):
            total_seconds = doc["total_seconds"]

            # Calculate total break time for the shift
            total_break_time = 0
            for break_periods in doc["breaks"]:
                for break_period in break_periods:
                    break_start = break_period.get("StartEpoch", 0)
                    break_end = break_period.get("EndEpoch", 0)
                    if break_start and break_end:
                        total_break_time += break_end - break_start

            # Adjust total_seconds by subtracting the break time
            adjusted_total_seconds = max(total_seconds - total_break_time, 0)

            all_staff[doc["_id"]] = {
                "id": doc["_id"],
                "total_seconds": adjusted_total_seconds,
                "moderations": doc["moderations"],
                "lowest_time": doc["lowest_time"],
            }

        # Fetch additional moderation data in bulk
        mod_ids = [
            staff["id"] for staff in all_staff.values() if staff["moderations"] == 0
        ]
        if mod_ids:
            mod_pipeline = [
                {"$match": {"ModeratorID": {"$in": mod_ids}, "Guild": ctx.guild.id}},
                {"$group": {"_id": "$ModeratorID", "mod_count": {"$sum": 1}}},
            ]
            async for doc in bot.punishments.db.aggregate(mod_pipeline):
                if doc["_id"] in all_staff:
                    all_staff[doc["_id"]]["moderations"] = doc["mod_count"]

        if len(all_staff) == 0:
            return await ctx.send(
                embed=discord.Embed(
                    title="No Shifts",
                    description="No shifts have been found in this server.",
                    color=BLANK_COLOR,
                )
            )

        sorted_staff = sorted(
            all_staff.values(), key=lambda x: x["total_seconds"], reverse=True
        )

        buffer = None
        embeds = []

        embed = discord.Embed(color=BLANK_COLOR, title="Shift Leaderboard")
        embed.set_author(
            name=f"{ctx.guild.name}",
            icon_url=ctx.guild.icon,
        )

        embeds.append(embed)
        data = []

        if not sorted_staff:
            if shift_type != 0 and shift_type is not None:
                if not msg:
                    return await ctx.send(
                        embed=discord.Embed(
                            title="No Shifts",
                            description="No shifts have been found in this server for this Shift Type.",
                            color=BLANK_COLOR,
                        )
                    )
                else:
                    return await msg.edit(
                        embed=discord.Embed(
                            title="No Shifts",
                            description="No shifts have been found in this server for this Shift Type.",
                            color=BLANK_COLOR,
                        )
                    )
            else:
                if not msg:
                    return await ctx.send(
                        embed=discord.Embed(
                            title="No Shifts",
                            description="No shifts have been found in this server.",
                            color=BLANK_COLOR,
                        )
                    )
                else:
                    return await ctx.send(
                        embed=discord.Embed(
                            title="No Shifts",
                            description="No shifts have been found in this server.",
                            color=BLANK_COLOR,
                        )
                    )

        my_data = None
        member_list = await ctx.guild.chunk()
        members = {m.id: m for m in member_list}  # Cache guild members
        total_seconds = 0

        for index, i in enumerate(sorted_staff):
            member = members.get(i["id"])
            if member:
                if member.id == ctx.author.id:
                    i["index"] = index
                    my_data = i
                total_seconds += i["total_seconds"]
                time_str = td_format(datetime.timedelta(seconds=i["total_seconds"]))

                if buffer is None:
                    buffer = f"{member.name} • {time_str}"
                else:
                    buffer += f"\n{member.name} • {time_str}"

                data.append(
                    [
                        index + 1,
                        member.name,
                        member.top_role.name,
                        time_str,
                        i["moderations"],
                    ]
                )

                line = f"**{index + 1}.** {member.mention} • {time_str}\n"
                if (
                    len((embeds[-1].description or "")) + len(line) > 4096
                    or len((embeds[-1].description or "").splitlines()) >= 16
                ):
                    new_embed = discord.Embed(
                        color=BLANK_COLOR, title="Shift Leaderboard"
                    )
                    new_embed.set_author(
                        name=f"{ctx.guild.name}", icon_url=ctx.guild.icon
                    )
                    new_embed.description = f"**Total Shifts**\n{line}"
                    embeds.append(new_embed)
                else:
                    if embeds[-1].description is None:
                        embeds[-1].description = f"**Total Shifts**\n{line}"
                    else:
                        embeds[-1].description += line

        staff_roles = []

        if configItem["staff_management"].get("role"):
            if isinstance(configItem["staff_management"]["role"], int):
                staff_roles.append(configItem["staff_management"]["role"])
            elif isinstance(configItem["staff_management"]["role"], list):
                for role in configItem["staff_management"]["role"]:
                    staff_roles.append(role)

        if configItem["staff_management"].get("management_role"):
            if isinstance(configItem["staff_management"]["management_role"], int):
                staff_roles.append(configItem["staff_management"]["management_role"])
            elif isinstance(configItem["staff_management"]["management_role"], list):
                for role in configItem["staff_management"]["management_role"]:
                    staff_roles.append(role)
        staff_roles = [ctx.guild.get_role(role) for role in staff_roles]
        added_staff = []

        for role in staff_roles.copy():
            if role is None:
                staff_roles.remove(role)

        for role in staff_roles:
            if role.members:
                for member in role.members:
                    if member.id not in [item["id"] for item in sorted_staff]:
                        if member not in added_staff:
                            index = index + 1

                            if buffer is None:
                                buffer = "%s - %s" % (
                                    f"{member.name}",
                                    "0 seconds",
                                )
                                data.append(
                                    [
                                        index,
                                        f"{member.name}",
                                        member.top_role.name,
                                        "0 seconds",
                                        0,
                                    ]
                                )
                                added_staff.append(member)
                            else:
                                buffer = buffer + "\n%s - %s" % (
                                    f"{member.name}",
                                    "0 seconds",
                                )
                                data.append(
                                    [
                                        index,
                                        f"{member.name}",
                                        member.top_role.name,
                                        "0 seconds",
                                        0,
                                    ]
                                )
                                added_staff.append(member)

                            if len((embeds[-1].description or "").splitlines()) < 16:
                                if embeds[-1].description is None:
                                    embeds[-1].description = (
                                        f"**Total Shifts**\n**{index + 1}.** {member.mention} • {td_format(datetime.timedelta(seconds=0))}\n"
                                    )
                                else:
                                    embeds[
                                        -1
                                    ].description += f"**{index + 1}.** {member.mention} • {td_format(datetime.timedelta(seconds=0))}\n"

                            else:
                                new_embed = discord.Embed(
                                    color=BLANK_COLOR, title="Shift Leaderboard"
                                )

                                new_embed.set_author(
                                    name=f"{ctx.guild.name}",
                                    icon_url=ctx.guild.icon,
                                )
                                new_embed.description = ""
                                new_embed.description += f"**Total Shifts**\n**{index + 1}.** {member.mention} - {td_format(datetime.timedelta(seconds=0))}\n"
                                embeds.append(new_embed)
        perm_staff = list(
            filter(
                lambda m: (
                    m.guild_permissions.manage_messages
                    or m.guild_permissions.manage_guild
                )
                and not m.bot,
                member_list,
            )
        )
        for member in perm_staff:
            if member.id not in [item["id"] for item in sorted_staff]:
                if member not in added_staff:
                    index = index + 1

                    if buffer is None:
                        buffer = "%s - %s" % (
                            f"{member.name}",
                            "0 seconds",
                        )
                        data.append(
                            [
                                index + 1,
                                f"{member.name}",
                                member.top_role.name,
                                "0 seconds",
                                0,
                            ]
                        )
                        added_staff.append(member)

                    else:
                        buffer = buffer + "\n%s - %s" % (
                            f"{member.name}",
                            "0 seconds",
                        )
                        data.append(
                            [
                                index + 1,
                                f"{member.name}",
                                member.top_role.name,
                                "0 seconds",
                                0,
                            ]
                        )
                        added_staff.append(member)

                    if len((embeds[-1].description or "").splitlines()) < 16:
                        if embeds[-1].description is None:
                            embeds[-1].description = (
                                f"**Total Shifts**\n**{index + 1}.** {member.mention} • {td_format(datetime.timedelta(seconds=0))}\n"
                            )
                        else:
                            embeds[
                                -1
                            ].description += f"**{index + 1}.** {member.mention} • {td_format(datetime.timedelta(seconds=0))}\n"

                    else:
                        new_embed = discord.Embed(
                            color=BLANK_COLOR, title="Shift Leaderboard"
                        )

                        new_embed.set_author(
                            name=f"{ctx.guild.name}",
                            icon_url=ctx.guild.icon,
                        )
                        new_embed.description = ""
                        new_embed.description += f"**Total Shifts**\n**{index + 1}.** {member.mention} • {td_format(datetime.timedelta(seconds=0))}\n"
                        embeds.append(new_embed)

        combined = []
        for list_item in data:
            for item in list_item:
                combined.append(item)
        if buffer == "":
            buffer += "No data to display."

        bbytes = buffer.encode("utf-8", "ignore")

        if len(embeds) == 1:
            new_embeds = []
            for i in embeds:
                new_embeds.append(i)
            if await management_predicate(ctx):
                view = RequestGoogleSpreadsheet(
                    self.bot,
                    ctx.author.id,
                    credentials_dict,
                    scope,
                    combined,
                    config("DUTY_LEADERBOARD_ID"),
                    total_seconds,
                )
            else:
                view = None
            await ctx.reply(
                embeds=new_embeds,
                file=discord.File(fp=BytesIO(bbytes), filename="shift_leaderboard.txt"),
                view=view,
            )
        else:
            if await management_predicate(ctx):
                view = RequestGoogleSpreadsheet(
                    self.bot,
                    ctx.author.id,
                    credentials_dict,
                    scope,
                    combined,
                    config("DUTY_LEADERBOARD_ID"),
                    total_seconds,
                )
            else:
                view = None

            async def response_func(
                interaction: discord.Interaction, button: discord.Button
            ):
                file = discord.File(
                    fp=BytesIO(bbytes), filename="shift_leaderboard.txt"
                )
                await interaction.response.send_message(file=file, ephemeral=True)

            if view:
                view.add_item(
                    CustomExecutionButton(
                        ctx.author.id,
                        "Download Shift Leaderboard",
                        discord.ButtonStyle.gray,
                        emoji=None,
                        func=response_func,
                    )
                )

            pages = [
                CustomPage(embeds=[embed], view=view, identifier=str(index + 1))
                for index, embed in enumerate(embeds)
            ]
            menu = SelectPagination(self.bot, ctx.author.id, pages)

            if len(menu.pages) == 1:
                try:
                    return await msg.edit(embed=embed, view=view)
                except (UnboundLocalError, AttributeError, ValueError):
                    return await ctx.reply(embed=embed, view=view)

            view_page = menu.get_current_view()
            try:
                menu.message = await msg.edit(embed=embeds[0], view=view_page)
            except (UnboundLocalError, AttributeError, ValueError):
                menu.message = await ctx.reply(embed=embeds[0], view=view_page)

    @commands.guild_only()
    @duty.command(
        name="history",
        description="Show all past shifts of user by shift type",
        extras={"category": "Shift Management"},
        aliases=["h"],
    )
    @require_settings()
    @app_commands.autocomplete(type=shift_type_autocomplete)
    @is_management()
    async def duty_shifts(
        self, ctx: commands.Context, user: discord.User, type: str = "Default"
    ):
        if self.bot.shift_management_disabled is True:
            return await new_failure_embed(
                ctx,
                "Maintenance",
                "This command is currently disabled as ERM is currently undergoing maintenance updates. This command will be turned off briefly to ensure that no data is lost during the maintenance.",
            )

        bot = self.bot
        configItem = await bot.settings.find_by_id(ctx.guild.id)
        if not configItem.get("shift_management", {}).get("enabled", False):
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description="Shift Logging is not enabled on this server.",
                )
            )

        shift_types = configItem.get("shift_types", {}).get("types", [])
        msg = None
        shift_type_item = None
        if shift_types and len(shift_types) >= 1:
            if type.lower() not in [ t["name"].lower() for t in shift_types ]:
                msg = await ctx.send(
                    embed=discord.Embed(
                        title="Incorrect Shift Type",
                        description="The shift type provided is not valid.",
                        color=BLANK_COLOR,
                    ),
                    view=(
                        view := CustomSelectMenu(
                            ctx.author.id,
                            [
                                discord.SelectOption(
                                    label=i["name"],
                                    value=i["name"],
                                    description=i["name"],
                                )
                                for i in shift_types
                            ],
                        )
                    ),
                )
                timeout = await view.wait()
                if timeout:
                    return

                if view.value:
                    type = view.value

            for item in shift_types:
                if item["name"].lower() == type.lower():
                    shift_type_item = item

        if not shift_type_item:
            if type.lower() == "default":
                shift_type_item = {"name": "Default"}
            else:
                return await ctx.send(
                    embed=discord.Embed(
                        title="Incorrect Shift Type",
                        description="The shift type provided is not valid.",
                        color=BLANK_COLOR,
                    )
                )

        shift_cursor = self.bot.shift_management.shifts.db.find(
            {"UserID": user.id, "Guild": ctx.guild.id, "Type": shift_type_item["name"]}
        )
        shifts = await shift_cursor.to_list(length=None)
        if not shifts:
            return await ctx.send(
                embed=discord.Embed(
                    title="No Shifts",
                    description="No shifts have been found for this user.",
                    color=BLANK_COLOR,
                )
            )

        embeds = []
        for shift in shifts:
            embed = discord.Embed(title=f"{user.name}'s Shifts", color=BLANK_COLOR)
            embed.add_field(
                name="Shift Information",
                value=(
                    f"> **Started:** <t:{int(shift['StartEpoch'])}:R>\n"
                    f"> **Ended:** <t:{int(shift['EndEpoch'])}:R>\n"
                    f"> **Total Time:** {td_format(datetime.timedelta(seconds=get_elapsed_time(shift)))}\n"
                    f"> **Moderations:** {len(shift.get('Moderations', []))}\n"
                    f"> **Breaks:** {len(shift.get('Breaks', []))}"
                ),
                inline=False,
            ).set_author(
                name=f"{ctx.guild.name}",
                icon_url=ctx.guild.icon,
            ).set_footer(
                text=f"Shift Type: {shift_type_item['name']}"
            ).set_thumbnail(
                url=user.display_avatar.url
            )
            embeds.append(embed)

        paginator = SelectPagination(
            self.bot,
            ctx.author.id,
            [
                CustomPage(embeds=[embed], identifier=str(index + 1))
                for index, embed in enumerate(embeds)
            ],
        )
        await ctx.reply(embed=embeds[0], view=paginator.get_current_view())


async def setup(bot):
    await bot.add_cog(ShiftLogging(bot))
