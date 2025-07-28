import re
from typing import List
import discord
from discord.ext import commands, tasks
import time
import logging
import asyncio
import aiohttp
import pytz
import roblox
import datetime
from decouple import config

from utils.prc_api import JoinLeaveLog, Player
from utils.utils import fetch_get_channel, staff_check
from utils import prc_api
from utils.constants import BLANK_COLOR, GREEN_COLOR, RED_COLOR
from menus import AvatarCheckView
from utils.username_check import UsernameChecker

global_aggregate = [
    {
        "$match": {
            "ERLC": {"$exists": True},
            "$or": [
                {"ERLC.rdm_channel": {"$type": "long", "$ne": 0}},
                {"ERLC.kill_logs": {"$type": "long", "$ne": 0}},
                {"ERLC.player_logs": {"$type": "long", "$ne": 0}},
                {"ERLC.welcome_message": {"$exists": True}},
                {"ERLC.automatic_shifts.enabled": {"$eq": True}},
                {"ERLC.team_restrictions": {"$exists": True}},
            ],
        }
    },
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

count_aggregate = global_aggregate + [{"$count": "total"}]


async def iterate_prc_logs_global(bot):
    try:
        server_count = await bot.settings.db.aggregate(count_aggregate).to_list(1)
        server_count = server_count[0]["total"] if server_count else 0

        logging.warning(f"[ITERATE] Starting iteration for {server_count} servers")
        processed = 0
        start_time = time.time()

        pipeline = global_aggregate

        semaphore = asyncio.Semaphore(10)
        tasks = []


        async for items in bot.settings.db.aggregate(pipeline):
            tasks.append(process_guild(bot, items, semaphore))
            processed += 1
            if processed % 10 == 0:
                logging.warning(f"[ITERATE] Queued {processed}/{server_count} servers")

        await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()
        logging.warning(
            f"[ITERATE] Completed task! Processed {processed} servers in {end_time - start_time:.2f} seconds"
        )

    except Exception as e:
        logging.error(f"[ITERATE] Error in iteration: {str(e)}", exc_info=True)



async def iterate_prc_logs_custom(bot):
    guild_id = config("CUSTOM_GUILD_ID")
    if not guild_id:
        logging.error("No custom guild ID provided for custom environment")
        return

    try:
        await unprimitive_guild_process({"_id": int(guild_id)}, bot)
    except Exception as e:
        logging.error(f"error processing guild: {e}")

async def unprimitive_guild_process(items, bot):
    guild = bot.get_guild(items["_id"]) or await bot.fetch_guild(
        items["_id"]
    )
    settings = await bot.settings.find_by_id(guild.id)
    erlc_settings = settings.get("ERLC", {})

    if await bot.whitelabel.db.find_one({"GuildID": str(guild.id)}) and not config("CUSTOM_GUILD_ID") == str(guild.id):
        logging.warning("Not handling {} due to whitelabel instance existing")
        return

    channels = {
        "kill_logs": erlc_settings.get("kill_logs"),
        "player_logs": erlc_settings.get("player_logs"),
    }

    channels = {
        k: await fetch_get_channel(guild, v)
        for k, v in channels.items()
        if v
    }
    has_welcome_message = bool(
        erlc_settings.get("welcome_message", False)
    )
    has_team_restrictions = bool(erlc_settings.get("team_restrictions"))
    has_automatic_shifts = bool(
        erlc_settings.get("automatic_shifts", {})
    )

    if (
            not channels
            and not has_welcome_message
            and not has_team_restrictions
            and not has_automatic_shifts
    ):
        return

    kill_logs, player_logs, command_logs = await fetch_logs_with_retry(
        guild.id, bot
    )
    current_time = int(time.time())

    if command_logs:
        await save_new_logs(bot, guild.id, command_logs, current_time)

    subtasks = []

    if has_welcome_message:
        last_timestamp = bot.log_tracker.get_last_timestamp(
            guild.id, "welcome_message"
        )
        latest_timestamp = await send_welcome_message(
            bot, settings, guild.id, player_logs, last_timestamp
        )
        bot.log_tracker.update_timestamp(
            guild.id, "welcome_message", latest_timestamp
        )

    if has_team_restrictions:
        await check_team_restrictions(
            bot,
            settings,
            guild.id,
            await bot.prc_api.get_server_players(guild.id),
        )

    if has_automatic_shifts:
        last_timestamp = bot.log_tracker.get_last_timestamp(
            guild.id, "automatic_shifts"
        )
        latest_timestamp = await check_automatic_shifts(
            bot, settings, guild.id, player_logs, last_timestamp
        )
        bot.log_tracker.update_timestamp(
            guild.id, "automatic_shifts", latest_timestamp
        )

    if "kill_logs" in channels and kill_logs:
        last_timestamp = bot.log_tracker.get_last_timestamp(
            guild.id, "kill_logs"
        )
        embeds, latest_timestamp = process_kill_logs(
            kill_logs, last_timestamp
        )
        if embeds:
            subtasks.append(
                send_log_batch(channels["kill_logs"], embeds)
            )
            bot.log_tracker.update_timestamp(
                guild.id, "kill_logs", latest_timestamp
            )

    if "player_logs" in channels and player_logs:
        last_timestamp = bot.log_tracker.get_last_timestamp(
            guild.id, "player_logs"
        )
        embeds, latest_timestamp = await process_player_logs(
            bot, settings, guild.id, player_logs, last_timestamp
        )
        if embeds:
            subtasks.append(
                send_log_batch(channels["player_logs"], embeds)
            )
            bot.log_tracker.update_timestamp(
                guild.id, "player_logs", latest_timestamp
            )

    if erlc_settings.get("kick_timer", {}).get("enabled", False):
        await handle_kick_timer(
            bot, settings, guild.id, player_logs, command_logs
        )

    if subtasks:
        await asyncio.gather(*subtasks, return_exceptions=True)

async def process_guild(bot, items, semaphore):
    async with semaphore:
        await asyncio.sleep(
            0.25
        )  # we need to slow things down a bit for discord
        try:
            await unprimitive_guild_process(items, bot)
        except Exception as e:
            logging.warning(f"error processing guild: {e}")


@tasks.loop(minutes=7, reconnect=True)
async def iterate_prc_logs(bot):
    if bot.environment == "PRODUCTION":
        await iterate_prc_logs_global(bot)
    else:
        await iterate_prc_logs_custom(
            bot
        )


async def fetch_logs_with_retry(guild_id, bot, retries=3):
    """Helper function to fetch logs with retry logic"""
    for attempt in range(retries):
        try:
            kill_logs = await bot.prc_api.fetch_kill_logs(guild_id)
            player_logs = await bot.prc_api.fetch_player_logs(guild_id)
            command_logs = await bot.prc_api.fetch_server_logs(guild_id)
            return kill_logs, player_logs, command_logs
        except prc_api.ResponseFailure as e:
            if e.status_code == 429 and attempt < retries - 1:
                retry_after = float(e.json_data.get("retry_after", 5))
                await asyncio.sleep(retry_after)
                continue
            raise
    return None, None, None


async def save_new_logs(bot, guild_id, command_logs, current_time):
    """Save new command logs to the database by updating existing documents"""
    last_saved = await bot.saved_logs.find_by_id(guild_id)

    last_timestamp = last_saved["timestamp"] if last_saved else 0
    cutoff_time = current_time - 10800

    new_logs = [
        {
            "username": log.username,
            "user_id": log.user_id,
            "timestamp": log.timestamp,
            "is_automated": log.is_automated,
            "command": log.command,
        }
        for log in command_logs
        if log.timestamp > last_timestamp and log.timestamp > cutoff_time
    ]

    if new_logs:
        if last_saved:
            # Filter both existing and new logs to remove old ones
            existing_logs = [
                log
                for log in last_saved.get("logs", [])
                if log["timestamp"] > cutoff_time
            ]
            await bot.saved_logs.update(
                {
                    "_id": guild_id,
                    "timestamp": current_time,
                    "logs": existing_logs + new_logs,
                }
            )
        else:
            await bot.saved_logs.insert(
                {"_id": guild_id, "timestamp": current_time, "logs": new_logs}
            )


async def send_log_batch(channel, embeds):
    """Helper function to send log embeds in batches"""
    if not embeds:
        return
    # Split embeds into chunks of 10 (Discord's limit)
    for i in range(0, len(embeds), 10):
        chunk = embeds[i: i + 10]
        try:
            await channel.send(embeds=chunk)
        except discord.HTTPException as e:
            logging.error(f"Failed to send log batch: {e}")


def process_kill_logs(kill_logs, last_timestamp):
    """Process kill logs and return embeds"""
    embeds = []
    latest_timestamp = last_timestamp

    for log in sorted(kill_logs):
        if log.timestamp <= last_timestamp:
            continue

        latest_timestamp = max(latest_timestamp, log.timestamp)
        embed = discord.Embed(
            title="Kill Log",
            color=BLANK_COLOR,
            description=f"[{log.killer_username}](https://roblox.com/users/{log.killer_user_id}/profile) killed [{log.killed_username}](https://roblox.com/users/{log.killed_user_id}/profile) • <t:{int(log.timestamp)}:T>",
        )
        embeds.append(embed)

    return embeds, latest_timestamp


async def process_player_logs(bot, settings, guild_id, player_logs, last_timestamp):
    """Process player logs and return embeds"""
    embeds = []
    latest_timestamp = last_timestamp
    new_join_ids = []

    username_checker = UsernameChecker()

    unrealistic_check = settings.get("ERLC", {}).get("unrealistic_username_check", {})
    if unrealistic_check.get("enabled"):
        for log in sorted(player_logs):
            if log.timestamp <= last_timestamp or log.type != "join":
                continue

            if username_checker.is_unrealistic(log.username):
                try:
                    channel_id = unrealistic_check.get("channel")
                    if not channel_id:
                        continue

                    guild = bot.get_guild(guild_id) or await bot.fetch_guild(guild_id)
                    channel = await fetch_get_channel(guild, channel_id)
                    if not channel:
                        continue

                    user = await bot.roblox.get_user(int(log.user_id))
                    avatar = await bot.roblox.thumbnails.get_user_avatar_thumbnails(
                        [user], type=roblox.thumbnails.AvatarThumbnailType.headshot
                    )
                    avatar_url = avatar[0].image_url if avatar else None

                    embed = discord.Embed(
                        title="Suspicious Username Detected",
                        description="A player with a potentially problematic username has joined the server.",
                        color=0xFF0000,
                    )
                    embed.add_field(
                        name="Player Information",
                        value=f"> **Username:** [{log.username}](https://roblox.com/users/{log.user_id}/profile)\n"
                              f"> **User ID:** {log.user_id}\n"
                              f"> **Reason:** Username appears to use confusing character patterns",
                    )
                    if avatar_url:
                        embed.set_thumbnail(url=avatar_url)

                    mentions = [
                        f"<@&{role}>"
                        for role in unrealistic_check.get("mentioned_roles", [])
                    ]
                    await channel.send(
                        content=" ".join(mentions) if mentions else None,
                        embed=embed,
                        allowed_mentions=discord.AllowedMentions.all(),
                    )
                except Exception as e:
                    logging.error(f"Error processing unrealistic username alert: {e}")

    for log in sorted(player_logs):
        if log.timestamp <= last_timestamp:
            continue
        if log.type == "join":
            new_join_ids.append(log.user_id)

        latest_timestamp = max(latest_timestamp, log.timestamp)
        embed = discord.Embed(
            title=f"Player {'Join' if log.type == 'join' else 'Leave'} Log",
            description=f"[{log.username}](https://roblox.com/users/{log.user_id}/profile) {'joined the server' if log.type == 'join' else 'left the server'} • <t:{int(log.timestamp)}:T>",
            color=GREEN_COLOR if log.type == "join" else RED_COLOR,
        )
        embeds.append(embed)

    if new_join_ids and settings.get("ERLC", {}).get("avatar_check", {}).get("channel"):
        enabled = settings.get("ERLC", {}).get("avatar_check", {}).get("enabled", True)
        if not enabled:
            return embeds, latest_timestamp

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                        config("AVATAR_CHECK_URL"),
                        json={"robloxIds": new_join_ids},
                        timeout=10,
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("success"):
                            for user_id, result in data["data"]["results"].items():
                                is_unrealistic = result.get("unrealistic", False)
                                has_blacklisted_items = False
                                blacklisted_reasons = []

                                logging.info(f"Processing user {user_id}")
                                logging.info(
                                    f"Blacklisted items configured: {settings.get('ERLC', {}).get('avatar_check', {}).get('blacklisted_items', [])}"
                                )

                                blacklisted_items = (
                                    settings.get("ERLC", {})
                                    .get("avatar_check", {})
                                    .get("blacklisted_items", [])
                                )
                                if blacklisted_items:
                                    current_items = result.get("current_items", [])
                                    logging.info(
                                        f"Current items: {[item['id'] for item in current_items]}"
                                    )

                                    for item in current_items:
                                        if str(item["id"]) in map(
                                                str, blacklisted_items
                                        ):
                                            has_blacklisted_items = True
                                            blacklisted_reasons.append(
                                                f"Using a blacklisted item: {item['name']}"
                                            )
                                            logging.info(
                                                f"Found blacklisted item: {item['id']} - {item['name']}"
                                            )

                                unrealistic_check = is_unrealistic and not any(
                                    str(item)
                                    in map(
                                        str,
                                        settings.get("ERLC", {}).get(
                                            "unrealistic_items_whitelist", []
                                        ),
                                    )
                                    for item in result.get("unrealistic_item_ids", [])
                                )

                                if unrealistic_check or has_blacklisted_items:
                                    logging.info(
                                        f"Avatar check failed - Unrealistic: {unrealistic_check}, Has blacklisted items: {has_blacklisted_items}"
                                    )

                                    reasons = (
                                            result.get("reasons", []) + blacklisted_reasons
                                    )

                                    channel_id = settings["ERLC"]["avatar_check"][
                                        "channel"
                                    ]
                                    guild = bot.get_guild(
                                        guild_id
                                    ) or await bot.fetch_guild(guild_id)
                                    channel = await fetch_get_channel(guild, channel_id)
                                    if channel:
                                        try:
                                            user = await bot.roblox.get_user(
                                                int(user_id)
                                            )
                                            avatar = await bot.roblox.thumbnails.get_user_avatar_thumbnails(
                                                [user],
                                                type=roblox.thumbnails.AvatarThumbnailType.headshot,
                                            )
                                            avatar_url = avatar[0].image_url
                                        except Exception as e:
                                            logging.error(
                                                f"Error fetching user data: {e}"
                                            )
                                            return embeds, latest_timestamp

                                        view = AvatarCheckView(
                                            bot,
                                            user_id,
                                            settings["ERLC"]["avatar_check"].get(
                                                "message", ""
                                            ),
                                        )
                                        await channel.send(
                                            content=", ".join(
                                                [
                                                    f"<@&{role}>"
                                                    for role in settings["ERLC"][
                                                    "avatar_check"
                                                ].get("mentioned_roles", [])
                                                ]
                                            ),
                                            embed=discord.Embed(
                                                title="Unrealistic Avatar Detected",
                                                description="We have detected that a player in your server has an unrealistic avatar.",
                                                color=0x2C2F33,
                                            )
                                            .add_field(
                                                name="Player Information",
                                                value=f"> **Username:** [{user.name}](https://roblox.com/users/{user_id}/profile)\n> **User ID:** {user_id}\n> **Reason:** {', '.join(reasons)}",
                                            )
                                            .set_thumbnail(url=avatar_url),
                                            view=view,
                                            allowed_mentions=discord.AllowedMentions.all(),
                                        )

                                        if settings["ERLC"]["avatar_check"].get(
                                                "message"
                                        ):
                                            await bot.scheduled_pm_queue.put(
                                                (
                                                    guild_id,
                                                    user.name,
                                                    settings["ERLC"]["avatar_check"][
                                                        "message"
                                                    ],
                                                )
                                            )
            except Exception as e:
                logging.error(f"Error in avatar check: {e}")

    return embeds, latest_timestamp


async def is_username_found(username: str, members: list[discord.Member]) -> bool:
    pattern = re.compile(re.escape(username), re.IGNORECASE)
    member_found = False
    for member in members:
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
    return member_found


async def send_welcome_message(
        bot, settings, guild_id, player_logs, last_timestamp
) -> int:
    """Send welcome messages to new players"""
    welcome_message = settings["ERLC"].get("welcome_message", "")

    player_names = {}
    for log in sorted(player_logs, key=lambda x: x.timestamp, reverse=True):
        if log.timestamp <= last_timestamp:
            break
        if log.timestamp <= bot.start_time:
            continue
        if log.type == "join":
            player_names[log.username] = log.timestamp
        else:
            if player_names.get(log.username, None) is not None:
                if player_names[log.username] < log.timestamp:
                    del player_names[log.username]
    players = player_names.keys()
    if len(players) == 0:
        return sorted(player_logs, key=lambda x: x.timestamp, reverse=True)[0].timestamp
    try:
        await bot.prc_api.run_command(
            guild_id, f":pm {','.join(players)} {welcome_message}"
        )
    except prc_api.ResponseFailure:
        pass
    return sorted(player_logs, key=lambda x: x.timestamp, reverse=True)[0].timestamp


async def check_automatic_shifts(bot, settings, guild_id, join_logs, ts: int) -> int:
    logging.info(f"Checking automatic shifts for server {guild_id}")
    automatic_shifts = settings["ERLC"].get("automatic_shifts", {}) or {}
    try:
        guild = bot.get_guild(guild_id) or await bot.fetch_guild(guild_id)
    except:
        return sorted(join_logs, key=lambda x: x.timestamp, reverse=True)[0].timestamp

    if automatic_shifts in [{}, None]:
        return sorted(join_logs, key=lambda x: x.timestamp, reverse=True)[0].timestamp

    if automatic_shifts["enabled"] is False:
        return sorted(join_logs, key=lambda x: x.timestamp, reverse=True)[0].timestamp

    try:
        players = await bot.prc_api.get_server_players(guild_id)
    except Exception as e:
        logging.info(f"Skipping {guild_id} (automatic shifts) because of exc: {e}")
        return sorted(join_logs, key=lambda x: x.timestamp, reverse=True)[0].timestamp

    new_players: list[Player] = list(
        filter(lambda x: x.permission != "Normal", players)
    )
    joins: list[JoinLeaveLog] = list(filter(lambda x: x.type == "join", join_logs))
    leaves: list[JoinLeaveLog] = list(filter(lambda x: x.type == "leave", join_logs))
    # quick check
    temp_linked = []
    for item in leaves:
        oauth2_user = await bot.oauth2_users.db.find_one(
            {"roblox_id": int(item.user_id)}
        )
        if oauth2_user:
            temp_linked.append(oauth2_user["discord_id"])
    discordid_to_shift = {
        x["UserID"]: x
        async for x in bot.shift_management.shifts.db.find(
            {
                "Guild": guild.id,
                "Type": automatic_shifts.get("type", "Default") or "Default",
                "EndEpoch": 0,
            }
        )
    }
    for item in temp_linked:
        if item in discordid_to_shift:
            shift = discordid_to_shift[item]
            await bot.shift_management.end_shift(shift["_id"], guild.id)
            member = guild.get_member(int(item))
            if not member:
                try:
                    member = await guild.fetch_member(int(item))
                except discord.HTTPException:
                    pass
            if not member:
                continue

            try:
                await member.send(
                    embed=discord.Embed(
                        title=f"{bot.emoji_controller.get_emoji('success')} Shift Ended",
                        description=f"Your shift has automatically been ended in the server **{guild.name}**.",
                        color=GREEN_COLOR,
                    )
                )
            except Exception as e:
                pass

    new_data = []
    username_to_player = {x.username: x for x in new_players}
    for item in joins:
        if item.username not in username_to_player.keys():
            continue
        player_obj = username_to_player[item.username]
        if item.timestamp > ts:
            new_data.append(
                {
                    "Username": item.username,
                    "UserID": item.user_id,
                    "Permission": player_obj.permission,
                    "Timestamp": item.timestamp,
                }
            )

    linked_users = []
    for item in new_data:
        uid = item["UserID"]
        doc = await bot.oauth2_users.db.find_one({"roblox_id": int(uid)})
        if doc is not None:
            discord_uid = doc["discord_id"]
            consent_doc = await bot.consent.db.find_one({"_id": discord_uid}) or {
                "automatic_shifts": True
            }
            if consent_doc.get("automatic_shifts", True) is True:
                member = guild.get_member(discord_uid)
                if not member:
                    try:
                        member = await guild.fetch_member(discord_uid)
                    except:
                        pass
                if not member:
                    continue
                linked_users.append(member)

    staff_members = []
    for item in linked_users:
        if await staff_check(bot, guild, item) is True:
            staff_members.append(item)

    for item in staff_members:
        if await bot.shift_management.get_current_shift(item, guild.id) is None:
            oid = await bot.shift_management.add_shift_by_user(
                item, automatic_shifts.get("type", "Default") or "Default", [], guild.id
            )
            try:
                await item.send(
                    embed=discord.Embed(
                        title=f"{bot.emoji_controller.get_emoji('success')} Shift Started",
                        description=f"Your shift has automatically been started in the server **{guild.name}**.",
                        color=GREEN_COLOR,
                    )
                )
            except Exception as e:
                pass

    return sorted(join_logs, key=lambda x: x.timestamp, reverse=True)[0].timestamp


async def check_team_restrictions(bot, settings, guild_id, players):
    """Check and enforce team restrictions"""
    logging.info(f"Checking team restrictions for server {guild_id}")
    team_restrictions = settings["ERLC"].get("team_restrictions", {})
    if team_restrictions in [None, {}]:
        return
    teams = {}
    for item in players:
        if teams.get(item.team):
            teams[item.team].append(item)
        else:
            teams[item.team] = [item]

    load_against = []  # [Username]
    pm_against = {}  # Message: [Username]
    send_to = {}  # Channel_ID: [Username, Team]
    kick_against = []  # [Username]

    min_count_for_compute = team_restrictions.get("min_players", 0)
    if min_count_for_compute >= len(players):
        return

    enabled = team_restrictions.get("enabled", True)
    if not enabled:
        return

    guild = bot.get_guild(guild_id) or await bot.fetch_guild(guild_id)
    all_roles = await guild.fetch_roles()
    for team_name, plrs in teams.items():
        if team_restrictions.get(team_name) is not None:
            restriction = team_restrictions.get(team_name)
            roles = restriction["required_roles"]
            if roles == []:
                continue
            actual_roles = [discord.utils.get(all_roles, id=r) for r in roles]
            members = set()
            for item in actual_roles:
                [members.update(member.id) for member in item.members]

            for plr in plrs:
                members = [
                    guild.get_member(m) or await guild.fetch_member(m) for m in members
                ]
                is_found = await is_username_found(plr.username, members)
                if not is_found:
                    do_load = restriction["load_player"]
                    if do_load:
                        load_against.append(plr.username)
                    if restriction["warn_player"]:
                        if pm_against.get(restriction["warning_message"]) is not None:
                            pm_against[restriction["warning_message"]].append(
                                plr.username
                            )
                        else:
                            pm_against[restriction["warning_message"]] = [plr.username]
                    if restriction["notification_channel"] != 0:
                        if not isinstance(
                                send_to.get(restriction["notification_channel"]), list
                        ):
                            send_to[restriction["notification_channel"]] = [
                                [plr.username, plr.team]
                            ]
                        else:
                            send_to[restriction["notification_channel"]].append(
                                [plr.username, plr.team]
                            )
                    if restriction["kick_after_infractions"] != 0:
                        if bot.team_restrictions_infractions.get(guild_id) is not None:
                            if not bot.team_restrictions_infractions[guild_id].get(
                                    plr.username
                            ):
                                bot.team_restrictions_infractions[guild_id][
                                    plr.username
                                ] = 1
                            else:
                                bot.team_restrictions_infractions[guild_id][
                                    plr.username
                                ] += 1
                        else:
                            bot.team_restrictions_infractions[guild_id] = {
                                plr.username: 1
                            }
                        if (
                                bot.team_restrictions_infractions[guild_id][plr.username]
                                >= restriction["kick_after_infractions"]
                        ):
                            kick_against.append(plr.username)
                            bot.team_restrictions_infractions[guild_id][
                                plr.username
                            ] = 0
    if len(load_against) > 0:
        filtered_load = [
            username
            for username in load_against
            if username.strip() and len(username.strip()) >= 3
        ]
        if filtered_load:
            cmd = f":load {','.join(filtered_load)}"
            try:
                await bot.prc_api.run_command(guild_id, cmd)
            except:
                logging.warning("PRC API Rate limit reached when loading.")
        else:
            logging.warning(
                "Skipped sending load command - usernames too short or empty"
            )

    for message, plrs_to_send in pm_against.items():
        try:
            await bot.scheduled_pm_queue.put(
                (guild_id, ",".join(plrs_to_send), message)
            )
            logging.warning("Added to scheduled PM queue.")
        except Exception as e:
            logging.warning("PRC API Rate limit reached when PMing.")
    if len(kick_against) > 0:
        try:
            await bot.prc_api.run_command(guild_id, f":kick {','.join(kick_against)}")
        except:
            logging.warning("PRC API Rate limit reached when kicking.")
    send_by_teams = {}
    team_to_channel = {}
    for channel, players_team_unions in send_to.items():
        for player_team_union in players_team_unions:
            if send_by_teams.get(player_team_union[1]) is None:
                send_by_teams[player_team_union[1]] = [player_team_union[0]]
                team_to_channel[player_team_union[1]] = channel
            else:
                send_by_teams[player_team_union[1]].append(player_team_union[0])
    for team, channel in team_to_channel.items():
        players = send_by_teams[team]
        mentioned_roles = team_restrictions[team]["mentioned_roles"]
        missing_roles = team_restrictions[team]["required_roles"]
        try:
            channel = await fetch_get_channel(guild, channel)
        except discord.HTTPException:
            continue
        per_user_action_list = ""
        for index, item in enumerate(players):
            per_user_action_list += f"- **{index + 1}.** {item}\n  - **Actions:** "
            preappended_items = 0
            if item.lower() in [i.lower() for i in kick_against]:
                per_user_action_list += "Kicked"
                preappended_items += 1
            users_to_pm = pm_against.values()
            total_users = []
            for userlist in users_to_pm:
                for user in userlist:
                    if user.lower() not in total_users:
                        total_users.append(user.lower())
            if (
                    item.lower() in total_users
            ):  # This whole thing is entirely overengineered, and I should've just used
                # ','.join(list) but I didn't realise this before writing this whole
                # algorithm :skull:
                if preappended_items > 0:
                    per_user_action_list += ", Private Messaged"
                else:
                    per_user_action_list += "Private Messaged"
                preappended_items += 1
            if item.lower() in [i.lower() for i in load_against]:
                if preappended_items > 0:
                    per_user_action_list += ", Loaded"
                else:
                    per_user_action_list += "Loaded"
                preappended_items += 1
            per_user_action_list += "\n"
        embed = discord.Embed(
            title="Team Restrictions",
            description=f"Your team restriction for the `{team}` team has affected **{len(players)}** players.",
            color=BLANK_COLOR,
        ).add_field(
            name=f"Players Affected [{len(players)}]",
            inline=False,
            value=per_user_action_list,
        )

        await channel.send(
            ", ".join([f"<@&{role}>" for role in mentioned_roles]),
            embed=embed,
            allowed_mentions=discord.AllowedMentions.all(),
        )


async def handle_kick_timer(bot, settings, guild_id, player_logs, command_logs):
    """Handle kick timer logic using command logs"""
    kick_timer_settings = settings["ERLC"]["kick_timer"]
    punishment = kick_timer_settings.get("punishment", "ban")
    time_limit = kick_timer_settings.get(
        "time", 1800
    )  # default to 30 minutes if not set

    if not hasattr(bot, "kicked_users"):
        bot.kicked_users = {}

    if guild_id not in bot.kicked_users:
        bot.kicked_users[guild_id] = {}

    for log in command_logs:
        if ":kick" in log.command.lower():
            parts = log.command.split(None, 1)
            if len(parts) > 1:
                kicked_users = parts[1].split(",")
                for username in kicked_users:
                    username = username.strip()
                    if username:
                        bot.kicked_users[guild_id][username.lower()] = log.timestamp

    rejoined_users = []
    current_time = int(time.time())
    if guild_id in bot.kicked_users:
        bot.kicked_users[guild_id] = {
            username: timestamp 
            for username, timestamp in bot.kicked_users[guild_id].items()
            if (current_time - timestamp) <= time_limit
        }

    for log in player_logs:
        if log.type == "join":
            username_lower = log.username.lower()
            if username_lower in bot.kicked_users[guild_id]:
                kick_timestamp = bot.kicked_users[guild_id][username_lower]
                if (current_time - kick_timestamp) <= time_limit:
                    rejoined_users.append(log.username)
                    logging.warning(
                        f"Found rejoin within timer: {log.username} (Kicked at: {kick_timestamp}, Rejoined at: {current_time})"
                    )
                del bot.kicked_users[guild_id][username_lower]

    if rejoined_users:
        usernames_str = ",".join(rejoined_users)
        logging.warning(f"Executing {punishment} for rejoined users: {usernames_str}")

        if punishment == "ban":
            try:
                await bot.prc_api.run_command(guild_id, f":ban {usernames_str}")
            except Exception as e:
                logging.error(f"Failed to ban users: {e}")
        else:
            try:
                await bot.prc_api.run_command(guild_id, f":kick {usernames_str}")
            except Exception as e:
                logging.error(f"Failed to kick users: {e}")

        for username in rejoined_users:
            try:
                user_data = next(
                    (
                        log
                        for log in player_logs
                        if log.username.lower() == username.lower()
                    ),
                    None,
                )
                if user_data:
                    await bot.punishments.insert_warning(
                        staff_id=978662093408591912,
                        staff_name="ERM Systems",
                        user_id=user_data.user_id,
                        user_name=username,
                        guild_id=guild_id,
                        reason="Rejoined within kick timer",
                        moderation_type=punishment,
                        time_epoch=current_time,
                    )
            except Exception as e:
                logging.error(f"Failed to log punishment for {username}: {e}")
