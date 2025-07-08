import datetime

import discord
import pytz
from dateutil import parser
from discord import app_commands
from discord.ext import commands
from reactionmenu import ViewButton, ViewMenu

from erm import is_management, is_admin, system_code_gen, is_staff
from menus import (
    ActivityNoticeModification,
    CustomModalView,
    CustomSelectMenu,
    LOAMenu,
    YesNoColourMenu,
    ActivityNoticeAdministration,
)
from utils.constants import BLANK_COLOR, GREEN_COLOR
from utils.paginators import CustomPage, SelectPagination
from utils.timestamp import td_format
from utils.utils import (
    invis_embed,
    removesuffix,
    require_settings,
    time_converter,
    get_elapsed_time,
    log_command_usage,
)


class ActivityCoreCommands:
    """
    Basic class for core commands of the Activity Notices module.
    This is used for utilising a similar command callback for a different command group, such as "ra request" and "loa request"
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def upload_schema(self, schema: dict):
        await self.bot.loas.insert(schema)

    async def upload_to_views(self, code, message_id, *args):
        await self.bot.views.insert(
            {
                "_id": code,
                "args": [*args],
                "view_type": "LOAMenu",
                "message_id": message_id,
            }
        )

    async def send_activity_request(
        self,
        guild: discord.Guild,
        staff_channel: discord.TextChannel,
        author: discord.Member,
        schema,
    ) -> dict:
        request_type = schema["type"]
        settings = await self.bot.settings.find_by_id(guild.id)
        management_roles = settings.get("staff_management").get("management_role")
        loa_roles = settings.get("staff_management").get(f"{request_type.lower()}_role")

        embed = discord.Embed(title=f"{request_type} Request", color=BLANK_COLOR)
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else "")

        past_author_notices = [
            item
            async for item in self.bot.loas.db.find(
                {
                    "guild_id": guild.id,
                    "user_id": author.id,
                    "accepted": True,
                    "denied": False,
                    "expired": True,
                    "type": request_type.upper(),
                }
            )
        ]

        shifts = []
        storage_item = [
            i
            async for i in self.bot.shift_management.shifts.db.find(
                {"UserID": author.id, "Guild": guild.id}
            )
        ]

        for s in storage_item:
            if s["EndEpoch"] != 0:
                shifts.append(s)

        total_seconds = sum([get_elapsed_time(i) for i in shifts])

        embed.add_field(
            name="Staff Information",
            value=(
                f"> **Staff Member:** {author.mention}\n"
                f"> **Top Role:** {author.top_role.name}\n"
                f"> **Past {request_type}s:** {len(past_author_notices)}\n"
                f"> **Shift Time:** {td_format(datetime.timedelta(seconds=total_seconds))}"
            ),
            inline=False,
        )

        embed.add_field(
            name="Request Information",
            value=(
                f"> **Type:** {request_type}\n"
                f"> **Reason:** {schema['reason']}\n"
                f"> **Starts At:** <t:{schema.get('started_at', int(schema['_id'].split('_')[2]))}>\n"
                f"> **Ends At:** <t:{schema['expiry']}>"
            ),
        )

        view = LOAMenu(
            self.bot,
            management_roles,
            loa_roles,
            schema,
            author.id,
            (code := system_code_gen()),
        )

        msg = await staff_channel.send(embed=embed, view=view)
        schema["message_id"] = msg.id
        await self.upload_to_views(
            code, msg.id, "SELF", management_roles, loa_roles, schema, author.id, code
        )
        return schema

    async def core_command_admin(
        self, ctx: commands.Context, request_type_object: str, victim: discord.Member
    ):
        settings = await self.bot.settings.find_by_id(ctx.guild.id)
        if not settings:
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Setup",
                    description="Your server is not setup.",
                    color=BLANK_COLOR,
                )
            )

        if (
            not settings.get("staff_management")
            or not settings.get("staff_management", {}).get(
                f"{request_type_object.lower()}_role", None
            )
            or not settings.get("staff_management", {}).get("channel")
        ):
            await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description=f"{request_type_object.upper()} Requests are not enabled on this server.",
                    color=BLANK_COLOR,
                )
            )
            return

        try:
            staff_channel = await ctx.guild.fetch_channel(
                settings["staff_management"]["channel"]
            )
        except Exception as _:
            return await ctx.send(
                embed=discord.Embed(
                    title="Channel Not Found",
                    description=f"Activity Notice channel was not found.",
                    color=BLANK_COLOR,
                )
            )

        past_victim_notices = [
            item
            async for item in self.bot.loas.db.find(
                {
                    "guild_id": ctx.guild.id,
                    "user_id": victim.id,
                    "accepted": True,
                    "expired": True,
                    "denied": False,
                    "type": request_type_object.upper(),
                }
            )
        ]

        current_notice = await self.bot.loas.db.find_one(
            {
                "guild_id": ctx.guild.id,
                "user_id": victim.id,
                "accepted": True,
                "denied": False,
                "voided": False,
                "expired": False,
                "type": request_type_object.upper(),
            }
        )

        view = ActivityNoticeAdministration(
            self.bot,
            ctx.author.id,
            victim=victim.id,
            guild_id=ctx.guild.id,
            request_type=request_type_object,
            current_notice=current_notice,
        )
        embed = discord.Embed(title="Activity Notices", color=BLANK_COLOR)
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
        embed.add_field(
            name="Staff Information",
            value=(
                f"> **Staff Member:** {victim.mention}\n"
                f"> **Top Role:** {victim.top_role.name}\n"
                f"> **Past {request_type_object.upper()}s:** {len(past_victim_notices)}\n"
            ),
            inline=False,
        )

        if current_notice is not None:
            embed.add_field(
                name=f"Current {request_type_object.upper()} Information",
                value=(
                    f"> **Type:** {request_type_object.upper()}\n"
                    f"> **Reason:** {current_notice['reason']}\n"
                    f"> **Starts At:** <t:{current_notice.get('started_at', int(current_notice['_id'].split('_')[2]))}>\n"
                    f"> **Ends At:** <t:{current_notice['expiry']}>"
                ),
                inline=False,
            )

        msg = await ctx.send(embed=embed, view=view)
        await view.wait()

        if view.value == "create":

            async def respond(embed: discord.Embed):
                if view.stored_interaction is not None:
                    await view.stored_interaction.followup.send(
                        embed=embed, ephemeral=True
                    )
                else:
                    await msg.edit(embed=embed, view=None)

            reason = view.modal.reason.value
            duration = view.modal.duration.value
            if not all([reason is not None, duration is not None]):
                return await respond(
                    embed=discord.Embed(
                        title="Cancelled",
                        description="Not enough values were entered.",
                        color=BLANK_COLOR,
                    )
                )

            try:
                duration_seconds = time_converter(duration)
            except ValueError:
                return await respond(
                    embed=discord.Embed(
                        title="Invalid Time",
                        description="You did not provide a valid time format.",
                        color=BLANK_COLOR,
                    )
                )

            if current_notice:
                return await respond(
                    embed=discord.Embed(
                        title="Active Notice",
                        description=f"This individual already has an active {request_type_object.upper()} notice.",
                        color=BLANK_COLOR,
                    )
                )
            else:
                await self.core_command_request(
                    ctx,
                    request_type_object,
                    duration,
                    reason,
                    return_bypass=True,
                    override_victim=victim,
                )
                return await respond(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('success')} Request Sent",
                        description=f"This {request_type_object.upper()} Request has been sent successfully.",
                        color=GREEN_COLOR,
                    )
                )
        elif view.value == "list":

            async def respond(
                embed: discord.Embed, custom_view: discord.ui.View | None
            ):
                if view.stored_interaction is not None:
                    if custom_view:
                        await view.stored_interaction.followup.send(
                            embed=embed,
                            view=custom_view,
                            # cant do ephemeral followup here.
                            # since you cant edit an ephemeral followup of an interaction, since its both a followup (so edit_original_response doesnt work)
                            # and ephemeral (message.edit doesnt work)
                        )
                    else:
                        await view.stored_interaction.followup.send(embed=embed)
                else:
                    await msg.edit(embed=embed, view=custom_view)

            def setup_embed() -> discord.Embed:
                embed = discord.Embed(title="Activity Notices", color=BLANK_COLOR)
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
                return embed

            embeds = []
            for item in past_victim_notices:
                if len(embeds) == 0:
                    embeds.append(setup_embed())

                if len(embeds[-1].fields) > 4:
                    embeds.append(setup_embed())

                embeds[-1].add_field(
                    name=f"{item['type']}",
                    value=(
                        f"> **Staff:** <@{item['user_id']}>\n"
                        f"> **Reason:** {item['reason']}\n"
                        f"> **Started At:** <t:{int(item.get('started_at', int(item['_id'].split('_')[2])))}>\n"
                        f"> **Ended At:** <t:{int(item['expiry'])}>"
                    ),
                    inline=False,
                )
            pages = [
                CustomPage(embeds=[embed], identifier=str(index + 1))
                for index, embed in enumerate(embeds)
            ]
            if len(pages) == 0:
                return await respond(
                    embed=discord.Embed(
                        title="No Activity Notices",
                        description="There were no active Activity Notices found.",
                        color=BLANK_COLOR,
                    ),
                    custom_view=None,
                )

            if len(pages) != 1:
                paginator = SelectPagination(self.bot, ctx.author.id, pages=pages)
                await respond(embed=embeds[0], custom_view=paginator)
            else:
                await respond(embed=embeds[0], custom_view=None)
        elif view.value == "delete":

            async def respond(embed: discord.Embed):
                if view.stored_interaction is not None:
                    await view.stored_interaction.followup.send(
                        embed=embed, ephemeral=True
                    )
                else:
                    await msg.edit(embed=embed, view=None)

            if not current_notice:
                return await respond(
                    embed=discord.Embed(
                        title="No Active Notice",
                        description="This staff member has no active notice.",
                    )
                )

            await self.bot.loas.delete_by_id(current_notice["_id"])
            return await respond(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Notice Deleted",
                    description=f"This {request_type_object.upper()} Request has been deleted.",
                    color=GREEN_COLOR,
                )
            )

        elif view.value == "end":

            async def respond(embed: discord.Embed):
                if view.stored_interaction is not None:
                    await view.stored_interaction.followup.send(
                        embed=embed, ephemeral=True
                    )
                else:
                    await msg.edit(embed=embed, view=None)

            if not current_notice:
                return await respond(
                    embed=discord.Embed(
                        title="No Active Notice",
                        description="This staff member has no active notice.",
                    )
                )

            current_time = int(datetime.datetime.now().timestamp())
            await self.bot.loas.db.update_one(
                {"_id": current_notice["_id"]},
                {"$set": {"expiry": current_time, "expired": True}},
            )

            return await respond(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Notice Ended Early",
                    description=f"{victim.mention}'s {request_type_object.upper()} has been ended early.",
                    color=GREEN_COLOR,
                )
            )

        elif view.value == "extend":

            async def respond(embed: discord.Embed):
                if view.stored_interaction is not None:
                    await view.stored_interaction.followup.send(
                        embed=embed,
                    )
                else:
                    await msg.edit(embed=embed, view=None)

            if not current_notice:
                return await respond(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('error')} No Active Notice",
                        description="This staff member has no active notice.",
                    )
                )

            duration = view.modal.duration.value
            if duration is None:
                return await respond(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('WarningIcon')} Cancelled",
                        description="You did not provide a duration.",
                        color=BLANK_COLOR,
                    )
                )

            try:
                duration_seconds = time_converter(duration)
            except ValueError:
                return await respond(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('WarningIcon')} Invalid Time",
                        description="You did not provide a valid time format.",
                        color=BLANK_COLOR,
                    )
                )

            new_expiry = current_notice["expiry"] + duration_seconds
            await self.bot.loas.db.update_one(
                {"_id": current_notice["_id"]}, {"$set": {"expiry": new_expiry}}
            )

            return await respond(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Notice Extended",
                    description=f"{victim.mention}'s {request_type_object.upper()} has been extended by {duration}.",
                    color=GREEN_COLOR,
                )
            )

    async def core_command_request(
        self,
        ctx: commands.Context,
        request_type_object: str,
        duration: str,
        reason: str,
        return_bypass=None,
        override_victim=None,
        starting: str = None,
    ):
        settings = await self.bot.settings.find_by_id(ctx.guild.id)
        if (
            not settings.get("staff_management")
            or not settings.get("staff_management", {}).get(
                f"{request_type_object.lower()}_role", None
            )
            or not settings.get("staff_management", {}).get("enabled")
        ):
            await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description=f"{request_type_object.upper()} Requests are not enabled on this server.",
                    color=BLANK_COLOR,
                )
            )
            return

        if override_victim is not None:
            member = override_victim
        else:
            member = ctx.author

        try:
            staff_channel = await ctx.guild.fetch_channel(
                settings["staff_management"]["channel"]
            )
        except discord.NotFound:
            return await ctx.send(
                embed=discord.Embed(
                    title="Channel Not Found",
                    description=f"Activity Notice channel was not found.",
                    color=BLANK_COLOR,
                )
            )

        try:
            duration_seconds = time_converter(duration)
        except ValueError:
            return await ctx.send(
                embed=discord.Embed(
                    title="Incorrect Time",
                    description=f"The time you provided was incorrect.",
                    color=BLANK_COLOR,
                )
            )

        active_author_notices = [
            item
            async for item in self.bot.loas.db.find(
                {
                    "guild_id": ctx.guild.id,
                    "user_id": member.id,
                    "accepted": True,
                    "denied": False,
                    "expired": False,
                    "voided": False,
                    "type": request_type_object.upper(),
                }
            )
        ]

        if len(active_author_notices) > 0:
            return await ctx.send(
                embed=discord.Embed(
                    title="Already Active",
                    description=f"You already have a {request_type_object.upper()} request.",
                    color=BLANK_COLOR,
                )
            )

        current_timestamp = int(datetime.datetime.now().timestamp())

        try:
            if starting:
                start_after_seconds = time_converter(starting)
                current_timestamp += start_after_seconds
        except ValueError:
            return await ctx.send(
                embed=discord.Embed(
                    title="Incorrect Time",
                    description=f"The time you provided was incorrect.",
                    color=BLANK_COLOR,
                )
            )


        expiry_timestamp = current_timestamp + duration_seconds

        # print(current_timestamp)
        # print(expiry_timestamp)

        schema = {
            "_id": f"{member.id}_{ctx.guild.id}_{current_timestamp}_{expiry_timestamp}",
            "user_id": member.id,
            "guild_id": ctx.guild.id,
            "message_id": None,
            "type": request_type_object.upper(),
            "started_at": current_timestamp,
            "expiry": expiry_timestamp,
            "expired": False,
            "accepted": False,
            "denied": False,
            "voided": False,
            "reason": reason,
            "user_rolled": False  #===========UPDATED SCHEMA=============
        }
        #We're updating the schema of LOA by adding 'user_rolled' parameter to keep the track of users who're rolled.
        #If LOA is requested in advance then on approving LOA it won't add role then can be added later by bot when using a seperate discord.task which will be handling advance LOA's
        #Logic will be updated in the `menus.py` to handle the future LOAs.

        new_schema = await self.send_activity_request(
            ctx.guild, staff_channel, member, schema
        )

        await self.upload_schema(new_schema)
        if return_bypass is None:
            await ctx.send(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Request Sent",
                    description=f"Your {request_type_object.upper()} has been sent successfully.",
                    color=GREEN_COLOR,
                )
            )

    async def core_command_active(
        self, ctx: commands.Context, request_type_object: str
    ):
        settings = await self.bot.settings.find_by_id(ctx.guild.id)
        if not settings.get("staff_management") or not settings.get(
            "staff_management", {}
        ).get(f"{request_type_object.lower()}_role", None):
            await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description=f"{request_type_object.upper()} Requests are not enabled on this server.",
                    color=BLANK_COLOR,
                )
            )
            return

        request_upper = request_type_object.upper()
        request_lower = request_type_object.lower()

        active_requests = []
        async for item in self.bot.loas.db.find(
            {
                "guild_id": ctx.guild.id,
                "accepted": True,
                "denied": False,
                "expired": False,
                "type": request_upper,
            }
        ):
            item["started_at"] = int(item["_id"].split("_")[2])
            active_requests.append(item)

        def setup_embed() -> discord.Embed:
            embed = discord.Embed(title="Activity Notices", color=BLANK_COLOR)
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
            return embed

        embeds = []
        for item in active_requests:
            if len(embeds) == 0:
                embeds.append(setup_embed())

            if len(embeds[-1].fields) > 4:
                embeds.append(setup_embed())

            embeds[-1].add_field(
                name=f"{item['type']}",
                value=(
                    f"> **Staff:** <@{item['user_id']}>\n"
                    f"> **Reason:** {item['reason']}\n"
                    f"> **Started At:** <t:{int(item.get('started_at', int(item['_id'].split('_')[2])))}>\n"
                    f"> **Ended At:** <t:{int(item['expiry'])}>"
                ),
                inline=False,
            )
        pages = [
            CustomPage(embeds=[embed], identifier=str(index + 1))
            for index, embed in enumerate(embeds)
        ]
        if len(pages) == 0:
            return await ctx.send(
                embed=discord.Embed(
                    title="No Activity Notices",
                    description="There were no active Activity Notices found.",
                    color=BLANK_COLOR,
                )
            )

        if len(pages) != 1:
            paginator = SelectPagination(self.bot, ctx.author.id, pages=pages)
            await ctx.send(embed=embeds[0], view=paginator)
        else:
            await ctx.send(embed=embeds[0])

    async def core_command_view(self, ctx: commands.Context, request_type_object: str):
        settings = await self.bot.settings.find_by_id(ctx.guild.id)
        if not settings.get("staff_management") or not settings.get(
            "staff_management", {}
        ).get(f"{request_type_object.lower()}_role", None):
            await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description=f"{request_type_object.upper()} Requests are not enabled on this server.",
                    color=BLANK_COLOR,
                )
            )
            return

        request_upper = request_type_object.upper()

        all_requests = []
        async for item in self.bot.loas.db.find(
            {"guild_id": ctx.guild.id, "user_id": ctx.author.id, "type": request_upper}
        ):
            all_requests.append(item)

        def setup_embed() -> discord.Embed:
            embed = discord.Embed(title="Activity Notices", color=BLANK_COLOR)
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
            return embed

        embeds = []
        for item in all_requests:
            if len(embeds) == 0:
                embeds.append(setup_embed())
            if len(embeds[-1].fields) > 4:
                embeds.append(setup_embed())
            embeds[-1].add_field(
                name=f"{item['type']}",
                value=(
                    f"> **Reason:** {item['reason']}\n"
                    f"> **Started At:** <t:{int(item.get('started_at', int(item['_id'].split('_')[2])))}>\n"
                    f"> **Ended At:** <t:{int(item['expiry'])}>"
                ),
                inline=False,
            )
        pages = [
            CustomPage(embeds=[embed], identifier=str(index + 1))
            for index, embed in enumerate(embeds)
        ]
        if len(pages) == 0:
            return await ctx.send(
                embed=discord.Embed(
                    title="No Activity Notices",
                    description="There were no active Activity Notices found.",
                    color=BLANK_COLOR,
                )
            )

        if len(pages) != 1:
            paginator = SelectPagination(self.bot, ctx.author.id, pages=pages)
            await ctx.channel.send(embed=embeds[0], view=paginator)

        else:
            await ctx.channel.send(
                embed=embeds[0],
            )


class StaffManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.core_commands = ActivityCoreCommands(bot)

    @commands.hybrid_group(
        name="ra",
        description="File a Reduced Activity request",
        extras={"category": "Staff Management"},
        with_app_command=True,
    )
    async def ra(self, ctx, time, *, reason):
        pass

    @commands.guild_only()
    @ra.command(
        name="active",
        description="View all active RAs",
        extras={"category": "Staff Management"},
    )
    @is_admin()
    @require_settings()
    async def ra_active(self, ctx):
        await self.core_commands.core_command_active(ctx, "ra")

    @commands.guild_only()
    @ra.command(
        name="request",
        description="File a Reduced Activity request",
        extras={"category": "Staff Management", "ephemeral": True},
        with_app_command=True,
    )
    @is_staff()
    @app_commands.describe(time="How long are you going to be on RA for? (s/m/h/d)")
    @app_commands.describe(reason="What is your reason for going on RA?")
    @app_commands.describe(starting="When would you like to start your RA? (s/m/h/d)")
    async def ra_request(self, ctx, time, *, reason, starting: str = None):
        await self.core_commands.core_command_request(
            ctx, "ra", time, reason, starting=starting
        )

    @commands.guild_only()
    @ra.command(
        name="admin",
        description="Administrate a Reduced Activity request",
        extras={"category": "Staff Management"},
        with_app_command=True,
    )
    @is_admin()
    @app_commands.describe(
        member="Who's RA would you like to administrate? Specify a Discord user."
    )
    async def ra_admin(self, ctx, member: discord.Member):
        await log_command_usage(self.bot, ctx.guild, ctx.author, f"RA Admin: {member}")
        await self.core_commands.core_command_admin(ctx, "ra", member)

    @commands.guild_only()
    @ra.command(
        name="view",
        description="View your active RA",
        extras={"category": "Staff Management"},
        with_app_command=True,
    )
    @is_staff()
    async def ra_view(self, ctx):
        await self.core_commands.core_command_view(ctx, "ra")

    @commands.hybrid_group(
        name="loa",
        description="File a Leave of Absence request",
        extras={"category": "Staff Management"},
        with_app_command=True,
    )
    @app_commands.describe(time="How long are you going to be on LoA for? (s/m/h/d)")
    @app_commands.describe(reason="What is your reason for going on LoA?")
    async def loa(self, ctx, time, *, reason):
        await ctx.invoke(self.bot.get_command("loa request"), time=time, reason=reason)

    @commands.guild_only()
    @loa.command(
        name="view",
        description="View your active LOA",
        extras={"category": "Staff Management"},
        with_app_command=True,
    )
    @is_staff()
    async def loa_view(self, ctx):
        await self.core_commands.core_command_view(ctx, "loa")

    @loa.command(
        name="active",
        description="View all active LOAs",
        extras={"category": "Staff Management"},
    )
    @is_admin()
    async def loa_active(self, ctx):
        await self.core_commands.core_command_active(ctx, "loa")

    @commands.guild_only()
    @loa.command(
        name="request",
        description="File a Leave of Absence request",
        extras={"category": "Staff Management", "ephemeral": True},
        with_app_command=True,
    )
    @is_staff()
    @app_commands.describe(time="How long are you going to be on LoA for? (s/m/h/d)")
    @app_commands.describe(reason="What is your reason for going on LoA?")
    @app_commands.describe(starting="When would you like to start your LOA? (s/m/h/d)")
    async def loa_request(self, ctx, time, *, reason, starting: str = None):
        await self.core_commands.core_command_request(
            ctx, "loa", time, reason, starting=starting
        )

    @commands.guild_only()
    @loa.command(
        name="admin",
        description="Administrate a Leave of Absence request",
        extras={"category": "Staff Management"},
        with_app_command=True,
    )
    @is_admin()
    @app_commands.describe(
        member="Who's LOA would you like to administrate? Specify a Discord user."
    )
    async def loa_admin(self, ctx, member: discord.Member):
        await log_command_usage(self.bot, ctx.guild, ctx.author, f"LOA Admin: {member}")

        return await self.core_commands.core_command_admin(ctx, "loa", member)


async def setup(bot):
    await bot.add_cog(StaffManagement(bot))
