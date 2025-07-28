import logging

import discord
from discord.ext import commands, tasks
import datetime

from menus import CompleteReminder
from utils import prc_api
import pytz
from utils.constants import BLANK_COLOR
import aiohttp
from decouple import config


async def iterate_reminder(bot, guildObj): # TODO: do a refactor of this.. this is abundantly terrible programming.
    if await bot.whitelabel.db.find_one({"GuildID": str(guildObj["_id"])}) is not None and bot.environment == "PRODUCTION":
        return

    for item in guildObj["reminders"].copy():
        if item.get("paused") is True:
            continue

        current_time = datetime.datetime.now(tz=pytz.UTC)
        interval = item["interval"]

        next_time = current_time + datetime.timedelta(seconds=interval)

        if next_time.timestamp() - item["lastTriggered"] >= interval:
            guild = bot.get_guild(int(guildObj["_id"]))
            if not guild:
                continue
            channel = guild.get_channel(int(item["channel"]))
            if not channel:
                continue

            roles = []
            try:
                for role in item["role"]:
                    roles.append(guild.get_role(int(role)).mention)
            except TypeError:
                roles = [""]

            if (
                    item.get("completion_ability")
                    and item.get("completion_ability") is True
            ):
                view = CompleteReminder(bot)
            else:
                view = None
            embed = discord.Embed(
                title="Notification",
                description=f"{item['message']}",
                color=BLANK_COLOR,
            )

            lastTriggered = next_time.timestamp()
            item["lastTriggered"] = lastTriggered
            await bot.reminders.update_by_id(guildObj)

            if isinstance(item.get("integration"), dict):
                # This has the ERLC integration enabled
                command = (
                    "h"
                    if item["integration"]["type"] == "Hint"
                    else (
                        "m"
                        if item["integration"]["type"] == "Message"
                        else None
                    )
                )
                content = item["integration"]["content"]
                total = ":" + command + " " + content
                if (
                        await bot.server_keys.db.count_documents(
                            {"_id": channel.guild.id}
                        )
                        != 0
                ):
                    do_not_complete = False
                    try:
                        status = await bot.prc_api.get_server_status(
                            channel.guild.id
                        )
                    except prc_api.ResponseFailure:
                        do_not_complete = True

                    if not do_not_complete:
                        resp = await bot.prc_api.run_command(
                            channel.guild.id, total
                        )
                        if resp[0] != 200:
                            logging.info(
                                "Failed reaching PRC due to {} status code".format(
                                    resp
                                )
                            )
                        else:
                            logging.info(
                                "Integration success with 200 status code"
                            )
                    else:
                        logging.info(
                            f"Cancelled execution of reminder for {channel.guild.id}"
                        )

            if not view:
                await channel.send(
                    " ".join(roles),
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(
                        replied_user=True,
                        everyone=True,
                        roles=True,
                        users=True,
                    ),
                )
            else:
                await channel.send(
                    " ".join(roles),
                    embed=embed,
                    view=view,
                    allowed_mentions=discord.AllowedMentions(
                        replied_user=True,
                        everyone=True,
                        roles=True,
                        users=True,
                    ),
                )

            try:
                panel_url_var = config("PANEL_API_URL")
                if panel_url_var not in ["", None]:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                                f"{panel_url_var}/Internal/{channel.guild.id}/TriggerReminder",
                                headers={
                                    "Authorization": config(
                                        "INTERNAL_API_AUTH"
                                    ),
                                    "Content-Type": "application/json",
                                },
                                json={"message": item["message"]},
                        ):
                            pass
            except Exception as e:
                logging.warning(f"Failed to trigger reminder: {e}")



@tasks.loop(minutes=1)
async def check_reminders(bot):

    if bot.environment == "PRODUCTION":
        try:
            async for guildObj in bot.reminders.db.find({}):
                try:
                    await iterate_reminder(bot, guildObj)
                except Exception as e:
                    logging.warning(f"Reminder failed: {e}")
        except Exception as e:
            logging.warning(f"Reminder task failed: {e}")
    else:
        try:
            async for guildObj in bot.reminders.db.find({"_id": int(config("CUSTOM_GUILD_ID"))}):
                try:
                    await iterate_reminder(bot, guildObj)
                except Exception as e:
                    logging.warning(f"Reminder failed: {e}")
        except Exception as e:
            logging.warning(f"Reminder task failed: {e}")
