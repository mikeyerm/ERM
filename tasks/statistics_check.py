import asyncio
import logging
import discord
import time

from decouple import config
from discord.ext import commands, tasks
from functools import reduce

from utils import prc_api
from utils.prc_api import Player, ServerStatus
from utils.utils import fetch_get_channel


async def update_channel(guild, channel_id, stat_config, placeholders):
    try:
        channel = await asyncio.wait_for(
            fetch_get_channel(guild, int(channel_id)),
            timeout=5.0
        )
        if channel:
            format_string = stat_config["format"]
            for key, value in placeholders.items():
                format_string = format_string.replace(f"{{{key}}}", str(value))

            if channel.name != format_string:
                await asyncio.wait_for(
                    channel.edit(name=format_string),
                    timeout=5.0
                )
                logging.info(f"Updated channel {channel_id} in guild {guild.id}")
            else:
                logging.debug(
                    f"Skipped update for channel {channel_id} in guild {guild.id} - no changes needed"
                )
        else:
            logging.error(f"Channel {channel_id} not found in guild {guild.id}")
    except asyncio.TimeoutError:
        logging.error(f"Timeout updating channel {channel_id} in guild {guild.id}")
    except Exception as e:
        logging.error(
            f"Failed to update channel in guild {guild.id}: {e}", exc_info=True
        )


@tasks.loop(minutes=15, reconnect=True)
async def statistics_check(bot):
    filter_map = (
        {"_id": int(config("CUSTOM_GUILD_ID", default=0))}
        if config("ENVIRONMENT") == "CUSTOM"
        else {
            "_id": {
                "$nin": [
                    int(item["GuildID"] or 0)
                    async for item in bot.whitelabel.db.find({})
                ]
            }
        }
    )

    initial_time = time.time()
    cursor = bot.settings.db.find(
        {"ERLC.statistics": {"$exists": True}, **filter_map}
    )
    
    try:
        async for guild_data in cursor:
            guild_id = guild_data["_id"]
            try:
                guild = await asyncio.wait_for(
                    bot.fetch_guild(guild_id),
                    timeout=5.0
                )
            except asyncio.TimeoutError:
                logging.error(f"Timeout fetching guild {guild_id}")
                continue
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
                player_task = asyncio.create_task(bot.prc_api.get_server_players(guild_id))
                status_task = asyncio.create_task(bot.prc_api.get_server_status(guild_id))
                queue_task = asyncio.create_task(bot.prc_api.get_server_queue(guild_id, minimal=True))
                duty_task = asyncio.create_task(bot.shift_management.shifts.db.count_documents(
                    {"Guild": guild_id, "EndEpoch": 0}
                ))
                
                results = await asyncio.wait_for(
                    asyncio.gather(player_task, status_task, queue_task, duty_task, return_exceptions=True),
                    timeout=10.0
                )
                
                for result in results:
                    if isinstance(result, Exception):
                        raise result
                        
                players, status, queue, on_duty = results
                
            except asyncio.TimeoutError:
                logging.error(f"Timeout fetching data for guild {guild_id}")
                continue
            except prc_api.ResponseFailure:
                logging.error(f"PRC ResponseFailure for guild {guild_id}")
                continue
            except Exception as e:
                logging.error(f"Error fetching data for guild {guild_id}: {e}", exc_info=True)
                continue

            permission_counts = {"Server Moderator": 0, "Server Administrator": 0, "staff": 0}
            
            for player in players:
                if player.permission == "Server Moderator":
                    permission_counts["Server Moderator"] += 1
                elif player.permission == "Server Administrator":
                    permission_counts["Server Administrator"] += 1
                
                if player.permission != "Normal":
                    permission_counts["staff"] += 1
            
            moderators = permission_counts["Server Moderator"]
            admins = permission_counts["Server Administrator"]
            staff_ingame = permission_counts["staff"]
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

            update_tasks = []
            chunk_size = 5
            
            channel_items = list(statistics.items())
            for i in range(0, len(channel_items), chunk_size):
                chunk = channel_items[i:i+chunk_size]
                chunk_tasks = [
                    update_channel(guild, channel_id, stat_config, placeholders)
                    for channel_id, stat_config in chunk
                ]
                await asyncio.gather(*chunk_tasks)
                
            logging.info(
                f"Statistics updated for guild {guild_id}"
            )
            
            del players
            del update_tasks
            del permission_counts
            placeholders.clear()
            
    except Exception as e:
        logging.error(f"Error in statistics_check: {e}", exc_info=True)
    end_time = time.time()
    logging.warning(f"Event statistics_check took {end_time - initial_time:.2f} seconds")
