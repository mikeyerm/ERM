import asyncio
import datetime
import json
import re
import discord
import roblox
from discord.ext import commands
from utils.autocompletes import erlc_group_autocomplete, erlc_players_autocomplete
from roblox.thumbnails import AvatarThumbnailType 

import logging
from typing import List
from erm import admin_check, is_staff, is_management
from utils.paginators import CustomPage, SelectPagination
from menus import CustomModal, ReloadView, RefreshConfirmation, RiskyUsersMenu, CustomExecutionButton
import copy
from utils.constants import *
from utils.prc_api import (
    Player,
    ServerStatus,
    KillLog,
    JoinLeaveLog,
    CommandLog,
    ResponseFailure,
)
import utils.prc_api as prc_api
from utils.utils import get_discord_by_roblox, log_command_usage, secure_logging
from discord import app_commands
import typing


class ERLC(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def is_server_linked():
        async def predicate(ctx: commands.Context):
            guild_id = ctx.guild.id
            command_group = ctx.command.full_parent_name

            try:
                if command_group == "erlc":
                    await ctx.bot.prc_api.get_server_status(guild_id)
                elif command_group == "mc":
                    await ctx.bot.mc_api.get_server_status(guild_id)
            except prc_api.ResponseFailure as exc:
                error = prc_api.ServerLinkNotFound(platform=command_group)
                try:
                    error.code = exc.json_data.get("code") or exc.status_code
                except json.JSONDecodeError:
                    pass
                raise error
            return True

        return commands.check(predicate)

    async def secure_logging(
        self,
        guild_id,
        author_id,
        interpret_type: typing.Literal["Message", "Hint", "Command"],
        command_string: str,
        attempted: bool = False,
    ):
        await secure_logging(
            self.bot, guild_id, author_id, interpret_type, command_string, attempted
        )

    @commands.hybrid_group(name="erlc")
    async def server(self, ctx: commands.Context):
        pass

    @commands.hybrid_group(name="mc")  # hmmmm...
    async def mc(self, ctx: commands.Context):
        pass

    @mc.command(name="link", description="Link your Maple County server with ERM!")
    @is_management()
    async def mc_link(self, ctx: commands.Context, *, server_name: str):
        # get the linked roblox user
        roblox_id = 0
        oauth2_user = (
            await self.bot.oauth2_users.db.find_one({"discord_id": ctx.author.id}) or {}
        )
        if not oauth2_user.get("roblox_id"):
            # go to fallback
            roblox_user = await self.bot.bloxlink.find_roblox(ctx.author.id)
            if not roblox_user.get("robloxID"):
                return await ctx.send(
                    embed=discord.Embed(
                        title="Not Linked",
                        description="You are not linked to any ROBLOX account.",
                        color=BLANK_COLOR,
                    )
                )
            roblox_id = roblox_user["robloxID"]
        else:
            roblox_id = oauth2_user["roblox_id"]

        try:
            server_token = await self.bot.mc_api.authorize(
                roblox_id, server_name, ctx.guild.id
            )
        except prc_api.ResponseFailure:  # yes, this is correct.
            return await ctx.send(
                embed=discord.Embed(
                    title="Server Not Found",
                    description="We could not find a server you own under the server name provided. Make sure you are linked with ERM by running `/link` in any server.",
                    color=BLANK_COLOR,
                )
            )

        await ctx.send(
            embed=discord.Embed(
                title=f"{self.bot.emoji_controller.get_emoji('success')} Server Linked",
                description=f"Your server has been linked with the name `{server_name}`.",
                color=GREEN_COLOR,
            )
        )

    @mc.command(
        name="info",
        description="Get information about the current players in your Maple County server.",
    )
    @is_server_linked()
    async def mc_info(self, ctx: commands.Context):
        guild_id = ctx.guild.id

        async def operate_and_reload_serverinfo(
            msg: discord.Message | None, guild_id: str
        ):
            guild_id = int(guild_id)
            status: ServerStatus = await self.bot.mc_api.get_server_status(guild_id)
            players: list[Player] = await self.bot.mc_api.get_server_players(guild_id)
            client = roblox.Client()

            embed1 = discord.Embed(title=f"{status.name}", color=BLANK_COLOR)
            embed1.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
            embed1.add_field(
                name="Basic Info",
                value=(
                    f"> **Join Code:** [{status.join_key}](https://www.roblox.com/games/start?placeId=8416011646&launchData=psjoincode%3D{status.join_key}&deep_link_value=roblox%3A%2F%2FplaceId%3D8416011646)\n"
                    f"> **Current Players:** {status.current_players}/{status.max_players}\n"
                ),
                inline=False,
            )
            embed1.add_field(
                name="Server Ownership",
                value=(
                    f"> **Owner:** [{(await client.get_user(status.owner_id)).name}](https://roblox.com/users/{status.owner_id}/profile)\n"
                    f"> **Co-Owners:** {f', '.join([f'[{user.name}](https://roblox.com/users/{user.id}/profile)' for user in await client.get_users(status.co_owner_ids, expand=False)])}"
                ),
                inline=False,
            )

            embed1.add_field(
                name="Staff Statistics",
                value=(
                    f"> **Moderators:** {len(list(filter(lambda x: x.permission == 'Server Moderator', players)))}\n"
                    f"> **Administrators:** {len(list(filter(lambda x: x.permission == 'Server Administrator', players)))}\n"
                    f"> **Staff In-Game:** {len(list(filter(lambda x: x.permission != 'Normal', players)))}\n"
                    f"> **Staff Clocked In:** {await self.bot.shift_management.shifts.db.count_documents({'Guild': guild_id, 'EndEpoch': 0})}"
                ),
                inline=False,
            )

            if msg is None:
                view = ReloadView(
                    self.bot,
                    ctx.author.id,
                    operate_and_reload_serverinfo,
                    [None, guild_id],
                )
                msg = await ctx.send(embed=embed1, view=view)
                view.message = msg
                view.callback_args[0] = msg
            else:
                await msg.edit(embed=embed1)

        await operate_and_reload_serverinfo(None, guild_id)

    @mc.command(name="logs", description="See the Command Logs of your server.")
    @is_staff()
    @is_server_linked()
    async def mc_logs(self, ctx: commands.Context):
        guild_id = ctx.guild.id

        async def operate_and_reload_commandlogs(msg, guild_id: str):
            guild_id = int(guild_id)
            # status: ServerStatus = await self.bot.prc_api.get_server_status(guild_id)
            command_logs: list[CommandLog] = await self.bot.mc_api.fetch_server_logs(
                guild_id
            )
            embed = discord.Embed(
                color=BLANK_COLOR, title="Command Logs", description=""
            )

            sorted_logs = sorted(
                command_logs, key=lambda log: log.timestamp, reverse=True
            )
            for log in sorted_logs:
                if len(embed.description) > 3800:
                    break
                embed.description += f"> [{log.username}](https://roblox.com/users/{log.user_id}/profile) ran the command `{log.command}` • <t:{int(log.timestamp)}:R>\n"

            if embed.description in ["", "\n"]:
                embed.description = "> No player logs found."

            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

            if msg is None:
                view = ReloadView(
                    self.bot,
                    ctx.author.id,
                    operate_and_reload_commandlogs,
                    [None, guild_id],
                )
                msg = await ctx.send(embed=embed, view=view)
                view.message = msg
                view.callback_args[0] = msg
            else:
                await msg.edit(embed=embed)

        await operate_and_reload_commandlogs(None, guild_id)

    @mc.command(name="bans", description="Filter the bans of your server.")
    @is_staff()
    @is_server_linked()
    async def mc_bans(
        self,
        ctx: commands.Context,
        username: typing.Optional[str],
        user_id: typing.Optional[int],
    ):
        guild_id = ctx.guild.id
        # status: ServerStatus = await self.bot.prc_api.get_server_status(guild_id)
        try:
            bans: list[prc_api.BanItem] = await self.bot.mc_api.fetch_bans(guild_id)
        except prc_api.ResponseFailure:
            return await ctx.send(
                embed=discord.Embed(
                    title="MC API Error",
                    description="There were no bans, or your API key is incorrect.",
                    color=BLANK_COLOR,
                )
            )
        embed = discord.Embed(color=BLANK_COLOR, title="Bans", description="")
        status = username or user_id

        if not username and user_id:
            username = "[PLACEHOLDER]"

        if not user_id and username:
            user_id = "99999"
        old_embed = copy.copy(embed)
        embeds = [embed]
        for log in bans:
            if str(username or "") in str(log.username).lower() or str(
                user_id or ""
            ) in str(log.user_id):
                embed = embeds[-1]
                if len(embed.description) > 3800:
                    new = copy.copy(old_embed)
                    embeds.append(new)
                embeds[
                    -1
                ].description += f"> [{log.username}:{log.user_id}](https://roblox.com/users/{log.user_id}/profile)\n"

        if embeds[0].description in ["", "\n"]:
            embeds[0].description = (
                "> This ban was not found."
                if status
                else "> Bans were not found in your server."
            )

        embeds[0].set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

        if len(embeds) > 1:
            pages = [
                CustomPage(embeds=[embeds[i]], identifier=str(i + 1))
                for i in range(0, len(embeds) - 1)
            ]
            paginator = SelectPagination(self.bot, ctx.author.id, pages)
            await ctx.send(embed=embeds[0], view=paginator.get_current_view())
            return
        else:
            await ctx.send(embed=embed)

    @mc.command(name="players", description="See all players in the server.")
    @is_server_linked()
    async def mc_players(
        self, ctx: commands.Context, filter: typing.Optional[str] = None
    ):
        guild_id = int(ctx.guild.id)
        players: list[Player] = await self.bot.mc_api.get_server_players(guild_id)
        embed2 = discord.Embed(
            title=f"Server Players [{len(players)}]", color=BLANK_COLOR, description=""
        )
        actual_players = []
        key_maps = {}
        staff = []
        for item in players:
            if item.permission == "Normal":
                actual_players.append(item)
            else:
                staff.append(item)

        if filter not in [None, ""]:
            actual_players_copy = []
            for item in actual_players:
                if item.username.lower().startswith(filter.lower()):
                    actual_players_copy.append(item)
            actual_players = actual_players_copy
            staff_copy = []
            for item in staff:
                if item.username.lower().startswith(filter.lower()):
                    staff_copy.append(item)
            staff = staff_copy

        embed2.description += f"**Server Staff [{len(staff)}]**\n" + (
            ", ".join(
                [
                    f"[{plr.username}](https://roblox.com/users/{plr.id}/profile)"
                    for plr in staff
                ]
            )
            or "> No players in this category."
        )

        embed2.description += f"\n\n**Online Players [{len(actual_players)}]**\n" + (
            ", ".join(
                [
                    f"[{plr.username}](https://roblox.com/users/{plr.id}/profile)"
                    for plr in actual_players
                ]
            )
            or "> No players in this category."
        )

        embed2.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
        if len(embed2.description) > 3999:
            embed2.description = ""
            embed2.description += f"**Server Staff [{len(staff)}]**\n" + ", ".join(
                [f"{plr.username}" for plr in staff]
            )

            embed2.description += (
                f"\n\n**Online Players [{len(actual_players)}]**\n"
                + ", ".join([f"{plr.username}" for plr in actual_players])
            )

        await ctx.send(embed=embed2)


    @server.command(
        name="panel",
        description="Open a panel that allows you to manage a player in your server.",
        aliases=["playerpanel", "manage"],
    )
    @app_commands.autocomplete(target=erlc_players_autocomplete)
    @app_commands.describe(target="Who would you like to manage?")
    @is_staff()
    @is_server_linked()
    async def erlc_panel(self, ctx: commands.Context, target: str):

        client = roblox.Client()
        roblox_player = await client.get_user_by_username(target)

        thumbnails = await client.thumbnails.get_user_avatar_thumbnails(
            [roblox_player], type=AvatarThumbnailType.full_body, size="720x720"
        )

        server_staff = await self.bot.prc_api.get_server_staff(ctx.guild.id)
        player_item = list(filter(lambda x: x.username.lower() == roblox_player.name.lower(), server_staff))
        player_permission = ""
        if len(player_item) == 0:
            player_permission = "Normal"
        else:
            player_permission = player_item[0].permission
        
        server_players = await self.bot.prc_api.get_server_players(ctx.guild.id)
        matched_players = list(filter(lambda x: x.username.lower() == roblox_player.name.lower(), server_players))
        disable_online_buttons = False
        erlc_player = None
        if len(matched_players) == 0:
            disable_online_buttons = True
        else:
            erlc_player = matched_players[0]

        server_join_logs = await self.bot.prc_api.fetch_player_logs(ctx.guild.id)
        matching_player_logs = list(filter(lambda x: x.username.lower() == roblox_player.name.lower(), server_join_logs))
        vehicle_information = await self.bot.prc_api.get_server_vehicles(ctx.guild.id)
        if len(vehicle_information) > 0:
            vehicle_information = list(
                filter(lambda x: x.username.lower() == roblox_player.name.lower(), vehicle_information)
            )
        else:
            vehicle_information = []

        kill_logs = await self.bot.prc_api.fetch_kill_logs(ctx.guild.id)
        matching_kill_logs = list(
            filter(lambda x: x.killer_username.lower() == roblox_player.name.lower() or x.killed_username.lower() == roblox_player.name.lower(), kill_logs)
        )
        
        modcalls = await self.bot.prc_api.get_mod_calls(ctx.guild.id)
        matching_modcalls = list(
            filter(
                lambda x: x.caller_username.lower() == roblox_player.name.lower() or (x.moderator_username and x.moderator_username.lower() == roblox_player.name.lower()), modcalls
            )
        )

        command_logs = await self.bot.prc_api.fetch_server_logs(ctx.guild.id)
        matching_command_logs = list(
            filter(lambda x: x.username.lower() == roblox_player.name.lower(), command_logs)
        )

        newline = "\n" # backwards python compatibility

        async def view_kills_callback(interaction: discord.Interaction, button: discord.ui.Button):
            if not matching_kill_logs:
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        title="No Kills Found",
                        description="This player has no kills in the server.",
                        color=BLANK_COLOR,
                    ),
                    ephemeral=True,
                )

            killsContainer = discord.ui.Container(
                discord.ui.TextDisplay(
                    "\n".join(
                    [
                        f"> [{log.killer_username}](https://roblox.com/users/{log.killer_user_id}/profile) killed [{log.killed_username}](https://roblox.com/users/{log.killed_user_id}/profile) • <t:{log.timestamp}:F>"
                        for log in matching_kill_logs
                    ]
                    )
                )
            )

            await interaction.response.send_message(
                view=discord.ui.LayoutView().add_item(killsContainer),
                ephemeral=True
            )

        async def view_commands_callback(interaction: discord.Interaction, button: discord.ui.Button):
            if not matching_command_logs:
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        title="No Commands Found",
                        description="This player has no commands in the server.",
                        color=BLANK_COLOR,
                    ),
                    ephemeral=True,
                )

            commandsContainer = discord.ui.Container(
                discord.ui.TextDisplay(
                    "\n".join(
                        [
                            f"> [{log.username}](https://roblox.com/users/{log.user_id}/profile) ran `{log.command}` • <t:{log.timestamp}:F>"
                            for log in matching_command_logs
                        ]
                    )
                )
            )

            await interaction.response.send_message(
                view=discord.ui.LayoutView().add_item(commandsContainer),
                ephemeral=True
            )

        async def view_modcalls_callback(interaction: discord.Interaction, button: discord.ui.Button):
            if not matching_modcalls:
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        title="No Modcalls Found",
                        description="This player has no modcalls in the server.",
                        color=BLANK_COLOR,
                    ),
                    ephemeral=True,
                )

            modcallsContainer = discord.ui.Container(
                discord.ui.TextDisplay(
                    "\n".join(
                        [
                            f"> Caller: {call.caller} • Moderator: {call.moderator} • <t:{call.timestamp}:F>"
                            for call in matching_modcalls
                        ]
                    )
                )
            )

            await interaction.response.send_message(
                view=discord.ui.LayoutView().add_item(modcallsContainer),
                ephemeral=True
            )

        async def refresh_player_callback(interaction: discord.Interaction, button: discord.ui.Button):
            # use prc_api integration to run command :refresh XYZ
            if disable_online_buttons:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Player Offline",
                            description="This player is currently offline, and cannot be refreshed.",
                            color=BLANK_COLOR,
                        ),
                        ephemeral=True,
                    )
            
            command_response = self.bot.prc_api.run_command(
                ctx.guild.id, f":refresh {roblox_player.name}"
            )
            if command_response[0] == 200:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title=f"{self.bot.emoji_controller.get_emoji('success')} Player Refreshed",
                            description=f"The player {roblox_player.name} has been refreshed successfully.",
                            color=GREEN_COLOR,
                        ),
                        ephemeral=True,
                )
            else:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Refresh Failed",
                            description="The player could not be refreshed successfully.",
                            color=BLANK_COLOR,
                        ),
                        ephemeral=True,
                    )

        async def respawn_player_callback(interaction: discord.Interaction, button: discord.ui.Button):
            if disable_online_buttons:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Player Offline",
                            description="This player is currently offline, and cannot be respawned.",
                            color=BLANK_COLOR,
                        ),
                        ephemeral=True,
                    )
            
            command_response = self.bot.prc_api.run_command(
                ctx.guild.id, f":respawn {roblox_player.name}"
            )
            if command_response[0] == 200:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title=f"{self.bot.emoji_controller.get_emoji('success')} Player Respawned",
                            description=f"The player {roblox_player.name} has been respawned successfully.",
                            color=GREEN_COLOR,
                        ),
                        ephemeral=True,
                )
            else:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Respawn Failed",
                            description="The player could not be respawned successfully.",
                            color=BLANK_COLOR,
                        ),
                        ephemeral=True,
                    )

        async def teleport_to_callback(interaction: discord.Interaction, button: discord.ui.Button):
            modal = CustomModal(
                f"Teleport To Player",
                [
                    (
                        "value",
                        discord.ui.TextInput(
                            label="Roblox Username",
                            placeholder="Roblox Username (e.g. i_iMikey)",
                            required=True,
                        ),
                    )
                ]
            )

            await interaction.response.send_modal(modal)
            await modal.wait()
            username = modal.value.value
            if not username:
                return
            
            command_response = await self.bot.prc_api.run_command(
                ctx.guild.id, (command := f":tp {username} {roblox_player.name}")
            )
            if command_response[0] == 200:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('success')} Teleported",
                        description=f"The player {username} has been teleported to {roblox_player.name}.",
                        color=GREEN_COLOR,
                    ),
                    ephemeral=True,
                )
                await self.secure_logging(
                    ctx.guild.id, ctx.author.id, "Command", command
                )
            else:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="Teleport Failed",
                        description="The player could not be teleported.",
                        color=BLANK_COLOR,
                    ),
                    ephemeral=True,
                )
                await self.secure_logging(
                    ctx.guild.id, ctx.author.id, "Command", command
                )

        async def pm_player_callback(interaction: discord.Interaction, button: discord.ui.Button):
            modal = CustomModal(
                f"PM Player",
                [
                    (
                        "value",
                        discord.ui.TextInput(
                            label="Message",
                            placeholder="What message would you like to send?",
                            required=True,
                        ),
                    )
                ]
            )

            await interaction.response.send_modal(modal)
            await modal.wait()
            message = modal.value.value
            if not message:
                return
            
            command_response = await self.bot.prc_api.run_command(
                ctx.guild.id, (command := f":pm {target} {message}")
            )
            if command_response[0] == 200:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('success')} PM Sent",
                        description=f"The message has been sent to {roblox_player.name}.",
                        color=GREEN_COLOR,
                    ),
                    ephemeral=True,
                )
                await self.secure_logging(
                    ctx.guild.id, ctx.author.id, "Command", command
                )
            else:
                await interaction.followup.send(
                    embed=discord.Embed(
                        title="PM Failed",
                        description="The message could not be sent to the player.",
                        color=BLANK_COLOR,
                    ),
                    ephemeral=True,
                )
                await self.secure_logging(
                    ctx.guild.id, ctx.author.id, "Command", command
                )

        
        async def kick_player_callback(interaction: discord.Interaction, button: discord.ui.Button):
            if disable_online_buttons:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Player Offline",
                            description="This player is currently offline, and cannot be kicked.",
                            color=BLANK_COLOR,
                        ),
                        ephemeral=True,
                    )
            
            command_response = self.bot.prc_api.run_command(
                ctx.guild.id, (command := f":kick {roblox_player.name}")
            )
            await self.secure_logging(
                ctx.guild.id, ctx.author.id, "Command", command
            )
            if command_response[0] == 200:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title=f"{self.bot.emoji_controller.get_emoji('success')} Player Kicked",
                            description=f"The player {roblox_player.name} has been kicked successfully.",
                            color=GREEN_COLOR,
                        ),
                        ephemeral=True,
                )

            else:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Kick Failed",
                            description="The player could not be kicked successfully.",
                            color=BLANK_COLOR,
                        ),
                        ephemeral=True,
                    )
            
        async def ban_player_callback(interaction: discord.Interaction, button: discord.ui.Button):
            if disable_online_buttons:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Player Offline",
                            description="This player is currently offline, and cannot be banned.",
                            color=BLANK_COLOR,
                        ),
                        ephemeral=True,
                    )
            if not await admin_check(self.bot, ctx.guild, ctx.author):
                return await interaction.response.send_message(
                    embed=discord.Embed(
                        title="Insufficient Permissions",
                        description="You do not have permission to ban players.",
                        color=BLANK_COLOR,
                    ),
                    ephemeral=True,
                )

            command_response = self.bot.prc_api.run_command(
                ctx.guild.id, (command := f":ban {roblox_player.id}")
            )
            await self.secure_logging(
                ctx.guild.id, ctx.author.id, "Command", command
            )

            if command_response[0] == 200:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title=f"{self.bot.emoji_controller.get_emoji('success')} Player Banned",
                            description=f"The player {roblox_player.name} has been banned successfully.",
                            color=GREEN_COLOR,
                        ),
                        ephemeral=True,
                )
            else:
                return await interaction.response.send_message(
                        embed=discord.Embed(
                            title="Ban Failed",
                            description="The player could not be banned successfully.",
                            color=BLANK_COLOR,
                        ),
                        ephemeral=True,
                    )
        

        class PanelContainer(discord.ui.Container):

            section = discord.ui.Section(
                accessory=discord.ui.Thumbnail(
                    media=thumbnails[0].image_url if thumbnails else None
             )
            ).add_item(f"## {roblox_player.name}\n### User Information\n> **Username:** `{roblox_player.name}`\n> **User ID:** `{roblox_player.id}`\n> **Permission:** {player_permission}\n{'> **Team:** {}{}{}'.format(erlc_player.team, newline, '> **Callsign:** `{}`'.format(erlc_player.callsign) if erlc_player.callsign else '') if erlc_player else ''}")

            if len(matching_player_logs) > 0:
                section.add_item(
                    f"### Timeline Information\n" + '\n'.join([f"> {'Joined' if log.type == 'join' else 'Left'} at <t:{log.timestamp}:F>" for log in matching_player_logs]))
            else:
                section.add_item("### Timeline Information\n> No activity logs found for this player.")
            
            if len(vehicle_information) > 0:
                section.add_item(
                    f"### Vehicle Information\n> **Vehicle:** {vehicle_information[0].vehicle}\n> **Livery:** {vehicle_information[0].texture}"
                )
            else:
                section.add_item("### Vehicle Information\n> No active vehicle found for this player.")

            log_actions = discord.ui.ActionRow(
                CustomExecutionButton(ctx.author.id, label="View Kills", style=discord.ButtonStyle.gray, func=view_kills_callback),
                CustomExecutionButton(ctx.author.id, label="View Commands", style=discord.ButtonStyle.gray, func=view_commands_callback),
                CustomExecutionButton(ctx.author.id, label="View Modcalls", style=discord.ButtonStyle.gray, func=view_modcalls_callback),
            )

            active_actions = discord.ui.ActionRow(
                CustomExecutionButton(ctx.author.id, label="Refresh Player", style=discord.ButtonStyle.gray, disabled=disable_online_buttons, func=refresh_player_callback),
                CustomExecutionButton(ctx.author.id, label="Respawn Player", style=discord.ButtonStyle.gray, disabled=disable_online_buttons, func=respawn_player_callback),
                CustomExecutionButton(ctx.author.id, label="PM Player", style=discord.ButtonStyle.gray, disabled=disable_online_buttons, func=pm_player_callback),
                CustomExecutionButton(ctx.author.id, label="Teleport To Player", style=discord.ButtonStyle.gray, disabled=disable_online_buttons, func=teleport_to_callback),
            )

            destructive_actions = discord.ui.ActionRow(
                CustomExecutionButton(ctx.author.id, label="Kick Player", style=discord.ButtonStyle.red, disabled=disable_online_buttons, func=kick_player_callback),
                CustomExecutionButton(ctx.author.id, label="Ban Player", style=discord.ButtonStyle.red, func=ban_player_callback), # bans can be done offline
            )

        class TestView(discord.ui.LayoutView):
            container = PanelContainer(id=1)

        await ctx.send(view=TestView(timeout=None))
    

    @server.command(
        name="modcalls",
        description="View all modcalls in your ER:LC server!",
    )
    @is_server_linked()
    @is_staff()
    @app_commands.describe(
        filter="Filter the modcalls by a specific username or user ID."
    )
    async def erlc_modcalls(self, ctx: commands.Context, filter: typing.Optional[str] = None):
        guild_id = ctx.guild.id
        modcalls = await self.bot.prc_api.get_mod_calls(guild_id)

        if not modcalls:
            return await ctx.send(
                embed=discord.Embed(
                    title="No Modcalls Found",
                    description="There are no modcalls in this server.",
                    color=BLANK_COLOR,
                )
            )

        embed = discord.Embed(
            title="Moderator Calls", color=BLANK_COLOR, description=""
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon or "")
        pages = []
        for call in modcalls:
            val = f"> Caller: [{call.caller_username}](https://roblox.com/users/{call.caller_id}/profile) • Moderator: {'[{}](https://roblox.com/users/{}/profile)'.format(call.moderator_username, call.moderator_id) if call.moderator_id else 'n/a'} • <t:{call.timestamp}:t>\n"
            if filter and (filter.lower() in val.lower()):
                embed.description += val
            elif not filter:
                embed.description += val
            if len(embed.description) > 2000:
                pages.append(CustomPage(embeds=[embed], identifier=str(len(pages) + 1)))
                embed = discord.Embed(
                    title="Moderator Calls", color=BLANK_COLOR, description=""
                )
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon or "")
        
        if len(pages) == 0:
            if embed.description == "":
                embed.description = "> No modcalls found."
            await ctx.send(embed=embed)
            return
    
        paginator = SelectPagination(self.bot, ctx.author.id, pages)
        await ctx.send(
            embed=pages[0].embeds[0],
            view=paginator.get_current_view(),
        )
        
    @server.command(
        name="permissions",
        description="View the permissions of players in your ER:LC server!",
        aliases=["perm", "playerpermissions", "playerperms"],
    )
    @is_server_linked()
    @is_staff()
    @app_commands.describe(
        filter="Filter the permissions by a specific role, username or user ID."
    )
    async def erlc_permissions(self, ctx: commands.Context, filter: typing.Optional[str] = None):
        # use SelectPagination - sort by Server Co-Owner, Server Administrator, Server Moderator
        pages = []
        server_staff = await self.bot.prc_api.get_server_staff(ctx.guild.id)
        embed = discord.Embed(
            title="Server Permissions", color=BLANK_COLOR, description=""
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon or "")
        for item in server_staff:
            val = f"> [{item.username}](https://roblox.com/users/{item.id}/profile) - {item.permission}\n"
            if filter and filter.lower() in val.lower():
                embed.description += val
            elif not filter:
                embed.description += val
            if len(embed.description) > 1000:
                pages.append(CustomPage(embeds=[embed], identifier=str(len(pages) + 1)))
                embed = discord.Embed(
                    title="Server Permissions", color=BLANK_COLOR, description=""
                )
                embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon or "")
            
        if len(pages) == 0:
            if embed.description == "":
                embed.description = "> No permissions found."
            await ctx.send(
                embed=embed
            )
            return

        paginator = SelectPagination(self.bot, ctx.author.id, pages)
        await ctx.send(
            embed=pages[0].embeds[0],
            view=paginator.get_current_view(),
        )
    
    @server.command(
        name="pm",
        description="Send a PM to players in your ER:LC server!",
        aliases=["private", "sendpm", "send"],
    )
    @app_commands.autocomplete(target=erlc_group_autocomplete)
    @app_commands.describe(
        target="Who would you like to send this message to?",
        message="What would you like to send?",
    )
    @is_staff()
    async def erlc_pm(self, ctx: commands.Context, target: str, *, message: str):
        guild_id = ctx.guild.id
        special_selections = ["moderators", "admins", "players", "staff"]
        selected = []
        if target in special_selections:
            players = await self.bot.prc_api.get_server_players(guild_id)
            for item in players:
                if item.permission == "Normal" and target.lower() == "players":
                    selected.append(item.username)
                elif item.permission != "Normal" and target.lower() == "staff":
                    selected.append(item.username)
                elif (
                    item.permission == "Server Moderator"
                    and target.lower() == "moderators"
                ):
                    selected.append(item.username)
                elif (
                    item.permission == "Server Administrator"
                    and target.lower() == "admins"
                ):
                    selected.append(item.username)
        else:
            selected = [target]

        command_response = await self.bot.prc_api.run_command(
            guild_id, f":pm {','.join(selected)} {message}"
        )
        if command_response[0] == 200:
            await ctx.send(
                embed=discord.Embed(
                    title="<:success:1163149118366040106> Successfully Sent",
                    description="This PM has been sent to the server!",
                    color=GREEN_COLOR,
                )
            )
            await self.secure_logging(
                guild_id, ctx.author.id, "Private Message", message
            )
        else:
            await ctx.send(
                embed=discord.Embed(
                    title="Not Executed",
                    description="This PM has not been sent to the server successfully.",
                    color=BLANK_COLOR,
                )
            )
            await self.secure_logging(
                guild_id, ctx.author.id, "Private Message", message
            )

    @server.command(
        name="message", description="Send a Message to your ER:LC server with ERM!"
    )
    @is_staff()
    @is_server_linked()
    async def erlc_message(self, ctx: commands.Context, *, message: str):
        guild_id = ctx.guild.id

        command_response = await self.bot.prc_api.run_command(guild_id, f":m {message}")
        if command_response[0] == 200:
            await ctx.send(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Successfully Sent",
                    description="This message has been sent to the server!",
                    color=GREEN_COLOR,
                )
            )
            await self.secure_logging(guild_id, ctx.author.id, "Message", message)
        else:
            await ctx.send(
                embed=discord.Embed(
                    title="Not Executed",
                    description="This message has not been sent to the server successfully.",
                    color=BLANK_COLOR,
                )
            )
            await self.secure_logging(guild_id, ctx.author.id, "Message", message)

    @server.command(
        name="hint", description="Send a Hint to your ER:LC server with ERM!"
    )
    @is_staff()
    @is_server_linked()
    async def erlc_hint(self, ctx: commands.Context, *, hint: str):
        guild_id = ctx.guild.id

        await self.secure_logging(guild_id, ctx.author.id, "Hint", hint)

        command_response = await self.bot.prc_api.run_command(guild_id, f":h {hint}")
        if command_response[0] == 200:
            return await ctx.send(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Successfully Sent",
                    description="This Hint has been sent to the server!",
                    color=GREEN_COLOR,
                )
            )
        else:
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Executed",
                    description="This Hint has not been sent to the server successfully.",
                    color=BLANK_COLOR,
                )
            )

    @server.command(
        name="link",
        description="Link your ER:LC server with ERM!",
        extras={"ignoreDefer": True},
    )
    @is_management()
    @app_commands.describe(
        key="Your PRC Server Key - check your server settings for details"
    )
    async def server_link(self, ctx: commands.Context, key: str):
        await log_command_usage(self.bot, ctx.guild, ctx.author, f"ER:LC Link")
        status: int | ServerStatus = await self.bot.prc_api.send_test_request(key)
        if isinstance(status, int):
            await (
                ctx.send
                if not ctx.interaction
                else ctx.interaction.response.send_message
            )(
                embed=discord.Embed(
                    title="Incorrect Key",
                    description="This Server Key is invalid and nonfunctional. Ensure you've entered it correctly.",
                    color=BLANK_COLOR,
                ),
                ephemeral=True,
            )
        else:
            await self.bot.server_keys.upsert({"_id": ctx.guild.id, "key": key})

            await (
                ctx.send
                if not ctx.interaction
                else ctx.interaction.response.send_message
            )(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Successfully Changed",
                    description="I have changed the Server Key successfully. You can now run ER:LC commands on your server.",
                    color=GREEN_COLOR,
                ),
                ephemeral=True,
            )

    @server.command(
        name="unlink",
        description="Unlink your ER:LC server from ERM!",
    )
    @is_management()
    @is_server_linked()
    async def server_unlink(self, ctx: commands.Context):
        await log_command_usage(self.bot, ctx.guild, ctx.author, f"ER:LC Unlink")
        await self.bot.server_keys.delete_one({"_id": ctx.guild.id})
        await ctx.send(
            embed=discord.Embed(
                title=f"{self.bot.emoji_controller.get_emoji('success')} Successfully Unlinked",
                description="I have unlinked your ER:LC server from ERM.",
                color=GREEN_COLOR,
            )
        )

    @server.command(
        name="command",
        description='Send a direct command to your ER:LC server, under "Remote Server Management"',
        extras={"ephemeral": True},
    )
    @app_commands.describe(command="The command to send to your ER:LC server")
    @is_management()
    @is_server_linked()
    async def server_send_command(self, ctx: commands.Context, *, command: str):
        if command[0] != ":":
            command = ":" + command
        elevated_privileges = None
        status: ServerStatus = await self.bot.prc_api.get_server_status(ctx.guild.id)
        for item in status.co_owner_ids + [status.owner_id]:
            if int(item) == int(
                (await self.bot.bloxlink.find_roblox(ctx.author.id) or {}).get(
                    "robloxID"
                )
                or 0
            ):
                elevated_privileges = True
                break
        else:
            elevated_privileges = False

        if (
            any([i in command for i in [":admin", ":unadmin"]])
            and not elevated_privileges
        ):
            # REQUIRES ELEVATION
            if (
                (await self.bot.settings.find_by_id(ctx.guild.id) or {}).get("ERLC", {})
                or {}
            ).get("elevation_required", True):
                await self.secure_logging(
                    ctx.guild.id, ctx.author.id, "Command", command, True
                )
                if ctx.interaction:
                    await ctx.interaction.followup.send(
                        embed=discord.Embed(
                            title="Not Authorized",
                            description="This command is privileged and requires special elevation.",
                            color=BLANK_COLOR,
                        ),
                        ephemeral=True,
                    )
                else:
                    await ctx.send(
                        embed=discord.Embed(
                            title="Not Authorized",
                            description="This command is privileged and requires special elevation.",
                            color=BLANK_COLOR,
                        )
                    )
                return

        guild_id = int(ctx.guild.id)
        command_response = await self.bot.prc_api.run_command(guild_id, command)
        if command_response[0] == 200:
            await ctx.send(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Successfully Ran",
                    description="This command should have now been executed in your server.",
                    color=GREEN_COLOR,
                )
            )
            await self.secure_logging(
                int(ctx.guild.id), ctx.author.id, "Command", command
            )
        else:
            await ctx.send(
                embed=discord.Embed(
                    title=f"Not Executed ({command_response[0]})",
                    description="This command has not been sent to the server successfully.",
                    color=BLANK_COLOR,
                )
            )
            await self.secure_logging(
                int(ctx.guild.id), ctx.author.id, "Command", command
            )

    @server.command(
        name="info",
        description="Get information about the current players in your ER:LC server.",
    )
    @is_server_linked()
    async def server_info(self, ctx: commands.Context):
        guild_id = ctx.guild.id

        async def operate_and_reload_serverinfo(
            msg: discord.Message | None, guild_id: str
        ):
            guild_id = int(guild_id)
            status: ServerStatus = await self.bot.prc_api.get_server_status(guild_id)
            players: list[Player] = await self.bot.prc_api.get_server_players(guild_id)
            queue: int = await self.bot.prc_api.get_server_queue(
                guild_id, minimal=True
            )  # this only returns the count
            client = roblox.Client()

            embed1 = discord.Embed(title=f"{status.name}", color=BLANK_COLOR)
            embed1.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
            embed1.add_field(
                name="Basic Info",
                value=(
                    f"> **Join Code:** [{status.join_key}](https://policeroleplay.community/join/{status.join_key})\n"
                    f"> **Current Players:** {status.current_players}/{status.max_players}\n"
                    f"> **Queue:** {queue}\n"
                ),
                inline=False,
            )
            embed1.add_field(
                name="Server Ownership",
                value=(
                    f"> **Owner:** [{(await client.get_user(status.owner_id)).name}](https://roblox.com/users/{status.owner_id}/profile)\n"
                    f"> **Co-Owners:** {f', '.join([f'[{user.name}](https://roblox.com/users/{user.id}/profile)' for user in await client.get_users(status.co_owner_ids, expand=False)])}"
                ),
                inline=False,
            )

            embed1.add_field(
                name="Staff Statistics",
                value=(
                    f"> **Moderators:** {len(list(filter(lambda x: x.permission == 'Server Moderator', players)))}\n"
                    f"> **Administrators:** {len(list(filter(lambda x: x.permission == 'Server Administrator', players)))}\n"
                    f"> **Staff In-Game:** {len(list(filter(lambda x: x.permission != 'Normal', players)))}\n"
                    f"> **Staff Clocked In:** {await self.bot.shift_management.shifts.db.count_documents({'Guild': guild_id, 'EndEpoch': 0})}"
                ),
                inline=False,
            )

            if msg is None:
                view = ReloadView(
                    self.bot,
                    ctx.author.id,
                    operate_and_reload_serverinfo,
                    [None, guild_id],
                )
                msg = await ctx.send(embed=embed1, view=view)
                view.message = msg
                view.callback_args[0] = msg
            else:
                await msg.edit(embed=embed1)

        await operate_and_reload_serverinfo(None, guild_id)

    @server.command(
        name="staff", description="See the online staff members in your ER:LC server!"
    )
    @is_staff()
    @is_server_linked()
    async def server_staff(self, ctx: commands.Context):
        guild_id = int(ctx.guild.id)
        status: ServerStatus = await self.bot.prc_api.get_server_status(guild_id)
        players: list[Player] = await self.bot.prc_api.get_server_players(guild_id)
        embed2 = discord.Embed(color=BLANK_COLOR)
        embed2.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
        actual_players = []
        key_maps = {}
        for item in players:
            if item.permission == "Normal":
                actual_players.append(item)
            else:
                if item.permission not in key_maps:
                    key_maps[item.permission] = [item]
                else:
                    key_maps[item.permission].append(item)

        new_maps = ["Server Owners", "Server Administrator", "Server Moderator"]
        new_vals = [
            key_maps.get("Server Owner", []) + key_maps.get("Server Co-Owner", []),
            key_maps.get("Server Administrator", []),
            key_maps.get("Server Moderator", []),
        ]
        new_keymap = dict(zip(new_maps, new_vals))
        embed2.title = f"Online Staff Members [{sum([len(i) for i in new_vals])}]"
        for key, value in new_keymap.items():
            if value:
                value_length = len(value)
                value = "\n".join(
                    [
                        f"[{plr.username}](https://roblox.com/users/{plr.id}/profile)"
                        for plr in value
                    ]
                )
                embed2.add_field(
                    name=f"{key} [{value_length}]", value=value, inline=False
                )

        if len(embed2.fields) == 0:
            embed2.description = "> There are no online staff members."
        await ctx.send(embed=embed2)

    @server.command(name="kills", description="See the Kill Logs of your server.")
    @is_staff()
    @is_server_linked()
    async def kills(self, ctx: commands.Context):
        guild_id = ctx.guild.id

        async def operate_and_reload_kills(msg, guild_id: str):
            guild_id = int(guild_id)
            # status: ServerStatus = await self.bot.prc_api.get_server_status(guild_id)
            kill_logs: list[KillLog] = await self.bot.prc_api.fetch_kill_logs(guild_id)
            embed = discord.Embed(
                color=BLANK_COLOR, title="Server Kill Logs", description=""
            )

            sorted_kill_logs = sorted(
                kill_logs, key=lambda log: log.timestamp, reverse=True
            )
            for log in sorted_kill_logs:
                if len(embed.description) > 3800:
                    break
                embed.description += f"> [{log.killer_username}](https://roblox.com/users/{log.killer_user_id}/profile) killed [{log.killed_username}](https://roblox.com/users/{log.killed_user_id}/profile) • <t:{int(log.timestamp)}:R>\n"

            if embed.description in ["", "\n"]:
                embed.description = "> No kill logs found."

            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

            # embed.set_footer(icon_url="https://cdn.discordapp.com/emojis/1176999148084535326.webp?size=128&quality=lossless",
            #                   text="Last updated 5 seconds ago")
            if msg is None:
                view = ReloadView(
                    self.bot, ctx.author.id, operate_and_reload_kills, [None, guild_id]
                )
                msg = await ctx.send(embed=embed, view=view)
                view.message = msg
                view.callback_args[0] = msg
            else:
                await msg.edit(embed=embed)

        await operate_and_reload_kills(None, guild_id)

    @server.command(
        name="playerlogs", description="See the Join and Leave logs of your server."
    )
    @is_staff()
    @is_server_linked()
    async def playerlogs(self, ctx: commands.Context):
        guild_id = ctx.guild.id

        async def operate_and_reload_playerlogs(msg, guild_id: str):
            guild_id = int(guild_id)
            # status: ServerStatus = await self.bot.prc_api.get_server_status(guild_id)
            player_logs: list[JoinLeaveLog] = await self.bot.prc_api.fetch_player_logs(
                guild_id
            )
            embed = discord.Embed(
                color=BLANK_COLOR, title="Player Join/Leave Logs", description=""
            )

            sorted_logs = sorted(
                player_logs, key=lambda log: log.timestamp, reverse=True
            )
            for log in sorted_logs:
                if len(embed.description) > 3800:
                    break
                embed.description += f"> [{log.username}](https://roblox.com/users/{log.user_id}/profile) {'joined the server' if log.type == 'join' else 'left the server'} • <t:{int(log.timestamp)}:R>\n"

            if embed.description in ["", "\n"]:
                embed.description = "> No player logs found."

            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

            # embed.set_footer(icon_url="https://cdn.discordapp.com/emojis/1176999148084535326.webp?size=128&quality=lossless",
            #                   text="Last updated 5 seconds ago")
            if msg is None:
                view = ReloadView(
                    self.bot,
                    ctx.author.id,
                    operate_and_reload_playerlogs,
                    [None, guild_id],
                )
                msg = await ctx.send(embed=embed, view=view)
                view.message = msg
                view.callback_args[0] = msg
            else:
                await msg.edit(embed=embed)

        await operate_and_reload_playerlogs(None, guild_id)

    @server.command(name="logs", description="See the Command Logs of your server.")
    @is_staff()
    @is_server_linked()
    async def commandlogs(self, ctx: commands.Context):
        guild_id = ctx.guild.id

        async def operate_and_reload_commandlogs(msg, guild_id: str):
            guild_id = int(guild_id)
            # status: ServerStatus = await self.bot.prc_api.get_server_status(guild_id)
            command_logs: list[CommandLog] = await self.bot.prc_api.fetch_server_logs(
                guild_id
            )
            embed = discord.Embed(
                color=BLANK_COLOR, title="Command Logs", description=""
            )

            sorted_logs = sorted(
                command_logs, key=lambda log: log.timestamp, reverse=True
            )
            for log in sorted_logs:
                if len(embed.description) > 3800:
                    break
                embed.description += f"> [{log.username}](https://roblox.com/users/{log.user_id}/profile) ran the command `{log.command}` • <t:{int(log.timestamp)}:R>\n"

            if embed.description in ["", "\n"]:
                embed.description = "> No player logs found."

            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

            # embed.set_footer(icon_url="https://cdn.discordapp.com/emojis/1176999148084535326.webp?size=128&quality=lossless",
            #                   text="Last updated 5 seconds ago")
            if msg is None:
                view = ReloadView(
                    self.bot,
                    ctx.author.id,
                    operate_and_reload_commandlogs,
                    [None, guild_id],
                )
                msg = await ctx.send(embed=embed, view=view)
                view.message = msg
                view.callback_args[0] = msg
            else:
                await msg.edit(embed=embed)

        await operate_and_reload_commandlogs(None, guild_id)

    @server.command(name="bans", description="Filter the bans of your server.")
    @is_staff()
    @is_server_linked()
    async def bans(
        self,
        ctx: commands.Context,
        username: typing.Optional[str],
        user_id: typing.Optional[int],
    ):
        guild_id = ctx.guild.id
        # status: ServerStatus = await self.bot.prc_api.get_server_status(guild_id)
        try:
            bans: list[prc_api.BanItem] = await self.bot.prc_api.fetch_bans(guild_id)
        except prc_api.ResponseFailure:
            return await ctx.send(
                embed=discord.Embed(
                    title="PRC API Error",
                    description="There were no bans, or your API key is incorrect.",
                    color=BLANK_COLOR,
                )
            )
        embed = discord.Embed(color=BLANK_COLOR, title="Bans", description="")
        status = username or user_id

        if not username and user_id:
            username = "[PLACEHOLDER]"

        if not user_id and username:
            user_id = "99999"
        old_embed = copy.copy(embed)
        embeds = [embed]
        for log in bans:
            if str(username or "") in str(log.username).lower() or str(
                user_id or ""
            ) in str(log.user_id):
                embed = embeds[-1]
                if len(embed.description) > 3800:
                    new = copy.copy(old_embed)
                    embeds.append(new)
                embeds[
                    -1
                ].description += f"> [{log.username}:{log.user_id}](https://roblox.com/users/{log.user_id}/profile)\n"

        if embeds[0].description in ["", "\n"]:
            embeds[0].description = (
                "> This ban was not found."
                if status
                else "> Bans were not found in your server."
            )

        embeds[0].set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

        if len(embeds) > 1:
            pages = [
                CustomPage(embeds=[embeds[i]], identifier=str(i + 1))
                for i in range(0, len(embeds) - 1)
            ]
            paginator = SelectPagination(self.bot, ctx.author.id, pages)
            await ctx.send(embed=embeds[0], view=paginator.get_current_view())
            return
        else:
            await ctx.send(embed=embeds[0])
            
    @server.command(name="players", description="See all players in the server.")
    @is_server_linked()
    async def server_players(
        self, ctx: commands.Context, filter: typing.Optional[str] = None
    ):
        guild_id = int(ctx.guild.id)
        # status: ServerStatus = await self.bot.prc_api.get_server_status(guild_id)
        players: list[Player] = await self.bot.prc_api.get_server_players(guild_id)
        queue: list[Player] = await self.bot.prc_api.get_server_queue(guild_id)
        embed2 = discord.Embed(
            title=f"Server Players [{len(players)}]", color=BLANK_COLOR, description=""
        )
        actual_players = []
        key_maps = {}
        staff = []
        for item in players:
            if item.permission == "Normal":
                actual_players.append(item)
            else:
                staff.append(item)

        if filter not in [None, ""]:
            actual_players_copy = []
            for item in actual_players:
                if item.username.lower().startswith(filter.lower()):
                    actual_players_copy.append(item)
            actual_players = actual_players_copy
            staff_copy = []
            for item in staff:
                if item.username.lower().startswith(filter.lower()):
                    staff_copy.append(item)
            staff = staff_copy

        embed2.description += f"**Server Staff [{len(staff)}]**\n" + (
            ", ".join(
                [
                    f"[{plr.username} ({plr.team})](https://roblox.com/users/{plr.id}/profile)"
                    for plr in staff
                ]
            )
            or "> No players in this category."
        )

        embed2.description += f"\n\n**Online Players [{len(actual_players)}]**\n" + (
            ", ".join(
                [
                    f"[{plr.username} ({plr.team})](https://roblox.com/users/{plr.id}/profile)"
                    for plr in actual_players
                ]
            )
            or "> No players in this category."
        )

        embed2.description += f"\n\n**Queue [{len(queue)}]**\n" + (
            ", ".join(
                [
                    f"[{plr.username}](https://roblox.com/users/{plr.id}/profile)"
                    for plr in queue
                ]
            )
            or "> No players in this category."
        )

        embed2.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
        if len(embed2.description) > 3999:
            embed2.description = ""
            embed2.description += f"**Server Staff [{len(staff)}]**\n" + ", ".join(
                [f"{plr.username} ({plr.team})" for plr in staff]
            )

            embed2.description += (
                f"\n\n**Online Players [{len(actual_players)}]**\n"
                + ", ".join([f"{plr.username} ({plr.team})" for plr in actual_players])
            )

            embed2.description += f"\n\n**Queue [{len(queue)}]**\n" + ", ".join(
                [f"{plr.username}" for plr in queue]
            )

        await ctx.send(embed=embed2)

    @server.command(
        name="teams", description="See all players in the server, grouped by team."
    )
    @is_staff()
    @is_server_linked()
    async def server_teams(
        self, ctx: commands.Context, filter: typing.Optional[str] = None
    ):
        guild_id = int(ctx.guild.id)
        players: list[Player] = await self.bot.prc_api.get_server_players(guild_id)
        embed2 = discord.Embed(
            title=f"Server Players by Team [{len(players)}]",
            color=BLANK_COLOR,
            description="",
        )

        teams = {}
        for plr in players:
            if filter and not plr.username.lower().startswith(filter.lower()):
                continue
            if plr.team not in teams:
                teams[plr.team] = []
            teams[plr.team].append(plr)

        team_order = ["Police", "Sheriff", "Fire", "DOT", "Civilian"]
        for team in team_order:
            team_players = []
            if team in teams:
                team_players = teams[team]
            embed2.description += (
                f"**{team} [{len(team_players)}]**\n"
                + ", ".join(
                    [
                        f"[{plr.username}](https://roblox.com/users/{plr.id}/profile)"
                        for plr in team_players
                    ]
                )
                + "\n\n"
            )
        if embed2.description.strip() == "":
            embed2.description = "> There are no players in-game."

        embed2.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)

        if len(embed2.description) > 3999:
            embed2.description = "> The list is too long to display."

        await ctx.send(embed=embed2)

    @server.command(
        name="vehicles", description="See all vehicles of players in the server."
    )
    @is_staff()
    @is_server_linked()
    async def server_vehicles(self, ctx: commands.Context):
        guild_id = int(ctx.guild.id)
        players: list[Player] = await self.bot.prc_api.get_server_players(guild_id)
        vehicles: list[prc_api.ActiveVehicle] = (
            await self.bot.prc_api.get_server_vehicles(guild_id)
        )

        if len(vehicles) <= 0:
            emb = discord.Embed(
                title=f"Server Vehicles [{len(vehicles)}/{len(players)}]",
                description="> There are no active vehicles in your server.",
                color=BLANK_COLOR,
            )
            emb.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url)
            return ctx.send(embed=emb)

        matched = {}
        for item in vehicles:
            for x in players:
                if x.username == item.username:
                    matched[item] = x

        actual_players = []
        staff = []
        for item in players:
            if item.permission == "Normal":
                actual_players.append(item)
            else:
                staff.append(item)

        descriptions = []
        description = ""
        for index, (veh, plr) in enumerate(matched.items()):
            description += f"[{plr.username}](https://roblox.com/users/{plr.id}/profile) - {veh.vehicle} **({veh.texture})**\n"
            if (index + 1) % 10 == 0 or (index + 1) == len(matched):
                descriptions.append(description)
                description = ""

        if not descriptions:
            descriptions.append("> There are no active vehicles in your server.")

        pages = []
        for index, description in enumerate(descriptions):
            embed = discord.Embed(
                title=f"Server Vehicles [{len(vehicles)}/{len(players)}]",
                color=BLANK_COLOR,
                description=description,
            )
            embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url)

            page = CustomPage(embeds=[embed], identifier=embed.title, view=None)
            pages.append(page)

        paginator = SelectPagination(self.bot, ctx.author.id, pages)
        await ctx.send(embeds=pages[0].embeds, view=paginator.get_current_view())

    @server.command(
        name="check",
        description="Perform a Discord check on your server to see if all players are in the Discord server.",
    )
    @is_staff()
    @is_server_linked()
    async def check(self, ctx: commands.Context):
        msg = await ctx.send(
            embed=discord.Embed(
                title=f"{self.bot.emoji_controller.get_emoji('Clock')} Checking...",
                description="This may take a while.",
                color=BLANK_COLOR,
            )
        )
        guild_id = ctx.guild.id
        try:
            players: list[Player] = await self.bot.prc_api.get_server_players(guild_id)
        except ResponseFailure:
            return await msg.edit(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('WarningIcon')} PRC API Error",
                    description="There was an error fetching players from the PRC API.",
                    color=BLANK_COLOR,
                )
            )

        if not players:
            return await msg.edit(
                embed=discord.Embed(
                    title="No Players Found",
                    description="There are no players in the server to check.",
                    color=BLANK_COLOR,
                )
            )

        embed = discord.Embed(
            title="Players in ER:LC Not in Discord", color=BLANK_COLOR, description=""
        )

        for player in players:
            pattern = re.compile(re.escape(player.username), re.IGNORECASE)
            member_found = False

            for member in ctx.guild.members:
                if (
                    pattern.search(member.name)
                    or pattern.search(member.display_name)
                    or (
                        hasattr(member, "global_name")
                        and member.global_name
                        and pattern.search(member.global_name)
                    )
                ):
                    member_found = True
                    break

            if not member_found:
                try:
                    discord_id = await get_discord_by_roblox(self.bot, player.username)
                    if discord_id:
                        member = ctx.guild.get_member(discord_id)
                        if member:
                            member_found = True
                except discord.HTTPException:
                    pass

            if not member_found:
                embed.description += f"> [{player.username}](https://roblox.com/users/{player.id}/profile)\n"

        if embed.description == "":
            embed.description = "> All players are in the Discord server."

        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
        await msg.edit(embed=embed)

    @server.command(
        name="refresh", description="Refresh the author in the ER:LC server."
    )
    @is_server_linked()
    async def refresh(self, ctx: commands.Context):
        settings = await self.bot.settings.find_by_id(ctx.guild.id) or {}
        erlc_settings = settings.get("ERLC", {})
        if not erlc_settings.get("allow_player_refresh", False):
            return await ctx.send(
                embed=discord.Embed(
                    title="Not Enabled",
                    description="Player refresh is not enabled in this server.",
                    color=BLANK_COLOR,
                )
            )

        user = ctx.author

        guild_id = ctx.guild.id
        roblox_user = await self.bot.bloxlink.find_roblox(user.id)
        if not roblox_user or not (roblox_user or {}).get("robloxID"):
            return await ctx.send(
                embed=discord.Embed(
                    title="Could not find user",
                    description="I couldn't find your ROBLOX user. Please make sure that you're verified with Bloxlink.",
                    color=BLANK_COLOR,
                )
            )

        roblox_info = await self.bot.bloxlink.get_roblox_info(roblox_user["robloxID"])
        username = roblox_info.get("name")

        if not username:
            return await ctx.send(
                embed=discord.Embed(
                    title="Could not find username",
                    description="I could not find this user's ROBLOX username.",
                    color=BLANK_COLOR,
                )
            )

        client = roblox.Client()
        roblox_player = await client.get_user_by_username(username)
        thumbnails = await client.thumbnails.get_user_avatar_thumbnails(
            [roblox_player], type=AvatarThumbnailType.headshot
        )
        thumbnail_url = thumbnails[0].image_url

        embed = discord.Embed(
            title="Confirm Refresh",
            description=f"Is this your account? If not, be sure to set a new primary account with Bloxlink.",
            color=BLANK_COLOR,
        )
        embed.set_thumbnail(url=thumbnail_url)
        embed.add_field(
            name="Account Information",
            value=(
                f"> **Username:** {username}\n"
                f"> **User ID:** {roblox_user['robloxID']}\n"
                f"> **Discord:** {user.mention}\n"
            ),
        )

        view = RefreshConfirmation(ctx.author.id)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

        await view.wait()
        if not view.value:
            return await msg.edit(
                embed=discord.Embed(
                    title="Cancelled",
                    description="Refresh has been cancelled.",
                    color=BLANK_COLOR,
                ),
                view=None,
            )

        command_response = await self.bot.prc_api.run_command(
            guild_id, f":refresh {username}"
        )
        if command_response[0] == 200:
            await msg.edit(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Successfully Refreshed",
                    description=f"Successfully refreshed {username} in-game.",
                    color=GREEN_COLOR,
                ),
                view=None,
            )
        else:
            await msg.edit(
                embed=discord.Embed(
                    title=f"Not Executed ({command_response[0]})",
                    description="This command has not been sent to the server successfully.",
                    color=BLANK_COLOR,
                ),
                view=None,
            )


async def setup(bot):
    await bot.add_cog(ERLC(bot))
