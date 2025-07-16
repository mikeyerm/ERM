import asyncio
import logging

import discord
import time

from decouple import config
from discord.ext import commands, tasks

from utils import prc_api
from utils.prc_api import Player, ServerStatus
from utils.utils import fetch_get_channel


async def update_channel(bot, guild, channel_id, stat_config, placeholders):
    try:
        channel = await fetch_get_channel(guild, int(channel_id))
        if channel:
            format_string = stat_config["format"]
            format_string = format_string.format(**placeholders)

            logging.info(f"Current name: '{channel.name}', New name: '{format_string}'")
            
            bot_member = guild.get_member(bot.user.id)
            permissions = channel.permissions_for(bot_member)
            if not permissions.manage_channels:
                logging.error(f"Missing 'Manage Channels' permission for channel {channel_id} in guild {guild.id}")
                return

            if channel.name != format_string:
                try:
                    await channel.edit(name=format_string)
                    logging.info(f"Successfully updated channel {channel_id} to: {format_string}")
                except discord.errors.Forbidden:
                    logging.error(f"Forbidden: Bot lacks permissions to edit channel {channel_id}")
                except discord.errors.HTTPException as http_err:
                    logging.error(f"HTTP Error updating channel {channel_id}: {http_err}")
            else:
                logging.debug(
                    f"Skipped update - no changes needed for channel {channel_id} in guild {guild.id}"
                )
        else:
            logging.error(f"Channel {channel_id} not found in guild {guild.id}")
    except Exception as e:
        logging.error(
            f"Failed to update channel in guild {guild.id}: {e}", exc_info=True
        )


@tasks.loop(minutes=15, reconnect=True)
async def statistics_check(bot):


    initial_time = time.time()
    async for guild_data in bot.settings.db.find(
        {"ERLC.statistics": {"$exists": True}}
    ):
        guild_id = guild_data["_id"]
        try:
            guild = await bot.fetch_guild(guild_id)
        except discord.errors.NotFound:
            continue

        settings = await bot.settings.find_by_id(guild_id)
        if (
            not settings
            or "ERLC" not in settings
            or "statistics" not in settings["ERLC"]
        ):
            continue

        statistics = settings["ERLC"]["statistics"]
        try:
            players: list[Player] = await bot.prc_api.get_server_players(guild_id)
            status: ServerStatus = await bot.prc_api.get_server_status(guild_id)
            queue: int = await bot.prc_api.get_server_queue(guild_id, minimal=True)
        except prc_api.ResponseFailure:
            logging.error(f"PRC ResponseFailure for guild {guild_id}")
            continue

        on_duty = await bot.shift_management.shifts.db.count_documents(
            {"Guild": guild_id, "EndEpoch": 0}
        )
        moderators = len(
            list(filter(lambda x: x.permission == "Server Moderator", players))
        )
        admins = len(
            list(filter(lambda x: x.permission == "Server Administrator", players))
        )
        staff_ingame = len(list(filter(lambda x: x.permission != "Normal", players)))
        current_player = status.current_players
        join_code = status.join_key
        max_players = status.max_players

        logging.info(f"Processing statistics for guild {guild_id}")
        placeholders = {
            "onduty": on_duty,
            "staff": staff_ingame,
            "mods": moderators,
            "admins": admins,
            "players": current_player,
            "join_code": join_code,
            "max_players": max_players,
            "queue": queue,
        }

        tasks = [
            update_channel(bot, guild, channel_id, stat_config, placeholders)
            for channel_id, stat_config in statistics.items()
        ]
        await asyncio.gather(*tasks)

    end_time = time.time()
    logging.warning(f"Event statistics_check took {end_time - initial_time} seconds")
