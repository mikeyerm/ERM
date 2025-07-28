import copy
import datetime
import logging
import string

import aiohttp
import discord
import num2words
import roblox
from decouple import config
from discord.ext import commands
from reactionmenu import Page, ViewButton, ViewMenu, ViewSelect

from utils.prc_api import Player
from utils.constants import BLANK_COLOR, GREEN_COLOR
from utils.utils import generator
from utils.utils import interpret_content, interpret_embed
from menus import CustomSelectMenu, GameSecurityActions
from utils.timestamp import td_format
from utils.utils import get_guild_icon, get_prefix, invis_embed


class OnMessage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message):
        bot = self.bot
        bypass_role = None

        if self.bot.environment == "PRODUCTION":
            if await bot.whitelabel.db.find_one({"Guild": str(message.guild.id)}) is not None:
                return
       
        if not hasattr(bot, "settings"):
            return

        if message.author == bot.user:
            return

        if not message.guild:
            return

        dataset = await bot.settings.find_by_id(message.guild.id)
        if dataset == None:
            return

        antiping_roles = None
        bypass_roles = None

        if "bypass_role" in dataset["antiping"].keys():
            bypass_role = dataset["antiping"]["bypass_role"]

        if isinstance(bypass_role, list):
            bypass_roles = [
                discord.utils.get(message.guild.roles, id=role) for role in bypass_role
            ]
        else:
            bypass_roles = [discord.utils.get(message.guild.roles, id=bypass_role)]

        if isinstance(dataset["antiping"]["role"], list):
            antiping_roles = [
                discord.utils.get(message.guild.roles, id=role)
                for role in dataset["antiping"]["role"]
            ]
        elif isinstance(dataset["antiping"]["role"], int):
            antiping_roles = [
                discord.utils.get(message.guild.roles, id=dataset["antiping"]["role"])
            ]
        else:
            antiping_roles = None

        aa_detection = False
        aa_detection_channel = None
        webhook_channel = None
        remote_commands = False
        remote_command_channel = None

        if dataset.get("ERLC", {}).get("remote_commands"):
            remote_commands = True
            remote_command_channel = (
                dataset["ERLC"]["remote_commands"]["webhook_channel"]
                if dataset["ERLC"]["remote_commands"].get("webhook_channel", None)
                else None
            )

        if "game_security" in dataset.keys():
            if "enabled" in dataset["game_security"].keys():
                if (
                    "channel" in dataset["game_security"].keys()
                    and "webhook_channel" in dataset["game_security"].keys()
                ):
                    if dataset["game_security"]["enabled"] is True:
                        aa_detection = True
                        webhook_channel = dataset["game_security"]["webhook_channel"]
                        webhook_channel = discord.utils.get(
                            message.guild.channels, id=webhook_channel
                        )
                        aa_detection_channel = dataset["game_security"]["channel"]
                        aa_detection_channel = discord.utils.get(
                            message.guild.channels, id=aa_detection_channel
                        )

                        if webhook_channel != None:
                            if message.channel.id == webhook_channel.id:
                                for embed in message.embeds:
                                    if embed.description not in [
                                        "",
                                        None,
                                    ] and embed.title not in [
                                        "",
                                        None,
                                    ]:
                                        if (
                                            "kicked" in embed.description
                                            or "banned" in embed.description
                                        ):
                                            if (
                                                "Players Kicked" in embed.title
                                                or "Players Banned" in embed.title
                                            ):
                                                raw_content = embed.description

                                                if "kicked" in raw_content:
                                                    user, command = raw_content.split(
                                                        " kicked `"
                                                    )
                                                else:
                                                    user, command = raw_content.split(
                                                        " banned `"
                                                    )

                                                command = command.replace("`", "")
                                                code = embed.footer.text.split(
                                                    "Server: "
                                                )[1]
                                                if command.count(",") + 1 >= 5:
                                                    people_affected = (
                                                        command.count(",") + 1
                                                    )
                                                    roblox_user = user.split(":")[
                                                        0
                                                    ].replace("[", "")

                                                    roblox_client = roblox.Client()
                                                    roblox_player = await roblox_client.get_user_by_username(
                                                        roblox_user
                                                    )
                                                    if not roblox_player:
                                                        return
                                                    thumbnails = await roblox_client.thumbnails.get_user_avatar_thumbnails(
                                                        [roblox_player], size=(420, 420)
                                                    )
                                                    thumbnail = thumbnails[0].image_url

                                                    embed = (
                                                        discord.Embed(
                                                            title=f"{self.bot.emoji_controller.get_emoji('security')} Abuse Detected",
                                                            color=BLANK_COLOR,
                                                        )
                                                        .add_field(
                                                            name="Staff Information",
                                                            value=(
                                                                f"> **Username:** {roblox_player.name}\n"
                                                                f"> **User ID:** {roblox_player.id}\n"
                                                                f"> **Profile Link:** [Click here](https://roblox.com/users/{roblox_player.id}/profile)\n"
                                                                f"> **Account Created:** <t:{int(roblox_player.created.timestamp())}>"
                                                            ),
                                                            inline=False,
                                                        )
                                                        .add_field(
                                                            name="Abuse Information",
                                                            value=(
                                                                f"> **Type:** {'Mass-Kick' if 'kicked' in raw_content else 'Mass-Ban'}\n"
                                                                f"> **Individuals Affected [{command.count(',')+1}]:** {command}\n"
                                                                f"> **At:** <t:{int(message.created_at.timestamp())}>"
                                                            ),
                                                            inline=False,
                                                        )
                                                        .set_thumbnail(url=thumbnail)
                                                    )
                                                    view = GameSecurityActions(bot)
                                                    if not "kicked" in raw_content:
                                                        view.enable_reflective_action()

                                                    pings = []
                                                    pings = [
                                                        (
                                                            (
                                                                message.guild.get_role(
                                                                    role_id
                                                                )
                                                            ).mention
                                                            if message.guild.get_role(
                                                                role_id
                                                            )
                                                            else None
                                                        )
                                                        for role_id in dataset.get(
                                                            "game_security", {}
                                                        ).get("role", [])
                                                    ]
                                                    pings = list(
                                                        filter(
                                                            lambda x: x is not None,
                                                            pings,
                                                        )
                                                    )

                                                    await aa_detection_channel.send(
                                                        (
                                                            ",".join(pings)
                                                            if pings != []
                                                            else ""
                                                        ),
                                                        embed=embed,
                                                        allowed_mentions=discord.AllowedMentions(
                                                            everyone=True,
                                                            users=True,
                                                            roles=True,
                                                            replied_user=True,
                                                        ),
                                                        view=view,
                                                    )
        if (
            remote_commands
            and remote_command_channel is not None
            and message.channel.id in [remote_command_channel]
        ):
            for embed in message.embeds:
                if not embed.description or not embed.title:
                    continue

                if "Player Kicked" in embed.title:
                    action_type = "Kick"
                elif "Player Banned" in embed.title:
                    action_type = "Ban"
                else:
                    continue

                raw_content = embed.description

                if ("kicked" not in raw_content and action_type == "Kick") or (
                    "banned" not in raw_content and action_type == "Ban"
                ):
                    continue

                try:
                    if action_type == "Kick":
                        user_info, command_info = raw_content.split("kicked ", 1)
                    else:
                        user_info, command_info = raw_content.split("banned ", 1)

                    user_info = user_info.strip()
                    command_info = command_info.strip()
                    roblox_user = (
                        user_info.split(":")[0]
                        .replace("[", "")
                        .replace("]", "")
                        .strip()
                    )
                    profile_link = user_info.split("(")[1].split(")")[0].strip()
                    roblox_id_str = profile_link.split("/")[-2]

                    if not roblox_id_str.isdigit():
                        raise ValueError(
                            f"Extracted Roblox ID is not a number: {roblox_id_str}"
                        )

                    roblox_id = int(roblox_id_str)

                    reason = command_info.split("`")[1].strip()
                except (IndexError, ValueError):
                    continue

                discord_user = 0
                async for document in bot.oauth2_users.db.find(
                    {"roblox_id": roblox_id}
                ):
                    discord_user = document["discord_id"]

                if discord_user == 0:
                    await message.add_reaction("❌")
                    return await message.add_reaction("6️⃣")

                user = discord.utils.get(message.guild.members, id=discord_user)
                if not user:
                    try:
                        user = await message.guild.fetch_member(discord_user)
                    except Exception as e:
                        await message.add_reaction("❌")
                        return await message.add_reaction("7️⃣")

                new_message = copy.copy(message)
                new_message.author = user
                prefix = (await get_prefix(bot, message))[-1]
                reason_info = command_info.split("`")[1].strip()
                split_index = reason_info.find(" ")
                if split_index != -1:
                    violator_user = reason_info[:split_index].strip()
                    reason = reason_info[split_index:].strip()
                else:
                    await message.add_reaction("❌")
                    return await message.add_reaction(
                        "🚫"
                    )  # return since no reason was
                if reason.endswith("- Player Not In Game"):
                    reason = reason[: -len("- Player Not In Game")]
                if not reason:
                    await message.add_reaction("❌")
                    return await message.add_reaction(
                        "🚫"
                    )  # return since no reason was provided
                new_message.content = (
                    f"{prefix}punish {violator_user} {action_type} {reason}"
                )
                await bot.process_commands(new_message)

        if (
            remote_commands
            and remote_command_channel is not None
            and message.channel.id in [remote_command_channel]
        ):
            for embed in message.embeds:
                if embed.description in ["", None] and embed.title in ["", None]:
                    break

                if (
                    ":bring" in embed.description.lower()
                    or ":tp" in embed.description.lower()
                    or ":kick" in embed.description.lower()
                    or ":ban" in embed.description.lower()
                ):
                    async with aiohttp.ClientSession(
                        headers={
                            "Content-Type": "application/json",
                            "X-Static-Token": config("PANEL_STATIC_AUTH"),
                        }
                    ) as session:
                        async with session.post(
                            url=f"{config('PANEL_API_URL')}/Internal/{message.guild.id}/SyncWebhookLogs",
                            data={"content": embed.description.split("`")[1].strip()},
                        ) as resp:
                            if resp.status != 200:
                                pass

        if (
            remote_commands
            and remote_command_channel is not None
            and message.channel.id in [remote_command_channel]
        ):
            for embed in message.embeds:
                if embed.description in ["", None] and embed.title in ["", None]:
                    break

                if not ":log" in embed.description:
                    break

                if "Command Usage" not in embed.title:
                    break

                raw_content = embed.description
                user, command = raw_content.split("used the command: ")

                profile_link = user.split("(")[1].split(")")[0]
                user = user.split("(")[0].replace("[", "").replace("]", "")
                try:
                    person = command.split(" ")[1]
                except IndexError:
                    logging.error("IndexError in remote command usage embed")
                    break
                # Adding check for the command to see if only admin is using the ban command

                players: list[Player] = await self.bot.prc_api.get_server_players(
                    message.guild.id
                )
                try:
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

                    # Create a map for key roles
                    new_maps = [
                        "Server Owners",
                        "Server Administrators",
                        "Server Moderators",
                    ]
                    new_vals = [
                        key_maps.get("Server Owner", [])
                        + key_maps.get("Server Co-Owner", []),
                        key_maps.get("Server Administrator", []),
                        key_maps.get("Server Moderator", []),
                    ]
                    new_keymap = dict(zip(new_maps, new_vals))

                    user_permission = None
                    for role, players in new_keymap.items():
                        if any(plr.username == user for plr in players):
                            user_permission = role
                            break

                    # If the user is a Server Moderator and used the ban command
                    if user_permission == "Server Moderators" and "ban" in command:
                        await message.add_reaction("⛔")
                        return
                except Exception as e:
                    logging.error(f"Error checking command permissions: {e}")
                    continue

                combined = ""
                for word in command.split(" ")[1:]:
                    if not bot.get_command(combined.strip()):
                        combined += word + " "
                    else:
                        item = bot.get_command(combined.strip())
                        if isinstance(item, commands.HybridCommand) and not isinstance(
                            item, commands.HybridGroup
                        ):
                            break
                        else:
                            combined += word + " "

                invoked_command = " ".join(combined.replace("`", "").split(" ")[:-1])
                _cmd = command

                discord_user = 0
                async for document in bot.oauth2_users.db.find(
                    {"roblox_id": int(profile_link.split("/")[4])}
                ):
                    discord_user = document["discord_id"]

                if discord_user == 0:
                    await message.add_reaction("❌")
                    return await message.add_reaction("6️⃣")

                user = discord.utils.get(message.guild.members, id=discord_user)
                if not user:
                    user = await message.guild.fetch_member(discord_user)
                    if not user:
                        await message.add_reaction("❌")
                        return await message.add_reaction("7️⃣")

                command = bot.get_command(invoked_command.lower().strip())
                if not command:
                    await message.add_reaction("❌")
                    return await message.add_reaction("8️⃣")

                new_message = copy.copy(message)
                new_message.channel = await user.create_dm()
                new_message.author = user
                actual_username = next(
                    (
                        player.username
                        for player in actual_players
                        if person in player.username
                    ),
                    person,
                )
                new_message.content = (
                    (await get_prefix(bot, message))[-1]
                ) + _cmd.split(":log ")[1].split("`")[0].replace(
                    person, actual_username
                )
                await bot.process_commands(new_message)

        if isinstance(message.author, discord.User):
            return

        if message.author.bot:
            return

        if antiping_roles is None:
            return

        if (
            dataset["antiping"]["enabled"] is False
            or dataset["antiping"]["role"] is None
        ):
            return

        if bypass_roles is not None:
            for role in bypass_roles:
                if role in message.author.roles:
                    return

        for mention in message.mentions:
            if mention.bot:
                return

            if dataset["antiping"].get("use_hierarchy") in [True, None]:
                for role in antiping_roles:
                    if role is not None:
                        if message.author.top_role >= role:
                            continue
                if message.author == message.guild.owner:
                    return

                for role in antiping_roles:
                    if role is not None:
                        if role in mention.roles and role not in message.author.roles:
                            embed = discord.Embed(
                                title=f"Do not ping {role.name} or above!",
                                color=discord.Color.red(),
                                description=f"Do not ping those with {role.name}!\nIt is a violation of the rules, and you will be punished if you continue.",
                            )
                            try:
                                if message.reference:
                                    msg = await message.channel.fetch_message(
                                        message.reference.message_id
                                    )
                                    if msg.author == mention:
                                        embed.set_image(
                                            url="https://i.imgur.com/pXesTnm.gif"
                                        )
                            except discord.NotFound:
                                pass
                            try:
                                embed.set_footer(
                                    text=f'Thanks, {dataset["customisation"]["brand_name"]}',
                                    icon_url=get_guild_icon(bot, message.guild),
                                )
                            except KeyError:
                                embed.set_footer(
                                    text=f"Thanks, ERM",
                                    icon_url=get_guild_icon(bot, message.guild),
                                )

                            ctx = await bot.get_context(message)
                            await ctx.reply(
                                f"{message.author.mention}",
                                embed=embed,
                                delete_after=15,
                            )
                            return

            if dataset["antiping"].get("use_hierarchy") not in [True, None]:
                for role in antiping_roles:
                    if role is not None:
                        if role in mention.roles and role not in message.author.roles:
                            embed = discord.Embed(
                                title=f"Do not ping {role.name}!",
                                color=discord.Color.red(),
                                description=f"Do not ping those with {role.name}!\nIt is a violation of the rules, and you will be punished if you continue.",
                            )
                            try:
                                if message.reference:
                                    msg = await message.channel.fetch_message(
                                        message.reference.message_id
                                    )
                                    if msg.author == mention:
                                        embed.set_image(
                                            url="https://i.imgur.com/pXesTnm.gif"
                                        )
                            except discord.NotFound:
                                pass
                            try:
                                embed.set_footer(
                                    text=f'Thanks, {dataset["customisation"]["brand_name"]}',
                                    icon_url=get_guild_icon(bot, message.guild),
                                )
                            except KeyError:
                                embed.set_footer(
                                    text=f"Thanks, ERM",
                                    icon_url=get_guild_icon(bot, message.guild),
                                )

                            ctx = await bot.get_context(message)
                            await ctx.reply(
                                f"{message.author.mention}",
                                embed=embed,
                                delete_after=15,
                            )
                            return

        custom_commands = await bot.custom_commands.find_by_id(message.guild.id)
        if custom_commands is None:
            return

        prefix = (dataset or {}).get("customisation", {}).get("prefix", ">")
        management_roles = dataset.get("staff_management", {}).get("management_role")
        if management_roles is None:
            return

        if message.content.startswith(prefix):
            try:
                command_parts = message.content.split(" ")
                command = command_parts[0].replace(prefix, "").lower()
                if command in bot.all_commands:
                    return
                channel_id = int(command_parts[1].replace("<#", "").replace(">", ""))
                channel = discord.utils.get(message.guild.text_channels, id=channel_id)
            except (IndexError, ValueError):
                command = message.content.replace(prefix, "").lower()
                channel = None

            ctx = await bot.get_context(message)
            if "commands" in custom_commands:
                if isinstance(custom_commands["commands"], list):
                    selected = next(
                        (
                            cmd
                            for cmd in custom_commands["commands"]
                            if cmd["name"].lower().replace(" ", "")
                            == command.lower().replace(" ", "")
                        ),
                        None,
                    )
                    is_command = selected is not None
                else:
                    is_command = False
            else:
                is_command = False

            if not is_command:
                return

            if not channel:
                channel = ctx.channel

            embeds = [
                await interpret_embed(bot, ctx, channel, embed, selected["id"])
                for embed in selected["message"]["embeds"]
            ]

            view = discord.ui.View()
            for item in selected.get("buttons", []):
                view.add_item(
                    discord.ui.Button(
                        label=item["label"],
                        url=item["url"],
                        row=item["row"],
                        style=discord.ButtonStyle.url,
                    )
                )

            if ctx.interaction:
                if (
                    not selected["message"]["content"]
                    and not selected["message"]["embeds"]
                ):
                    return await ctx.interaction.followup.send(
                        embed=discord.Embed(
                            title="Empty Command",
                            description="Due to Discord limitations, I am unable to send your reminder. Your message is most likely empty.",
                            color=discord.Color.red(),
                        )
                    )
                await ctx.interaction.followup.send(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('success')} Command Ran",
                        description=f"I've just ran the custom command in {channel.mention}.",
                        color=discord.Color.green(),
                    )
                )
                msg = await channel.send(
                    content=await interpret_content(
                        bot,
                        ctx,
                        channel,
                        selected["message"]["content"],
                        selected["id"],
                    ),
                    embeds=embeds,
                    view=view,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=True, users=True, roles=True, replied_user=True
                    ),
                )
            else:
                if (
                    not selected["message"]["content"]
                    and not selected["message"]["embeds"]
                ):
                    return await ctx.reply(
                        embed=discord.Embed(
                            title="Empty Command",
                            description="Due to Discord limitations, I am unable to send your reminder. Your message is most likely empty.",
                            color=discord.Color.red(),
                        )
                    )
                await ctx.reply(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('success')} Command Ran",
                        description=f"I've just ran the custom command in {channel.mention}.",
                        color=discord.Color.green(),
                    )
                )
                msg = await channel.send(
                    content=await interpret_content(
                        bot,
                        ctx,
                        channel,
                        selected["message"]["content"],
                        selected["id"],
                    ),
                    embeds=embeds,
                    view=view,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=True, users=True, roles=True, replied_user=True
                    ),
                )

            doc = await bot.ics.find_by_id(selected["id"]) or {}
            if doc is None:
                return
            doc["associated_messages"] = (
                [(channel.id, msg.id)]
                if not doc.get("associated_messages")
                else doc["associated_messages"] + [(channel.id, msg.id)]
            )
            doc["_id"] = ctx.guild.id
            await bot.ics.update_by_id(doc)

        return


async def setup(bot):
    await bot.add_cog(OnMessage(bot))
