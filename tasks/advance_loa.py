import datetime

import discord
from decouple import config
from discord.ext import commands, tasks

from utils.constants import RED_COLOR, BLANK_COLOR


@tasks.loop(minutes=1, reconnect=True)
async def advance_loa(bot):
    filter_map = (
        {"guild_id": int(config("CUSTOM_GUILD_ID", default=0))}
        if config("ENVIRONMENT") == "CUSTOM"
        else {
            "guild_id": {
                "$nin": [
                    int(item["GuildID"] or 0)
                    async for item in bot.whitelabel.db.find({})
                ]
            }
        }
    )

    try:
        loas = bot.loas

        async for loaObject in bot.loas.db.find(filter_map):
            if (
                datetime.datetime.now().timestamp() > loaObject["started_at"]
                and loaObject["user_rolled"] is False
            ):
                if loaObject["accepted"] is True:
                    await bot.loas.update_by_id(loaObject)
                    guild = bot.get_guild(loaObject["guild_id"])
                    if guild:

                        member = guild.get_member(loaObject["user_id"])
                        settings = await bot.settings.find_by_id(guild.id)
                        roles = [None]
                        if settings is not None:
                            if "loa_role" in settings["staff_management"]:
                                try:
                                    if isinstance(
                                        settings["staff_management"]["loa_role"], int
                                    ):
                                        roles = [
                                            discord.utils.get(
                                                guild.roles,
                                                id=settings["staff_management"][
                                                    "loa_role"
                                                ],
                                            )
                                        ]
                                    elif isinstance(
                                        settings["staff_management"]["loa_role"], list
                                    ):
                                        roles = [
                                            discord.utils.get(guild.roles, id=role)
                                            for role in settings["staff_management"][
                                                "loa_role"
                                            ]
                                        ]
                                except KeyError:
                                    pass

                        docs = bot.loas.db.find(
                            {
                                "user_id": loaObject["user_id"],
                                "guild_id": loaObject["guild_id"],
                                "accepted": True,
                                "expired": False,
                                "denied": False,
                                "type": loaObject["type"],
                            }
                        )
                        should_add_roles = True
                        async for doc in docs:
                            if not doc == loaObject:
                                should_add_roles = False
                                break

                        if should_add_roles:
                            for role in roles:
                                if role is not None:
                                    if member:
                                        if role in member.roles:
                                            try:
                                                await member.add_roles(
                                                    role,
                                                    reason="LOA Started",
                                                    atomic=True,
                                                )
                                            except discord.HTTPException:
                                                pass
                        if member:
                            try:
                                await member.send(
                                    embed=discord.Embed(
                                        title=f"{loaObject['type']} Started!",
                                        description=f"Your {loaObject['type']} has started in **{guild.name}**.",
                                        color=BLANK_COLOR,
                                    )
                                )
                            except discord.Forbidden:
                                pass
    except ValueError:
        pass
