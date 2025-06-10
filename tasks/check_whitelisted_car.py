import datetime
import re
import time
import discord
import pytz
from decouple import config
from discord.ext import commands, tasks
import logging
import asyncio
import roblox

from utils.constants import RED_COLOR, BLANK_COLOR
from utils.prc_api import Player
from utils import prc_api
from utils.utils import is_whitelisted, run_command


@tasks.loop(minutes=10, reconnect=True)
async def check_whitelisted_car(bot):
    current_time = time.time()
    if not hasattr(bot, 'pm_counter_timestamps'):
        bot.pm_counter_timestamps = {}
    
    expired_keys = [k for k, timestamp in bot.pm_counter_timestamps.items() 
                   if current_time - timestamp > 3600] 
    #We will keep PM counter for maximum 1 hour.
    #Otherwise, it's leading to growth of the dictionary without any bounds.
    for key in expired_keys:
        if key in bot.pm_counter:
            bot.pm_counter.pop(key)
        if key in bot.pm_counter_timestamps:
            bot.pm_counter_timestamps.pop(key)

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
    logging.info("Starting check_whitelisted_car task")

    base = {"ERLC.vehicle_restrictions.enabled": True}

    for key, value in filter_map.items():
        base[key] = value

    pipeline = [
        {"$match": base},
        {
            "$lookup": {
                "from": "server_keys",
                "localField": "_id",
                "foreignField": "_id",
                "as": "server_key",
            }
        },
        {"$match": {"server_key": {"$ne": []}}},
    ]

    try:
        async for items in bot.settings.db.aggregate(pipeline):
            guild_id = items["_id"]
            logging.info(f"Processing guild ID: {guild_id} for Whitelisted Car Check")

            try:
                settings = items["ERLC"].get("vehicle_restrictions", {})
                if not settings:
                    continue

                whitelisted_vehicle_roles = settings.get("roles", [])
                alert_channel_id = settings.get("channel")
                whitelisted_vehicles = settings.get("cars", [])
                alert_message = settings.get(
                    "message", "You do not have the required role to use this vehicle."
                )

                if (
                    not whitelisted_vehicle_roles
                    or not alert_channel_id
                    or not whitelisted_vehicles
                ):
                    continue

                guild = bot.get_guild(guild_id)
                if not guild:
                    try:
                        guild = await asyncio.wait_for(bot.fetch_guild(guild_id), timeout=5.0)
                    except asyncio.TimeoutError:
                        logging.warning(f"Timeout fetching guild {guild_id}")
                        continue

                alert_channel = bot.get_channel(alert_channel_id)
                if not alert_channel:
                    try:
                        alert_channel = await asyncio.wait_for(bot.fetch_channel(alert_channel_id), timeout=5.0)
                    except asyncio.TimeoutError:
                        logging.warning(f"Timeout fetching channel {alert_channel_id}")
                        continue

                if not alert_channel:
                    continue

                exotic_roles = []
                if isinstance(whitelisted_vehicle_roles, int):
                    role = guild.get_role(whitelisted_vehicle_roles)
                    if role:
                        exotic_roles = [role]
                elif isinstance(whitelisted_vehicle_roles, list):
                    exotic_roles = [
                        r
                        for r_id in whitelisted_vehicle_roles
                        if (r := guild.get_role(r_id))
                    ]

                if not exotic_roles:
                    continue

                try:
                    players_task = asyncio.create_task(bot.prc_api.get_server_players(guild_id))
                    vehicles_task = asyncio.create_task(bot.prc_api.get_server_vehicles(guild_id))
                    players, vehicles = await asyncio.gather(players_task, vehicles_task)
                except Exception as e:
                    logging.error(f"Error fetching data for guild {guild_id}: {e}")
                    continue

                player_lookup = {p.username: p for p in players}

                for vehicle in vehicles:
                    player = player_lookup.get(vehicle.username)
                    if not player:
                        continue

                    def normalize_vehicle_name(name):
                        name = name.lower().strip()
                        year = None
                        year_match = re.search(r"\b(19|20)\d{2}\b", name)
                        if year_match:
                            year = year_match.group(0)
                            name = name.replace(year, "").strip()
                        name = " ".join(name.split())
                        return name, year

                    vehicle_name, vehicle_year = normalize_vehicle_name(vehicle.vehicle)
                    is_vehicle_whitelisted = False

                    for wv in whitelisted_vehicles:
                        whitelist_name, whitelist_year = normalize_vehicle_name(str(wv))
                        if vehicle_name == whitelist_name and (
                            not vehicle_year
                            or not whitelist_year
                            or vehicle_year == whitelist_year
                        ):
                            is_vehicle_whitelisted = True
                            break

                    if not is_vehicle_whitelisted:
                        continue

                    pattern = re.compile(re.escape(player.username), re.IGNORECASE)
                    member = None

                    for m in guild.members:
                        if (
                            pattern.search(m.name)
                            or pattern.search(m.display_name)
                            or (
                                hasattr(m, "global_name")
                                and m.global_name
                                and pattern.search(m.global_name)
                            )
                        ):
                            member = m
                            break

                    if not member:
                        try:
                            members = await asyncio.wait_for(
                                guild.query_members(query=player.username, limit=1),
                                timeout=5.0
                            )
                            member = members[0] if members else None
                        except asyncio.TimeoutError:
                            logging.warning(f"Timeout querying member {player.username}")
                            continue

                    if member:
                        if not any(role in member.roles for role in exotic_roles):
                            await run_command(bot, guild_id, player.username, alert_message)
                            await handle_pm_counter(bot, player, guild, alert_channel)
                    else:
                        await handle_non_member(
                            bot, player, guild, alert_channel, alert_message
                        )
                # Cleaning Up the variables stored in memory
                del players
                del vehicles
                del player_lookup

            except discord.errors.NotFound:
                logging.error(f"Guild or channel not found: {guild_id}")
                continue
            except Exception as e:
                logging.error(f"Error processing guild {guild_id}: {e}", exc_info=True)
                continue
            
    except Exception as e:
        logging.error(f"Error in database aggregation: {e}", exc_info=True)

    end_time = time.time()
    logging.info(
        f"Event check_whitelisted_car completed in {end_time - initial_time:.2f} seconds"
    )


async def handle_pm_counter(bot, player, guild, alert_channel):
    current_time = time.time()
    
    if not hasattr(bot, 'pm_counter_timestamps'):
        bot.pm_counter_timestamps = {}
    
    if player.username not in bot.pm_counter:
        bot.pm_counter[player.username] = 1
    else:
        bot.pm_counter[player.username] += 1
    bot.pm_counter_timestamps[player.username] = current_time

    if bot.pm_counter[player.username] >= 4:
        await send_warning_embed(bot, player, guild, alert_channel)
        bot.pm_counter.pop(player.username, None)
        bot.pm_counter_timestamps.pop(player.username, None)


async def handle_non_member(bot, player, guild, alert_channel, alert_message):
    await run_command(bot, guild.id, player.username, alert_message)
    await handle_pm_counter(bot, player, guild, alert_channel)


async def send_warning_embed(bot, player, guild, alert_channel):
    try:
        user = await bot.roblox.get_user(int(player.id))
        avatar = await bot.roblox.thumbnails.get_user_avatar_thumbnails(
            [user], type=roblox.thumbnails.AvatarThumbnailType.headshot
        )
        avatar_url = avatar[0].image_url if avatar else None
        embed = discord.Embed(
            title="Whitelisted Vehicle Warning",
            description=f"""
            > I've PM'd [{player.username}](https://roblox.com/users/{player.id}/profile) three times that they are in a whitelisted vehicle without the required role.
            """,
            color=BLANK_COLOR,
            timestamp=datetime.datetime.now(tz=pytz.UTC),
        )

        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        await alert_channel.send(embed=embed)
    except discord.HTTPException as e:
        logging.error(f"Failed to send embed for {player.username}: {e}")
    except Exception as e:
        logging.error(
            f"Error in send_warning_embed for {player.username}: {e}", exc_info=True
        )
