import datetime
import json

import aiohttp
import discord
import pytz
import reactionmenu
import roblox
from decouple import config
from discord import app_commands
from discord.ext import commands
from reactionmenu import ViewButton, ViewMenu
from reactionmenu.abc import _PageController
import pytz
from datamodels.Settings import Settings
from datamodels.Warnings import WarningItem
from erm import (
    admin_predicate,
    generator,
    is_management,
    is_staff,
    management_predicate,
)
from menus import (
    ChannelSelect,
    CustomisePunishmentType,
    CustomModalView,
    CustomSelectMenu,
    EditWarning,
    RemoveWarning,
    RequestDataView,
    CustomExecutionButton,
    UserSelect,
    YesNoMenu,
    ManagementOptions,
    ManageTypesView,
    PunishmentTypeCreator,
    PunishmentModifier,
    CustomModal,
)
from utils.AI import AI
from utils.autocompletes import punishment_autocomplete, user_autocomplete
from utils.constants import BLANK_COLOR, GREEN_COLOR
from utils.paginators import SelectPagination, CustomPage
from utils.utils import (
    failure_embed,
    removesuffix,
    get_roblox_by_username,
    failure_embed,
    require_settings,
    new_failure_embed,
    time_converter,
)
from utils.timestamp import td_format


class Punishments(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.guild_only()
    @commands.hybrid_command(
        name="punish",
        aliases=["p"],
        description="Punish a user",
        extras={"category": "Punishments"},
        usage="punish <user> <type> <reason>",
    )
    @is_staff()
    @require_settings()
    @app_commands.autocomplete(type=punishment_autocomplete)
    @app_commands.autocomplete(user=user_autocomplete)
    @app_commands.describe(type="The type of punishment to give.")
    @app_commands.describe(
        user="What's their username? You can mention a Discord user, or provide a ROBLOX username."
    )
    @app_commands.describe(reason="What is your reason for punishing this user?")
    async def punish(self, ctx, user: str, type: str, *, reason: str):
        if type.lower() == "warn":
            type = "Warning"

        settings = await self.bot.settings.find_by_id(ctx.guild.id) or {}
        if not settings:
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Setup",
                    description="Your server is not setup.",
                    color=BLANK_COLOR,
                )
            )

        if not (settings.get("punishments") or {}).get("enabled", False):
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description="Your server has punishments disabled.",
                    color=BLANK_COLOR,
                )
            )
        flags = []
        if "--kick" in reason.lower():
            flags.append("autokick")
            reason = reason.replace("--kick", "")
        elif "--ban" in reason.lower():
            flags.append("autoban")
            reason = reason.replace("--ban", "")

        if self.bot.punishments_disabled is True:
            return await new_failure_embed(
                ctx,
                "Maintenance",
                "This command is currently disabled as ERM is currently undergoing maintenance updates. This command will be turned off briefly to ensure that no data is lost during the maintenance.",
            )

        roblox_user = await get_roblox_by_username(user, self.bot, ctx)
        roblox_client = roblox.client.Client()
        if not roblox_user or roblox_user.get("errors") is not None:
            return await ctx.send(
                embed=discord.Embed(
                    title="Could not find player",
                    description="I could not find a Roblox player with that username.",
                    color=BLANK_COLOR,
                )
            )

        roblox_player = await roblox_client.get_user(roblox_user["id"])
        thumbnails = await roblox_client.thumbnails.get_user_avatar_thumbnails(
            [roblox_player], type=roblox.thumbnails.AvatarThumbnailType.headshot
        )
        thumbnail = thumbnails[0].image_url

        # Get and verify punishment type
        punishment_types = await self.bot.punishment_types.get_punishment_types(
            ctx.guild.id
        )
        types = (punishment_types or {}).get("types", [])
        preset_types = ["Warning", "Kick", "Ban", "BOLO"]
        actual_types = []
        for item in preset_types + types:
            if isinstance(item, str):
                actual_types.append(item)
            else:
                actual_types.append(item["name"])

        if type.lower().strip() not in [i.lower().strip() for i in actual_types]:
            return await ctx.send(
                embed=discord.Embed(
                    title="Incorrect Type",
                    description="The punishment type you provided is invalid.",
                    color=BLANK_COLOR,
                )
            )

        # agent = AI(config('AI_API_URL'), config('AI_API_AUTH'))
        # punishment = await agent.recommended_punishment(reason, None)
        msg = None
        # consent_item = await self.bot.consent.find(ctx.author.id) or {}
        # ai_predictions = consent_item.get('ai_predictions', True)
        # if type.lower() in ["warning", "kick", "ban", "bolo"]:
        # if punishment.prediction.lower() !=  type.lower():
        # if ai_predictions:
        # msg = await ctx.send(
        # embed=discord.Embed(
        # title="Recommended Punishment",
        # description="ERM AI thinks that the punishment associated with this reason is not preferable. It suggests that you should **{}** for this punishment, rather than {}. Do you want to change the punishment type?".format(punishment.prediction, type),
        # color=BLANK_COLOR
        # ),
        # view=(view := YesNoMenu(ctx.author.id))
        # )
        # await view.wait()
        # if view.value is True:
        # type = punishment.prediction

        for item in actual_types:
            safe_item = item.lower().split()
            if safe_item == type.lower().split():
                actual_type = item
                break
        else:
            return await ctx.send(
                embed=discord.Embed(
                    title="Incorrect Type",
                    description="The punishment type you provided is invalid.",
                    color=BLANK_COLOR,
                )
            )

        if type.lower() in ["tempban", "temporary ban"]:
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Supported",
                    description="Temporary Bans are not supported.",
                    color=BLANK_COLOR,
                )
            )

        oid = await self.bot.punishments.insert_warning(
            ctx.author.id,
            ctx.author.name,
            roblox_player.id,
            roblox_player.name,
            ctx.guild.id,
            reason,
            actual_type,
            datetime.datetime.now(tz=pytz.UTC).timestamp(),
        )

        current_shift = await self.bot.shift_management.get_current_shift(
            ctx.author, ctx.guild.id
        )
        is_online = bool(current_shift)
        if is_online:
            await self.bot.shift_management.shifts.db.update_one(
                {"_id": current_shift["_id"]}, {"$push": {"Moderations": oid}}
            )

        self.bot.dispatch("punishment", oid)

        warning: WarningItem = await self.bot.punishments.fetch_warning(oid)
        newline = "\n"
        if msg is not None:
            if "autoban" in flags and (await admin_predicate(ctx) or await management_predicate(ctx)):
                try:
                    await self.bot.prc_api.run_command(
                        ctx.guild.id, ":ban {}".format(warning.username)
                    )
                except:
                    pass
            elif "autokick" in flags:
                try:
                    await self.bot.prc_api.run_command(
                        ctx.guild.id, ":kick {}".format(warning.username)
                    )
                except:
                    pass
            return await msg.edit(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Logged Punishment",
                    description=(
                        "I have successfully logged the following punishment!"
                    ),
                    color=GREEN_COLOR,
                )
                .add_field(
                    name="Punishment",
                    value=(
                        f"> **Player:** {warning.username}\n"
                        f"> **Type:** {warning.warning_type}\n"
                        f"> **Moderator:** <@{warning.moderator_id}>\n"
                        f"> **Reason:** {warning.reason}\n"
                        f"> **At:** <t:{int(warning.time_epoch)}>\n"
                        f'{"> **Until:** <t:{}>{}".format(int(warning.until_epoch), newline) if warning.until_epoch is not None else ""}'
                        f"> **ID:** `{warning.snowflake}`"
                        f"> **Custom Flags:** {'`N/A`' if len(flags) == 0 else '`{}`'.format(', '.join(flags))}"
                    ),
                    inline=False,
                )
                .set_thumbnail(url=thumbnail),
                view=None,
            )
        await ctx.send(
            embed=discord.Embed(
                title=f"{self.bot.emoji_controller.get_emoji('success')} Logged Punishment",
                description=("I have successfully logged the following punishment!"),
                color=GREEN_COLOR,
            )
            .add_field(
                name="Punishment",
                value=(
                    f"> **Player:** {warning.username}\n"
                    f"> **Type:** {warning.warning_type}\n"
                    f"> **Moderator:** <@{warning.moderator_id}>\n"
                    f"> **Reason:** {warning.reason}\n"
                    f"> **At:** <t:{int(warning.time_epoch)}>\n"
                    f'{"> **Until:** <t:{}>{}".format(int(warning.until_epoch), newline) if warning.until_epoch is not None else ""}'
                    f"> **ID:** `{warning.snowflake}`\n"
                    f"> **Custom Flags:** {'`N/A`' if len(flags) == 0 else '{}'.format(', '.join(flags))}"
                ),
                inline=False,
            )
            .set_thumbnail(url=thumbnail)
        )

        if "autoban" in flags and (await admin_predicate(ctx) or await management_predicate(ctx)):
            try:
                await self.bot.prc_api.run_command(
                    ctx.guild.id, ":ban {}".format(warning.user_id)
                )
            except:
                pass
        elif "autokick" in flags:
            try:
                await self.bot.prc_api.run_command(
                    ctx.guild.id, ":kick {}".format(warning.username)
                )
            except:
                pass

    @commands.hybrid_group(
        name="punishment",
        description="Punishment commands",
        extras={"category": "Punishments"},
        aliases=["pm"],
    )
    @is_staff()
    async def punishments(self, ctx: commands.Context):
        await ctx.invoke(self.bot.get_command("punishment manage"))

    # Punishment Manage command, containing `types`, `void` and `modify`
    @commands.guild_only()
    @punishments.command(
        name="manage",
        description="Manage punishments",
        extras={"category": "Punishments"},
    )
    @require_settings()
    # @is_management()
    @is_staff()
    async def punishment_manage(self, ctx: commands.Context):
        embed = discord.Embed(
            title="Staff Options",
            description="Using this menu, you can **Manage Punishment Types** as well as **Modify Punishment**.",
            color=BLANK_COLOR,
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
        view = ManagementOptions(ctx.author.id)
        settings = await self.bot.settings.find_by_id(ctx.guild.id)

        msg = await ctx.send(embed=embed, view=view)
        await view.wait()

        if view.value == "modify":
            try:
                punishment_id = int(view.modal.punishment_id.value.strip())
            except ValueError:
                return await msg.edit(
                    embed=discord.Embed(
                        title="Invalid Punishment ID",
                        description="This punishment ID is invalid.",
                        color=BLANK_COLOR,
                    ),
                    view=None,
                )

            punishment = await self.bot.punishments.find_warning_by_spec(
                snowflake=punishment_id, guild_id=ctx.guild.id
            )
            if not punishment:
                return await msg.edit(
                    embed=discord.Embed(
                        title="Invalid Punishment ID",
                        description="This punishment ID is invalid.",
                        color=BLANK_COLOR,
                    ),
                    view=None,
                )

            if (
                punishment["ModeratorID"] != ctx.author.id
                and not await management_predicate(ctx)
                and not await admin_predicate(ctx)
            ):
                return await msg.edit(
                    embed=discord.Embed(
                        title="Access Denied",
                        description="You are unable to edit other people's punishments as you only have the Staff permission.",
                        color=BLANK_COLOR,
                    )
                )

            view = PunishmentModifier(self.bot, ctx.author.id, punishment)
            await view.refresh_ui(msg)
            await view.wait()
            await msg.edit(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Modified!",
                    description="Successfully modified this punishment!",
                    color=GREEN_COLOR,
                ),
                view=None,
            )

        elif view.value == "types":
            if not await management_predicate(ctx):
                return await msg.edit(
                    embed=discord.Embed(
                        title="Not Permitted",
                        description="You are not permitted to access this panel.",
                        color=BLANK_COLOR,
                    ),
                    view=None,
                )
            punishment_types = await self.bot.punishment_types.get_punishment_types(
                ctx.guild.id
            )
            if not punishment_types:
                punishment_types = {"types": []}

            punishment_types = punishment_types["types"]

            def setup_embed() -> discord.Embed:
                embed = discord.Embed(title="Punishment Types", color=BLANK_COLOR)
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
                return embed

            filtered = list(filter(lambda x: isinstance(x, dict), punishment_types))
            embeds = []
            associations = {}
            if len(embeds) == 0:
                embeds.append(setup_embed())

            for item in filtered:

                if len(embeds[-1].fields) > 15:
                    embeds[-1].add_field(
                        name="Limitation",
                        value="You cannot have more than 15 custom punishment types.",
                        inline=False,
                    )
                    break

                embeds[-1].add_field(
                    name=item["name"],
                    value=(
                        f"> **Name:** {item['name']}\n"
                        f"> **ID:** {item.get('id', (temporary_id := next(generator)))}\n"
                        f"> **Channel:** <#{item['channel']}>"
                    ),
                    inline=False,
                )
                associations[temporary_id] = item
            if len(embeds[0].fields) == 0:
                embeds[0].add_field(
                    name="No Punishment Types",
                    value="There are no custom punishment types in this server.",
                    inline=False,
                )
            manage_types_view = ManageTypesView(self.bot, ctx.author.id)
            await msg.edit(embed=embeds[0], view=manage_types_view)
            await manage_types_view.wait()
            if manage_types_view.value == "create":
                data = {
                    "id": next(generator),
                    "name": manage_types_view.name_for_creation,
                    "channel": None,
                }
                embed = discord.Embed(
                    title="Punishment Type Creation",
                    description=(
                        f"> **Name:** {data['name']}\n"
                        f"> **ID:** {data['id']}\n"
                        f"> **Punishment Channel:** {'<#{}>'.format(data.get('channel', None)) if data.get('channel', None) is not None else 'Not set'}\n"
                    ),
                    color=BLANK_COLOR,
                )

                view = PunishmentTypeCreator(ctx.author.id, data)
                await msg.edit(view=view, embed=embed)
                await view.wait()
                if view.cancelled is True:
                    return

                punishment_types.append(view.dataset)

                await self.bot.punishment_types.upsert(
                    {"_id": ctx.guild.id, "types": punishment_types}
                )
                await msg.edit(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('success')} Type Created",
                        description="Your punishment type has been created!",
                        color=GREEN_COLOR,
                    ),
                    view=None,
                )
            elif manage_types_view.value == "delete":
                if not await management_predicate(ctx):
                    return await msg.edit(
                        embed=discord.Embed(
                            title="Not Permitted",
                            description="You are not permitted to access this panel.",
                            color=BLANK_COLOR,
                        )
                    )
                try:
                    type_id = int(manage_types_view.selected_for_deletion.strip())
                except ValueError:
                    return await msg.edit(
                        embed=discord.Embed(
                            title="Invalid Punishment Type",
                            description="The ID you have provided is not associated with a punishment type.",
                            color=BLANK_COLOR,
                        ),
                        view=None,
                    )
                if len(punishment_types) == 0:
                    return await msg.edit(
                        embed=discord.Embed(
                            title="Invalid Punishment Type",
                            description="The ID you have provided is not associated with a punishment type.",
                            color=BLANK_COLOR,
                        ),
                        view=None,
                    )
                if type_id not in [t.get("id") for t in list(filtered)]:
                    if not associations.get(type_id):
                        return await msg.edit(
                            embed=discord.Embed(
                                title="Invalid Punishment Type",
                                description="The ID you have provided is not associated with a punishment type.",
                                color=BLANK_COLOR,
                            ),
                            view=None,
                        )
                for item in filtered:
                    if item.get("id") == type_id or item == associations.get(type_id):
                        punishment_types.remove(item)
                        break

                await self.bot.punishment_types.upsert(
                    {"_id": ctx.guild.id, "types": punishment_types}
                )
                await msg.edit(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('success')} Type Deleted",
                        description="Your Punishment Type has been deleted!",
                        color=GREEN_COLOR,
                    ),
                    view=None,
                )

    @commands.hybrid_group(
        name="bolo",
        description="Manage the server's BOLO list.",
        extras={"category": "Punishments"},
    )
    async def bolo(self, ctx):
        pass

    @commands.guild_only()
    @bolo.command(
        name="active",
        description="View the server's active BOLOs.",
        extras={"category": "Punishments", "ignoreDefer": True},
        aliases=["search", "lookup"],
    )
    @app_commands.autocomplete(user=user_autocomplete)
    @app_commands.describe(user="The user to search for.")
    @is_staff()
    @require_settings()
    async def active(self, ctx, user: str = None):

        async def task(interaction: discord.Interaction, _):
            modal = CustomModal(
                "Mark as Complete",
                [
                    (
                        "bolo",
                        discord.ui.TextInput(
                            placeholder="The ID for the BOLO you are marking as complete",
                            label="BOLO ID",
                        ),
                    )
                ],
                {"ephemeral": True, "thinking": True},
            )

            await interaction.response.send_modal(modal)
            timeout = await modal.wait()
            if timeout:
                return
            try:
                id = int(modal.bolo.value)
            except ValueError:
                return await modal.interaction.followup.send(
                    embed=discord.Embed(
                        title="Invalid Identifier",
                        description="I could not find a BOLO associating with that ID. Please ensure you have entered the correct ID.",
                        color=BLANK_COLOR,
                    )
                )

            matching_docs = list(
                filter(
                    lambda x: x is not None,
                    [
                        await bot.punishments.find_warning_by_spec(
                            snowflake=id,
                            warning_type="BOLO",
                            guild_id=interaction.guild.id,
                        )
                    ],
                )
            )

            if len(matching_docs) == 0:
                return await modal.interaction.followup.send(
                    embed=discord.Embed(
                        title="Invalid Identifier",
                        description="I could not find a BOLO associating with that ID. Please ensure you have entered the correct ID.",
                        color=BLANK_COLOR,
                    )
                )

            doc = matching_docs[0]

            await bot.punishments.insert_warning(
                ctx.author.id,
                ctx.author.name,
                doc["UserID"],
                doc["Username"],
                ctx.guild.id,
                f"BOLO marked as complete by {ctx.author} ({ctx.author.id}). Original BOLO Reason was {doc['Reason']} made by {doc['Moderator']} ({doc['ModeratorID']})",
                "Ban",
                datetime.datetime.now(tz=pytz.UTC).timestamp(),
            )

            await bot.punishments.remove_warning_by_snowflake(id)

            await modal.interaction.followup.send(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Completed BOLO",
                    description="This BOLO has been marked as complete successfully.",
                    color=GREEN_COLOR,
                )
            )
            return

        async def deny_task(interaction: discord.Interaction, _):
            modal = CustomModal(
                "Mark as Denied",
                [
                    (
                        "bolo",
                        discord.ui.TextInput(
                            placeholder="The ID for the BOLO you are marking as denied",
                            label="BOLO ID",
                        ),
                    )
                ],
                {"ephemeral": True, "thinking": True},
            )

            await interaction.response.send_modal(modal)
            timeout = await modal.wait()
            if timeout:
                return
            try:
                id = int(modal.bolo.value)
            except ValueError:
                return await modal.interaction.followup.send(
                    embed=discord.Embed(
                        title="Invalid Identifier",
                        description="I could not find a BOLO associating with that ID. Please ensure you have entered the correct ID.",
                        color=BLANK_COLOR,
                    )
                )

            # bro i just realised someone could use this to erase a non-bolo...
            matching_docs = list(
                filter(
                    lambda x: x is not None,
                    [
                        await bot.punishments.find_warning_by_spec(
                            snowflake=id,
                            warning_type="BOLO",
                            guild_id=interaction.guild.id,
                        )
                    ],
                )
            )

            if len(matching_docs) == 0:
                return await modal.interaction.followup.send(
                    embed=discord.Embed(
                        title="Invalid Identifier",
                        description="I could not find a BOLO associating with that ID. Please ensure you have entered the correct ID.",
                        color=BLANK_COLOR,
                    )
                )

            doc = matching_docs[0]

            await bot.punishments.remove_warning_by_snowflake(id)

            await modal.interaction.followup.send(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Denied BOLO",
                    description="This BOLO has been marked as denied successfully.\nIt has been erased from the active BOLO list.",
                    color=GREEN_COLOR,
                )
            )
            return

        if self.bot.punishments_disabled is True:
            return await failure_embed(
                ctx,
                "This command is currently disabled as ERM is currently undergoing maintenance updates. This command will be turned off briefly to ensure that no data is lost during the maintenance. It will be returned shortly.",
            )

        bot = self.bot
        if user is None:
            bolos = await bot.punishments.get_guild_bolos(ctx.guild.id)
            msg = None
            if len(bolos) == 0:
                return await ctx.reply(
                    embed=discord.Embed(
                        title="No Entries",
                        description="There are no active BOLOs in this server.",
                        color=BLANK_COLOR,
                    )
                )
            embeds = []

            embed = discord.Embed(
                title="Active Ban BOLOs",
                color=BLANK_COLOR,
            )

            embed.set_author(
                name=ctx.guild.name,
                icon_url=ctx.guild.icon,
            )

            embed.set_footer(
                text="Click 'Mark as Complete' or 'Deny BOLO' and enter the BOLO ID."
            )

            embeds.append(embed)

            for entry in bolos:
                if len(embeds[-1].fields) == 4:
                    new_embed = discord.Embed(
                        title="Active Ban BOLOs",
                        color=BLANK_COLOR,
                    )

                    new_embed.set_author(
                        name=ctx.guild.name,
                        icon_url=ctx.guild.icon,
                    )

                    embeds.append(new_embed)

                warning: WarningItem = await bot.punishments.fetch_warning(entry["_id"])

                embeds[-1].add_field(
                    name=f"{warning.username} ({warning.user_id})",
                    inline=False,
                    value=(
                        f"> **Moderator:** <@{warning.moderator_id}>\n"
                        f"> **Reason:** {warning.reason}\n"
                        f"> **At:** <t:{int(warning.time_epoch)}>\n"
                        f"> **ID:** `{warning.snowflake}`"
                    ),
                )

            for embed in embeds:
                embed.title += " [{}]".format(len(bolos))

            view = discord.ui.View()
            view.add_item(
                CustomExecutionButton(
                    ctx.author.id,
                    "Mark as Complete",
                    discord.ButtonStyle.secondary,
                    func=task,
                )
            )
            view.add_item(
                CustomExecutionButton(
                    ctx.author.id,
                    "Deny BOLO",
                    discord.ButtonStyle.danger,
                    func=deny_task,
                )
            )

            paginator = SelectPagination(
                self.bot,
                ctx.author.id,
                [
                    CustomPage(embeds=[embed], view=view, identifier=str(index + 1))
                    for index, embed in enumerate(embeds)
                ],
            )
            current_page = paginator.get_current_view()

            msg = await ctx.reply(embed=embeds[0], view=current_page)

        else:
            roblox_user = await get_roblox_by_username(user, bot, ctx)
            if roblox_user is None:
                return await ctx.send(
                    embed=discord.Embed(
                        title="Could not find player",
                        description="I could not find a Roblox player with that username.",
                        color=BLANK_COLOR,
                    )
                )

            if roblox_user.get("errors") is not None:
                return await ctx.send(
                    embed=discord.Embed(
                        title="Could not find player",
                        description="I could not find a Roblox player with that username.",
                        color=BLANK_COLOR,
                    )
                )

            user = [
                i
                async for i in bot.punishments.find_warnings_by_spec(
                    ctx.guild.id, user_id=roblox_user["id"], bolo=True
                )
            ]
            bolos = user

            if user is None:
                return await ctx.reply(
                    embed=discord.Embed(
                        title="No Entries",
                        description="There are no active BOLOs for this user in this server.",
                        color=BLANK_COLOR,
                    )
                )

            if len(bolos) == 0:
                return await ctx.reply(
                    embed=discord.Embed(
                        title="No Entries",
                        description="There are no active BOLOs for this user in this server.",
                        color=BLANK_COLOR,
                    )
                )

            embeds = []

            embed = discord.Embed(
                title="Active Ban BOLOs",
                color=BLANK_COLOR,
            )

            embed.set_author(
                name=ctx.guild.name,
                icon_url=ctx.guild.icon,
            )

            embed.set_footer(
                text="Click 'Mark as Complete' or 'Deny BOLO' and enter the BOLO ID."
            )

            embeds.append(embed)

            for entry in bolos:
                if len(embeds[-1].fields) == 4:
                    new_embed = discord.Embed(
                        title="Active Ban BOLOs",
                        color=BLANK_COLOR,
                    )

                    new_embed.set_author(
                        name=ctx.guild.name,
                        icon_url=ctx.guild.icon,
                    )

                    embeds.append(new_embed)

                warning: WarningItem = await bot.punishments.fetch_warning(entry["_id"])

                embeds[-1].add_field(
                    name=f"{warning.username} ({warning.user_id})",
                    inline=False,
                    value=(
                        f"> **Moderator:** <@{warning.moderator_id}>\n"
                        f"> **Reason:** {warning.reason}\n"
                        f"> **At:** <t:{int(warning.time_epoch)}>\n"
                        f"> **ID:** `{warning.snowflake}`"
                    ),
                )

            for embed in embeds:
                embed.title += " [{}]".format(len(bolos))

            view = discord.ui.View()
            view.add_item(
                CustomExecutionButton(
                    ctx.author.id,
                    "Mark as Complete",
                    discord.ButtonStyle.secondary,
                    func=task,
                )
            )
            view.add_item(
                CustomExecutionButton(
                    ctx.author.id,
                    "Deny BOLO",
                    discord.ButtonStyle.danger,
                    func=deny_task,
                )
            )

            paginator = SelectPagination(
                self.bot,
                ctx.author.id,
                [
                    CustomPage(embeds=[embed], view=view, identifier=str(index + 1))
                    for index, embed in enumerate(embeds)
                ],
            )
            current_page = paginator.get_current_view()

            msg = await ctx.reply(embed=embeds[0], view=current_page)

    @commands.guild_only()
    @commands.hybrid_command(
        name="tempban",
        aliases=["tb", "tba"],
        description="Tempbans a user.",
        extras={"category": "Punishments"},
        with_app_command=True,
    )
    @is_staff()
    @app_commands.autocomplete(user=user_autocomplete)
    @app_commands.describe(user="What's their ROBLOX username?")
    @app_commands.describe(time="How long are you banning them for? (s/m/h/d)")
    @app_commands.describe(reason="What is your reason for punishing this user?")
    async def tempban(self, ctx, user, time: str, *, reason):
        if self.bot.punishments_disabled is True:
            return await new_failure_embed(
                ctx,
                "Maintenance",
                "This command is currently disabled as ERM is currently undergoing maintenance updates. This command will be turned off briefly to ensure that no data is lost during the maintenance.",
            )

        try:
            amount = time_converter(time)
        except ValueError:
            return await ctx.send(
                embed=discord.Embed(
                    title="Invalid Time",
                    description="The time provided is invalid.",
                    color=BLANK_COLOR,
                )
            )

        roblox_user = await get_roblox_by_username(user, self.bot, ctx)
        roblox_client = roblox.client.Client()
        if not roblox_user or roblox_user.get("errors") is not None:
            return await ctx.send(
                embed=discord.Embed(
                    title="Could not find player",
                    description="I could not find a Roblox player with that username.",
                    color=BLANK_COLOR,
                )
            )

        roblox_player = await roblox_client.get_user(roblox_user["id"])
        thumbnails = await roblox_client.thumbnails.get_user_avatar_thumbnails(
            [roblox_player], type=roblox.thumbnails.AvatarThumbnailType.headshot
        )
        thumbnail = thumbnails[0].image_url

        oid = await self.bot.punishments.insert_warning(
            ctx.author.id,
            ctx.author.name,
            roblox_player.id,
            roblox_player.name,
            ctx.guild.id,
            reason,
            "Temporary Ban",
            datetime.datetime.now(tz=pytz.UTC).timestamp(),
            datetime.datetime.now(tz=pytz.UTC).timestamp() + amount,
        )

        self.bot.dispatch("punishment", oid)

        warning: WarningItem = await self.bot.punishments.fetch_warning(oid)
        newline = "\n"
        await ctx.send(
            embed=discord.Embed(
                title=f"{self.bot.emoji_controller.get_emoji('success')} Logged Punishment",
                description=("I have successfully logged the following punishment!"),
                color=GREEN_COLOR,
            )
            .add_field(
                name="Punishment",
                value=(
                    f"> **Player:** {warning.username}\n"
                    f"> **Moderator:** <@{warning.moderator_id}>\n"
                    f"> **Reason:** {warning.reason}\n"
                    f"> **At:** <t:{int(warning.time_epoch)}>\n"
                    f'{"> **Until:** <t:{}>{}".format(int(warning.until_epoch), newline) if warning.until_epoch is not None else ""}'
                    f"> **ID:** `{warning.snowflake}`"
                ),
                inline=False,
            )
            .set_thumbnail(url=thumbnail)
        )


async def setup(bot):
    await bot.add_cog(Punishments(bot))
