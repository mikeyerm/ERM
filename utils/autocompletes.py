import typing

import aiohttp
import discord
import roblox
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context
import utils.prc_api
from erm import Bot


async def shift_type_autocomplete(
    interaction: discord.Interaction, _: str
) -> typing.List[app_commands.Choice[str]]:
    bot = interaction.client

    data = await bot.settings.find_by_id(interaction.guild.id)
    if not data:
        return [app_commands.Choice(name="Default", value="Default")]
    shift_types_settings = data.get("shift_types", {})
    types = shift_types_settings.get("types", [])

    if types is not None and len(types or []) != 0:
        return [
            app_commands.Choice(name=shift_type["name"], value=shift_type["name"])
            for shift_type in types
        ]
    else:
        return [app_commands.Choice(name="Default", value="Default")]


async def erlc_players_autocomplete(
   interaction: discord.Interaction, incomplete: str
) -> typing.List[app_commands.Choice[str]]:
    bot: Bot = (await Context.from_interaction(interaction)).bot
    defaults = []
    try:
        data = await bot.prc_api.get_server_players(interaction.guild.id)
    except utils.prc_api.ResponseFailure:
        return defaults

    for player in data:
        if len(incomplete) > 2:
            if incomplete.lower() in player.username:
                defaults.append(
                    discord.app_commands.Choice(
                        name=player.username, value=player.username
                    )
                )
                continue
            else:
                continue
        defaults.append(
            discord.app_commands.Choice(name=player.username, value=player.username)
        )

    return defaults

async def erlc_group_autocomplete(
    interaction: discord.Interaction, incomplete: str
) -> typing.List[app_commands.Choice[str]]:
    bot: Bot = (await Context.from_interaction(interaction)).bot
    defaults = [
        discord.app_commands.Choice(name="Staff", value="staff"),
        discord.app_commands.Choice(name="Moderators", value="moderators"),
        discord.app_commands.Choice(name="Admins", value="admins"),
        discord.app_commands.Choice(name="Players", value="players"),
    ]
    try:
        data = await bot.prc_api.get_server_players(interaction.guild.id)
    except utils.prc_api.ResponseFailure:
        return defaults

    for player in data:
        if len(incomplete) > 2:
            if incomplete.lower() in player.username:
                defaults.append(
                    discord.app_commands.Choice(
                        name=player.username, value=player.username
                    )
                )
                continue
            else:
                continue
        defaults.append(
            discord.app_commands.Choice(name=player.username, value=player.username)
        )

    return defaults


async def all_shift_type_autocomplete(
    interaction: discord.Interaction, _: str
) -> typing.List[app_commands.Choice[str]]:
    bot = (await Context.from_interaction(interaction)).bot
    data = await bot.settings.find_by_id(interaction.guild.id)
    if not data:
        return [app_commands.Choice(name="Default", value="Default")]
    shift_types_settings = data.get("shift_types", {})
    types = shift_types_settings.get("types", [])

    if types is not None:
        return [
            app_commands.Choice(name=shift_type["name"], value=shift_type["name"])
            for shift_type in (types + [{"name": "All"}])
        ]
    else:
        return [app_commands.Choice(name="Default", value="Default")]


async def action_autocomplete(
    interaction: discord.Interaction, current: str
) -> typing.List[app_commands.Choice[str]]:
    bot = (await Context.from_interaction(interaction)).bot
    actions = [i async for i in bot.actions.db.find({"Guild": interaction.guild.id})]
    if actions in [None, []]:
        return [discord.app_commands.Choice(name="No actions found", value="NULL")]

    action_list = []
    for action in actions:
        if current not in ["", " "]:
            if (
                action["ActionName"].startswith(current)
                or current in action["ActionName"]
                or action["ActionName"].endswith(current)
            ):
                action_list.append(action["ActionName"])
        else:
            action_list.append(action["ActionName"])

    if len(action_list) == 0:
        return [discord.app_commands.Choice(name="No actions found", value="NULL")]

    commandList = []
    for command in action_list:
        commandList.append(discord.app_commands.Choice(name=command, value=command))
    return commandList[:24]


async def command_autocomplete(
    interaction: discord.Interaction, current: str
) -> typing.List[app_commands.Choice[str]]:
    bot = (await Context.from_interaction(interaction)).bot
    Data = await bot.custom_commands.find_by_id(interaction.guild.id)
    if Data is None:
        return [
            discord.app_commands.Choice(name="No custom commands found", value="NULL")
        ]
    else:
        commands = []
        for command in Data["commands"]:
            if current not in ["", " "]:
                if (
                    command["name"].startswith(current)
                    or current in command["name"]
                    or command["name"].endswith(current)
                ):
                    commands.append(command["name"])
            else:
                commands.append(command["name"])
        if len(commands) == 0:
            return [
                discord.app_commands.Choice(
                    name="No custom commands found", value="NULL"
                )
            ]

        # # # print(commands)
        commandList = []
        for command in commands:
            if command not in [""]:
                commandList.append(
                    discord.app_commands.Choice(name=command, value=command)
                )
            else:
                cmd = None
                for c in Data["commands"]:
                    if c["name"].lower() == command.lower():
                        cmd = c
                commandList.append(
                    discord.app_commands.Choice(
                        name=cmd["message"]["content"][:20].replace(" ", "").lower(),
                        value=cmd["name"],
                    )
                )
        return commandList


async def punishment_autocomplete(
    interaction: discord.Interaction, current: str
) -> typing.List[app_commands.Choice[str]]:
    bot = interaction.client
    Data = await bot.punishment_types.find_by_id(interaction.guild.id)
    if Data is None:
        return [
            app_commands.Choice(name=item, value=item)
            for item in ["Warning", "Kick", "Ban", "BOLO"]
        ]
    else:
        ndt = []
        for item in Data["types"]:
            if item not in ["Warning", "Kick", "Ban", "BOLO"]:
                ndt.append(item)
        return [
            app_commands.Choice(
                name=(
                    item_identifier := item if isinstance(item, str) else item["name"]
                ),
                value=item_identifier,
            )
            for item in ndt + ["Warning", "Kick", "Ban", "BOLO"]
        ]


async def user_autocomplete(
    interaction: discord.Interaction, current: str
) -> typing.List[app_commands.Choice[str]]:
    bot = interaction.client

    async def fallback_completion():
        choices = []
        async for search in bot.punishments.db.find({}).limit(10):
            if search["Username"] in [choice.name for choice in choices]:
                continue
            choices.append(
                discord.app_commands.Choice(
                    name=search["Username"], value=search["Username"]
                )
            )
        return choices

    if current in [None, ""]:
        return await fallback_completion()

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://apis.roblox.com/search-api/omni-search?verticalType=user&searchQuery={current}&pageToken=&globalSessionId=8fefd242-5667-42e3-9735-e2044c15b567&sessionId=8fefd242-5667-42e3-9735-e2044c15b567"
        ) as resp:
            data_json = await resp.json()
            if data_json:
                if not data_json.get("searchResults"):
                    items = []
                else:
                    if isinstance(data_json.get("searchResults")[0]["contents"], list):
                        items = [
                            item
                            for item in data_json["searchResults"][0]["contents"][:25]
                        ]
                    else:
                        items = []
            else:
                items = []
    choices = []
    for item in items:
        choices.append(
            discord.app_commands.Choice(
                name=f"{item['displayName']} (@{item['username']})",
                value=item["username"],
            )
        )
    return choices


async def infraction_type_autocomplete(
    interaction: discord.Interaction, current: str
) -> typing.List[app_commands.Choice[str]]:
    """Get all infraction types configured for the server"""
    settings = await interaction.client.settings.find_by_id(interaction.guild.id)
    if not settings or "infractions" not in settings:
        return []

    infraction_types = []
    for infraction in settings["infractions"].get("infractions", []):
        name = infraction.get("name")
        if name:
            infraction_types.append(app_commands.Choice(name=name, value=name))

    return infraction_types[:25]  # Discord limits to max 25 choices
