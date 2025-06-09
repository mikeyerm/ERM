import asyncio
import datetime
import logging
import re
import typing

import aiohttp
import discord
import pytz
import requests
import roblox.users
from discord import Embed, InteractionResponse, Webhook
from discord.ext import commands
from fuzzywuzzy import fuzz
from snowflake import SnowflakeGenerator
from zuid import ZUID

import utils.prc_api as prc_api
from utils.constants import BLANK_COLOR, RED_COLOR
from utils.prc_api import ServerStatus, Player


class ArgumentMockingInstance:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            self.key = value


tokenGenerator = ZUID(
    prefix="",
    length=64,
    timestamped=True,
    charset="0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_",
)

generator = SnowflakeGenerator(192)
error_gen = ZUID(prefix="error_", length=10)
system_code_gen = ZUID(prefix="erm-systems-", length=7)


def removesuffix(input_string: str, suffix: str):
    if suffix and input_string.endswith(suffix):
        return input_string[: -len(suffix)]
    return input_string


def get_guild_icon(
    bot: typing.Union[commands.Bot, commands.AutoShardedBot], guild: discord.Guild
):
    if guild.icon is None:
        return bot.user.display_avatar.url
    else:
        return guild.icon.url


async def generalised_interaction_check_failure(
    responder: InteractionResponse | Webhook | typing.Callable,
):
    if isinstance(responder, typing.Callable):
        responder = responder()

    if isinstance(responder, InteractionResponse):
        await responder.send_message(
            embed=discord.Embed(
                title="Not Permitted",
                description="You are not permitted to interact with these buttons.",
                color=BLANK_COLOR,
            ),
            ephemeral=True,
        )
    else:
        await responder.send(
            embed=discord.Embed(
                title="Not Permitted",
                description="You are not permitted to interact with these buttons.",
                color=BLANK_COLOR,
            )
        )


async def get_roblox_by_username(user: str, bot, ctx: commands.Context):
    if "<@" in user:
        try:
            member_converted = await discord.ext.commands.MemberConverter().convert(
                ctx, user
            )
            if member_converted:
                bl_user_data = await bot.bloxlink.find_roblox(member_converted.id)
                # print(bl_user_data)
                roblox_user = await bot.bloxlink.get_roblox_info(
                    bl_user_data["robloxID"]
                )
                return roblox_user
        except KeyError:
            return {"errors": ["Member could not be found in Discord."]}

    client = roblox.Client()
    roblox_user = await client.get_user_by_username(user)
    if not roblox_user:
        return {"errors": ["Could not find user"]}
    else:
        return await bot.bloxlink.get_roblox_info(roblox_user.id)


async def staff_check(bot_obj, guild, member):
    guild_settings = await bot_obj.settings.find_by_id(guild.id)
    if guild_settings:
        if "role" in guild_settings["staff_management"].keys():
            if guild_settings["staff_management"]["role"] != "":
                if isinstance(guild_settings["staff_management"]["role"], list):
                    for role in guild_settings["staff_management"]["role"]:
                        if role in [role.id for role in member.roles]:
                            return True
                elif isinstance(guild_settings["staff_management"]["role"], int):
                    if guild_settings["staff_management"]["role"] in [
                        role.id for role in member.roles
                    ]:
                        return True
    if (
        member.guild_permissions.manage_messages
        or member.guild_permissions.administrator
    ):
        return True
    return False


def time_converter(parameter: str) -> int:
    conversions = {
        ("s", "seconds", " seconds"): 1,
        ("m", "minute", "minutes", " minutes"): 60,
        ("h", "hour", "hours", " hours"): 60 * 60,
        ("d", "day", "days", " days"): 24 * 60 * 60,
        ("w", "week", " weeks"): 7 * 24 * 60 * 60,
    }

    for aliases, multiplier in conversions.items():
        parameter = parameter.strip()
        for alias in aliases:
            if parameter[(len(parameter) - len(alias)) :].lower() == alias.lower():
                alias_found = parameter[(len(parameter) - len(alias)) :]
                number = parameter.split(alias_found)[0]
                number = number.replace("-", "")  # prevent those negative times!
                if not number.strip()[-1].isdigit():
                    continue
                if int(number.strip()) * multiplier > 15552000:
                    raise OverflowError(
                        "Time value exceeds the maximum allowed duration of 180 days."
                    )
                return int(number.strip()) * multiplier

    raise ValueError("Invalid time format")


class GuildCheckFailure(commands.CheckFailure):
    pass


def require_settings():
    async def predicate(ctx: commands.Context):
        if ctx.guild is None:
            return True
        settings = await ctx.bot.settings.find_by_id(ctx.guild.id)
        if not settings:
            raise GuildCheckFailure()
        else:
            return True

    return commands.check(predicate)


async def update_ics(bot, ctx, channel, return_val: dict, ics_id: int):
    try:
        status: ServerStatus = await bot.prc_api.get_server_status(ctx.guild.id)
    except prc_api.ResponseFailure:
        status = None
    if not isinstance(status, ServerStatus):
        return return_val  # Invalid key

    try:
        queue: int = await bot.prc_api.get_server_queue(ctx.guild.id, minimal=True)
        players: list[Player] = await bot.prc_api.get_server_players(ctx.guild.id)
    except prc_api.ResponseFailure:
        return return_val  # fuck knows why
    mods: int = len(list(filter(lambda x: x.permission == "Server Moderator", players)))
    admins: int = len(
        list(filter(lambda x: x.permission == "Server Administrator", players))
    )
    total_staff: int = len(list(filter(lambda x: x.permission != "Normal", players)))

    if await bot.ics.db.count_documents({"_id": ics_id}):
        await bot.ics.db.update_one(
            {"_id": ics_id, "guild": ctx.guild.id},
            {
                "$set": {
                    "data": {
                        "join_code": status.join_key,
                        "players": status.current_players,
                        "max_players": status.max_players,
                        "queue": queue,
                        "staff": total_staff,
                        "admins": admins,
                        "mods": mods,
                    }
                }
            },
        )
    else:
        await bot.ics.insert(
            {
                "_id": ics_id,
                "guild": ctx.guild.id,
                "data": {
                    "join_code": status.join_key,
                    "players": status.current_players,
                    "max_players": status.max_players,
                    "queue": queue,
                    "staff": total_staff,
                    "admins": admins,
                    "mods": mods,
                },
                "associated_messages": [],
            }
        )

    return return_val


async def interpret_embed(bot, ctx, channel, embed: dict, ics_id: int):
    embed = discord.Embed.from_dict(embed)
    try:
        embed.title = await sub_vars(bot, ctx, channel, embed.title)
    except AttributeError:
        pass

    if str(var := await sub_vars(bot, ctx, channel, embed.author.name)) != "None":
        try:
            embed.set_author(name=await sub_vars(bot, ctx, channel, embed.author.name))
        except AttributeError:
            pass
    try:
        embed.description = await sub_vars(bot, ctx, channel, embed.description)
    except AttributeError:
        pass
    try:
        embed.set_footer(
            text=await sub_vars(bot, ctx, channel, embed.footer.text),
            icon_url=embed.footer.icon_url,
        )
    except AttributeError:
        pass
    for index, i in enumerate(embed.fields):
        embed.set_field_at(
            index,
            name=await sub_vars(bot, ctx, channel, i.name),
            value=await sub_vars(bot, ctx, channel, i.value),
        )

    if await bot.server_keys.db.count_documents({"_id": ctx.guild.id}) == 0:
        return embed

    return await update_ics(bot, ctx, channel, embed, ics_id)


async def interpret_content(bot, ctx, channel, content: str, ics_id):
    await update_ics(bot, ctx, channel, content, ics_id)
    return await sub_vars(bot, ctx, channel, content)


async def sub_vars(bot, ctx: commands.Context, channel, string, **kwargs):
    try:
        string = string.replace("{user}", ctx.author.mention)
        string = string.replace("{username}", ctx.author.name)
        string = string.replace("{display_name}", ctx.author.display_name)
        string = string.replace(
            "{time}", f"<t:{int(datetime.datetime.now().timestamp())}>"
        )
        string = string.replace("{server}", ctx.guild.name)
        string = string.replace("{channel}", channel.mention)
        string = string.replace("{prefix}", list(await get_prefix(bot, ctx))[-1])

        onduty: int = len(
            [
                i
                async for i in bot.shift_management.shifts.db.find(
                    {"Guild": ctx.guild.id, "EndEpoch": 0}
                )
            ]
        )

        string = string.replace("{onduty}", str(onduty))

        #### CUSTOM ER:LC VARS
        # Fetch whether they should even be allowed to use ER:LC vars
        if await bot.server_keys.db.count_documents({"_id": ctx.guild.id}) == 0:
            return string  # end here no point

        status: ServerStatus = await bot.prc_api.get_server_status(ctx.guild.id)
        if not isinstance(status, ServerStatus):
            return string  # Invalid key
        queue: int = await bot.prc_api.get_server_queue(ctx.guild.id, minimal=True)
        players: list[Player] = await bot.prc_api.get_server_players(ctx.guild.id)
        mods: int = len(
            list(filter(lambda x: x.permission == "Server Moderator", players))
        )
        admins: int = len(
            list(filter(lambda x: x.permission == "Server Administrator", players))
        )
        total_staff: int = len(
            list(filter(lambda x: x.permission != "Normal", players))
        )

        string = string.replace("{join_code}", status.join_key)
        string = string.replace("{players}", str(status.current_players))
        string = string.replace("{max_players}", str(status.max_players))
        string = string.replace("{queue}", str(queue))
        string = string.replace("{staff}", str(total_staff))
        string = string.replace("{admins}", str(admins))
        string = string.replace("{mods}", str(mods))

        return string
    except:
        return string


def get_elapsed_time(document):
    from datamodels.ShiftManagement import ShiftItem

    if isinstance(document, ShiftItem):
        new_document = {
            "Breaks": [
                {"StartEpoch": item.start_epoch, "EndEpoch": item.end_epoch}
                for item in document.breaks
            ],
            "StartEpoch": document.start_epoch,
            "EndEpoch": document.end_epoch,
            "AddedTime": document.added_time,
            "RemovedTime": document.removed_time,
        }
        document = new_document
    total_seconds = 0
    break_seconds = 0
    for br in document["Breaks"]:
        if br["EndEpoch"] != 0:
            break_seconds += int(br["EndEpoch"]) - int(br["StartEpoch"])
        else:
            break_seconds += int(
                datetime.datetime.now(tz=pytz.UTC).timestamp() - int(br["StartEpoch"])
            )

    total_seconds += (
        int(
            (
                document["EndEpoch"]
                if document["EndEpoch"] != 0
                else datetime.datetime.now(tz=pytz.UTC).timestamp()
            )
        )
        - int(document["StartEpoch"])
        + document.get("AddedTime", 0)
        - document["RemovedTime"]
    ) - break_seconds

    return total_seconds


async def get_prefix(bot, message):
    if not message.guild:
        return commands.when_mentioned_or(">")(bot, message)

    try:
        prefix = await bot.settings.find_by_id(message.guild.id)
        prefix = (prefix or {})["customisation"]["prefix"]
    except KeyError:
        return discord.ext.commands.when_mentioned_or(">")(bot, message)

    return commands.when_mentioned_or(prefix)(bot, message)


async def invis_embed(ctx: commands.Context, content: str, **kwargs) -> discord.Message:
    msg = await ctx.send(
        content=f"<:ERMCheck:1111089850720976906>  **{ctx.author.name}**, {content}",
        **kwargs,
    )
    return msg


async def failure_embed(
    ctx: commands.Context, content: str, **kwargs
) -> discord.Message:
    msg = await ctx.send(
        content=f"<:ERMClose:1111101633389146223>  **{ctx.author.name}**, {content}",
        **kwargs,
    )
    return msg


async def new_failure_embed(
    ctx: commands.Context, title: str, description: str, **kwargs
) -> discord.Message:
    msg = await ctx.send(
        embed=discord.Embed(title=title, description=description, color=BLANK_COLOR)
    )
    return msg


async def get_player_avatar_url(player_id):
    url = f"https://thumbnails.roblox.com/v1/users/avatar?userIds={player_id}&size=180x180&format=Png&isCircular=false"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()
            return data["data"][0]["imageUrl"]


async def run_command(bot, guild_id, username, message):
    while True:
        command = f":pm {username} {message}"
        command_response = await bot.prc_api.run_command(guild_id, command)
        if command_response[0] == 200:
            logging.info(f"Sent PM to {username} in guild {guild_id}")
            break
        elif command_response[0] == 429:
            retry_after = int(command_response[1].get("Retry-After", 5))
            logging.warning(f"Rate limited. Retrying after {retry_after} seconds.")
            await asyncio.sleep(retry_after)
        else:
            logging.error(f"Failed to send PM to {username} in guild {guild_id}")
            break


def is_whitelisted(vehicle_name, whitelisted_vehicle):
    vehicle_year_match = re.search(r"\d{4}$", vehicle_name)
    whitelisted_year_match = re.search(r"\d{4}$", whitelisted_vehicle)
    if vehicle_year_match and whitelisted_year_match:
        vehicle_year = vehicle_year_match.group()
        whitelisted_year = whitelisted_year_match.group()
        if vehicle_year != whitelisted_year:
            return False
        vehicle_name_base = vehicle_name[: vehicle_year_match.start()].strip()
        whitelisted_vehicle_base = whitelisted_vehicle[
            : whitelisted_year_match.start()
        ].strip()
        return (
            fuzz.ratio(vehicle_name_base.lower(), whitelisted_vehicle_base.lower()) > 80
        )
    return False


async def int_failure_embed(interaction, content, **kwargs):
    try:
        await interaction.response.send_message(
            content=f"<:ERMClose:1111101633389146223>  **{interaction.user.name}**, {content}",
            **kwargs,
        )
    except discord.InteractionResponded:
        await interaction.response.send_message(
            content=f"<:ERMClose:1111101633389146223>  **{interaction.user.name}**, {content}",
            **kwargs,
        )


async def int_pending_embed(interaction, content, **kwargs):
    try:
        await interaction.response.send_message(
            content=f"<:ERMPending:1111097561588183121>  **{interaction.user.name}**, {content}",
            **kwargs,
        )
    except discord.InteractionResponded:
        await interaction.response.send_message(
            content=f"<:ERMPending:1111097561588183121>  **{interaction.user.name}**, {content}",
            **kwargs,
        )


async def pending_embed(
    ctx: commands.Context, content: str, **kwargs
) -> discord.Message:
    msg = await ctx.send(
        content=f"<:ERMPending:1111097561588183121>  **{ctx.author.name}**, {content}",
        **kwargs,
    )
    return msg


async def int_invis_embed(interaction, content, **kwargs):
    try:
        await interaction.response.send_message(
            content=f"<:ERMCheck:1111089850720976906>  **{interaction.user.name}**, {content}",
            **kwargs,
        )
    except discord.InteractionResponded:
        await interaction.response.send_message(
            content=f"<:ERMCheck:1111089850720976906>  **{interaction.user.name}**, {content}",
            **kwargs,
        )


async def coloured_embed(
    ctx: commands.Context, content: str, **kwargs
) -> discord.Message:
    embed = Embed(color=0xED4348, description=f"{content}")
    msg = await ctx.send(embed=embed, **kwargs)
    return msg


async def int_coloured_embed(interaction, content, **kwargs):
    embed = Embed(color=0xED4348, description=f"{content}")
    try:
        await interaction.response.send_message(embed=embed, **kwargs)
    except discord.InteractionResponded:
        await interaction.edit_original_response(embed=embed, **kwargs)


async def request_response(bot, ctx, question, **kwargs):
    await ctx.send(
        content=f"<:ERMPending:1111097561588183121>  **{ctx.author.name}**, {question}",
        **kwargs,
    )
    try:
        response = await bot.wait_for(
            "message",
            check=lambda message: message.author == ctx.author
            and message.guild.id == ctx.guild.id,
            timeout=300,
        )
    except asyncio.TimeoutError:
        raise Exception("No response")
    return response


def make_ordinal(n):
    """
    Convert an integer into its ordinal representation::

        make_ordinal(0)   => '0th'
        make_ordinal(3)   => '3rd'
        make_ordinal(122) => '122nd'
        make_ordinal(213) => '213th'
    """
    n = int(n)
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = ["th", "st", "nd", "rd", "th"][min(n % 10, 4)]
    return str(n) + suffix


async def fetch_get_channel(target, identifier):
    channel = target.get_channel(identifier)
    if not channel:
        try:
            channel = await target.fetch_channel(identifier)
        except discord.HTTPException as e:
            channel = None
    return channel


async def get_discord_by_roblox(bot, username):
    api_url = "https://users.roblox.com/v1/usernames/users"
    payload = {"usernames": [username], "excludeBannedUsers": True}
    response = requests.post(api_url, json=payload)
    if response.status_code == 200:
        data = response.json()["data"][0]
        id = data["id"]
        linked_account = await bot.oauth2_users.db.find_one({"roblox_id": id})
        if linked_account:
            return linked_account["discord_id"]
        else:
            return None


async def log_command_usage(bot, guild, member, command_name):
    settings = await bot.settings.find_by_id(guild.id)
    if not settings:
        return
    if not settings.get("staff_management", {}).get("erm_log_channel"):
        return
    try:
        log_channel_id = settings.get("staff_management", {}).get("erm_log_channel")
    except (ValueError, TypeError):
        return
    log_channel = guild.get_channel(log_channel_id)
    if log_channel is None:
        return
    if not log_channel.permissions_for(guild.me).send_messages:
        return
    embed = discord.Embed(
        title="ERM Command Log",
        description=f"Command `{command_name}` used by {member.mention}",
        color=BLANK_COLOR,
    )
    embed.set_footer(text=f"User ID: {member.id}")
    embed.set_author(name=member.name, icon_url=member.display_avatar.url)
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await log_channel.send(embed=embed)


async def config_change_log(bot, guild, member, data):
    setting = await bot.settings.find_by_id(guild.id)
    if not setting:
        return
    if not setting.get("staff_management", {}).get("erm_log_channel"):
        return
    try:
        log_channel_id = setting.get("staff_management", {}).get("erm_log_channel")
    except (ValueError, TypeError) as e:
        return
    log_channel = guild.get_channel(log_channel_id)
    if log_channel is None:
        return
    if not log_channel.permissions_for(guild.me).send_messages:
        return
    embed = discord.Embed(
        title="ERM Config Change Log",
        description=f"Configuration change made by {member.mention}",
        color=BLANK_COLOR,
    ).add_field(name="Configuration Change", value=data)
    embed.set_footer(text=f"User ID: {member.id}")
    embed.set_author(name=member.name, icon_url=member.display_avatar.url)
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    await log_channel.send(embed=embed)


async def secure_logging(
    bot,
    guild_id,
    author_id,
    interpret_type: typing.Literal["Message", "Hint", "Command"],
    command_string: str,
    attempted: bool = False,
):
    settings = await bot.settings.find_by_id(guild_id)
    channel = ((settings or {}).get("game_security", {}) or {}).get("channel")
    try:
        channel = await (await bot.fetch_guild(guild_id)).fetch_channel(channel)
    except discord.HTTPException:
        channel = None
    bloxlink_user = await bot.bloxlink.find_roblox(author_id)
    # # print(bloxlink_user)
    server_status: ServerStatus = await bot.prc_api.get_server_status(guild_id)
    if channel is not None:
        if not attempted:
            await channel.send(
                embed=discord.Embed(
                    title="Remote Server Logs",
                    description=f"[{(await bot.bloxlink.get_roblox_info(bloxlink_user['robloxID']))['name']}:{bloxlink_user['robloxID']}](https://roblox.com/users/{bloxlink_user['robloxID']}/profile) used a command: {'`:m {}`'.format(command_string) if interpret_type == 'Message' else ('`:h {}`'.format(command_string) if interpret_type == 'Hint' else '`{}`'.format(command_string))}",
                    color=RED_COLOR,
                ).set_footer(text=f"Private Server: {server_status.join_key}")
            )
        else:
            await channel.send(
                embed=discord.Embed(
                    title="Attempted Command Execution",
                    description=f"[{(await bot.bloxlink.get_roblox_info(bloxlink_user['robloxID']))['name']}:{bloxlink_user['robloxID']}](https://roblox.com/users/{bloxlink_user['robloxID']}/profile) attempted to use the command: {'`:m {}`'.format(command_string) if interpret_type == 'Message' else ('`:h {}`'.format(command_string) if interpret_type == 'Hint' else '`{}`'.format(command_string))}",
                    color=RED_COLOR,
                ).set_footer(text=f"Private Server: {server_status.join_key}")
            )
