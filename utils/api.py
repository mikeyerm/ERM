import asyncio
import copy
import datetime
import typing

import aiohttp
import pytz
import uvicorn
from bson import ObjectId
from fastapi import FastAPI, APIRouter, Header, HTTPException, Request
from discord.ext import commands
import discord
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from erm import (
    Bot,
    management_predicate,
    is_staff,
    staff_predicate,
    staff_check,
    management_check,
    admin_check,
)
from typing import Annotated
from decouple import config
import copy
from menus import LOAMenu
from utils.constants import BLANK_COLOR, GREEN_COLOR
from utils.utils import get_elapsed_time, secure_logging
from pydantic import BaseModel

from utils.timestamp import td_format
from utils.utils import tokenGenerator, system_code_gen
import logging


logger = logging.getLogger(__name__)


class Identification(BaseModel):
    license: typing.Optional[typing.Any]
    discord: typing.Optional[typing.Any]
    source: typing.Literal["fivem", "discord"]


async def validate_authorization(bot: Bot, token: str, disable_static_tokens=False):
    # Check static and dynamic tokens
    if not disable_static_tokens:
        static_token = config("API_STATIC_TOKEN")  # Dashboard
        if token == static_token:
            return True
    token_obj = await bot.api_tokens.db.find_one({"token": token})
    if token_obj:
        if int(datetime.datetime.now().timestamp()) < token_obj["expires_at"]:
            return True
        else:
            return False
    else:
        return False


class APIRoutes:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.router = APIRouter()
        for i in dir(self):
            # # # print(i)
            if any(
                [i.startswith(a) for a in ("GET_", "POST_", "PATCH_", "DELETE_")]
            ) and not i.startswith("_"):
                x = i.split("_")[0]
                self.router.add_api_route(
                    f"/{i.removeprefix(x+'_')}",
                    getattr(self, i),
                    methods=[i.split("_")[0].upper()],
                )

    def GET_status(self):
        return {"guilds": len(self.bot.guilds), "ping": round(self.bot.latency * 1000)}

    async def POST_get_mutual_guilds(self, request: Request):
        json_data = await request.json()
        guild_ids = json_data.get("guilds")
        if not guild_ids:
            return HTTPException(status_code=400, detail="No guild ids given")

        guilds = []
        for i in guild_ids:
            guild: discord.Guild = self.bot.get_guild(int(i))
            if not guild:
                continue
            if guild.get_member(self.bot.user.id):
                try:
                    icon = guild.icon.with_size(512)
                    icon = icon.with_format("png")
                    icon = str(icon)
                except Exception as e:
                    # # # print(e)
                    icon = "https://cdn.discordapp.com/embed/avatars/0.png?size=512"

                guilds.append(
                    {"id": str(guild.id), "name": str(guild.name), "icon_url": icon}
                )

        return {"guilds": guilds}

    async def GET_shard_pings(self, authorization: Annotated[str | None, Header()]):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        shard_pings = {}
        for shard_id, shard in self.bot.shards.items():
            shard_pings[shard_id] = round(shard.latency * 1000, 2)

        return {"shard_pings": shard_pings}

    async def GET_guild_shard(
        self, authorization: Annotated[str | None, Header()], guild_id: int
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                raise HTTPException(status_code=404, detail="Guild not found")

            shard_id = guild.shard_id
            return {"guild_id": guild_id, "shard_id": shard_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")

    async def POST_approve_application(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        try:
            json_data = await request.json()
            user_id = int(json_data["user"])
            add_role_ids = json_data.get("roles", [])
            remove_role_ids = json_data.get("remove_roles", [])
            guild_id = int(json_data["guild"])
            submitted_on = json_data.get("submitted", 1)
            note = json_data.get("note", "Not provided.")
            application_name = json_data.get("application_name")

            guild = self.bot.get_guild(guild_id)
            if not guild:
                raise HTTPException(status_code=400, detail="Invalid Guild ID")

            try:
                user = await guild.fetch_member(user_id)
            except discord.NotFound:
                raise HTTPException(status_code=400, detail="User not found in guild")
            except Exception as e:
                raise HTTPException(
                    status_code=400, detail=f"Error fetching user: {str(e)}"
                )

            embed = discord.Embed(
                title=f"{self.bot.emoji_controller.get_emoji('success')} Application Accepted",
                description=f"Your application in **{guild.name}** has been accepted. Congratulations!\n\n**Application Information**\n> **Application Name:** {application_name}\n> **Submitted On:** <t:{submitted_on}>\n> **Note:** {note}",
                color=GREEN_COLOR,
            )

            try:
                await user.send(embed=embed)
            except discord.Forbidden:
                print(f"Could not send DM to user {user_id}")

            # Fetch and validate roles
            fetched_roles = await guild.fetch_roles()
            roles_to_add = []
            roles_to_remove = []

            # Process roles to add
            for role_id in add_role_ids:
                role = discord.utils.get(fetched_roles, id=int(role_id))
                if role:
                    roles_to_add.append(role)

            # Process roles to remove
            for role_id in remove_role_ids:
                role = discord.utils.get(fetched_roles, id=int(role_id))
                if role:
                    roles_to_remove.append(role)

            # Add roles
            if roles_to_add:
                try:
                    await user.add_roles(
                        *roles_to_add, reason="Application approved - roles added"
                    )
                except discord.Forbidden:
                    raise HTTPException(
                        status_code=403, detail="Bot lacks permission to manage roles"
                    )
                except Exception as e:
                    raise HTTPException(
                        status_code=400, detail=f"Error adding roles: {str(e)}"
                    )

            # Remove roles
            if roles_to_remove:
                try:
                    await user.remove_roles(
                        *roles_to_remove, reason="Application approved - roles removed"
                    )
                except discord.Forbidden:
                    raise HTTPException(
                        status_code=403, detail="Bot lacks permission to manage roles"
                    )
                except Exception as e:
                    raise HTTPException(
                        status_code=400, detail=f"Error removing roles: {str(e)}"
                    )

            return 200

        except ValueError as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid data format: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )

    async def POST_deny_application(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        try:
            json_data = await request.json()
            user_id = int(json_data["user"])
            add_role_ids = json_data.get("roles", [])
            remove_role_ids = json_data.get("remove_roles", [])
            guild_id = int(json_data["guild"])
            submitted_on = json_data.get("submitted", 1)
            note = json_data.get("note", "Not provided.")
            application_name = json_data.get("application_name")

            guild = self.bot.get_guild(guild_id)
            if not guild:
                raise HTTPException(status_code=400, detail="Invalid Guild ID")

            try:
                user = await guild.fetch_member(user_id)
            except discord.NotFound:
                raise HTTPException(status_code=400, detail="User not found in guild")
            except Exception as e:
                raise HTTPException(
                    status_code=400, detail=f"Error fetching user: {str(e)}"
                )

            embed = discord.Embed(
                title="Application Denied",
                description=f"Your application in **{guild.name}** has been denied.\n\n**Application Information**\n> **Application Name:** {application_name}\n> **Submitted On:** <t:{submitted_on}>\n> **Note:** {note}",
                color=BLANK_COLOR,
            )

            try:
                await user.send(embed=embed)
            except discord.Forbidden:
                print(f"Could not send DM to user {user_id}")

            # Fetch and validate roles
            fetched_roles = await guild.fetch_roles()
            roles_to_add = []
            roles_to_remove = []

            # Process roles to add
            for role_id in add_role_ids:
                role = discord.utils.get(fetched_roles, id=int(role_id))
                if role:
                    roles_to_add.append(role)

            # Process roles to remove
            for role_id in remove_role_ids:
                role = discord.utils.get(fetched_roles, id=int(role_id))
                if role:
                    roles_to_remove.append(role)

            # Add roles
            if roles_to_add:
                try:
                    await user.add_roles(
                        *roles_to_add, reason="Application denied - roles added"
                    )
                except discord.Forbidden:
                    raise HTTPException(
                        status_code=403, detail="Bot lacks permission to manage roles"
                    )
                except Exception as e:
                    raise HTTPException(
                        status_code=400, detail=f"Error adding roles: {str(e)}"
                    )

            # Remove roles
            if roles_to_remove:
                try:
                    await user.remove_roles(
                        *roles_to_remove, reason="Application denied - roles removed"
                    )
                except discord.Forbidden:
                    raise HTTPException(
                        status_code=403, detail="Bot lacks permission to manage roles"
                    )
                except Exception as e:
                    raise HTTPException(
                        status_code=400, detail=f"Error removing roles: {str(e)}"
                    )

            return 200

        except ValueError as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid data format: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )

    async def POST_notify_new_application(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        json_data = await request.json()
        guild_id = json_data["guild_id"]
        channel_id = json_data["channel_id"]
        user_id = json_data["user_id"]
        application_name = json_data["application_name"]

        guild = self.bot.get_guild(guild_id) or await self.bot.fetch_guild(guild_id)
        if not guild:
            raise HTTPException(status_code=404, detail="Guild not found")

        channel = guild.get_channel(channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        embed = discord.Embed(
            title=f"Application Received",
            description="",
            color=BLANK_COLOR,
        )
        embed.add_field(
            name="Details",
            value=(
                f"> **Application Name:** {application_name}\n"
                f"> **Submitted By:** <@{user_id}>\n"
                f"> **User ID:** {user_id}\n"
            ),
            inline=False,
        )
        embed.timestamp = datetime.datetime.now(pytz.utc)
        embed.set_author(
            name=guild.name,
            icon_url=guild.icon.url if guild.icon else None,
        )

        try:
            await channel.send(embed=embed)
            return {"op": 1, "code": 200}
        except discord.HTTPException as e:
            raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")

    async def POST_send_staff_request(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        json_data = await request.json()
        staff_request_id = json_data["document_id"]
        self.bot.dispatch("staff_request_send", ObjectId(staff_request_id))
        return {"op": 1, "code": 200}

    async def POST_send_priority_dm(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        json_data = await request.json()

        guild = self.bot.get_guild(json_data["guild_id"]) or await self.bot.fetch_guild(
            json_data["guild_id"]
        )
        guild_name = guild.name
        user_id = json_data["user_id"]
        member = guild.get_member(user_id)
        if not member:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                return HTTPException(status_code=404, detail="Member not found")
        if json_data["status"].lower() == "accepted":
            embed = discord.Embed(
                title=f"{self.bot.emoji_controller.get_emoji('success')} Priority Request Accepted",
                description=f"Your priority request is **{guild.name}** has been accepted!",
                color=GREEN_COLOR,
            ).add_field(
                name="Priority Information",
                value=f"> **Reason:** {json_data['reason']}\n> **Time:** {td_format(datetime.timedelta(seconds=int(json_data['priority_time'])))}",
                inline=False,
            )
        else:
            embed = discord.Embed(
                title="Priority Request Denied",
                description=f"Your priority request in **{guild_name}** has been denied. You can request a new one [here](https://ermbot.xyz/{guild.id}/request).",
                color=BLANK_COLOR,
            )
        try:
            await member.send(embed=embed)
            return {"op": 1, "code": 200}
        except discord.HTTPException:
            return HTTPException(
                status_code=400, detail="Member cannot be direct messaged."
            )

    async def POST_send_priority(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        json_data = await request.json()
        channel_id = json_data["channel_id"]
        try:
            channel = await self.bot.fetch_channel(channel_id)
        except discord.HTTPException:
            return HTTPException(status_code=404, detail="Channel not found")

        if not channel:
            return HTTPException(status_code=404, detail="Channel not found")

        embed = discord.Embed(
            title="New Priority Received",
            description=f"We have received a new priority request from **<@{json_data['username']}>** ({json_data['user_id']})",
            color=BLANK_COLOR,
        )

        to_usernames = []
        for item in json_data["players"]:
            user = await self.bot.roblox.get_user(item)
            to_usernames.append(user.name)

        embed.add_field(
            name="Priority Information",
            value=(
                f"> **Content:** {json_data['content']}\n"
                f"> **Players:** {', '.join(to_usernames)}\n"
                f"> **Link:** [Click here]({json_data['panel_link']})"
            ),
            inline=False,
        )

        embed.timestamp = datetime.datetime.now()

        priority_settings = await self.bot.priority_settings.db.find_one(
            {"guild_id": str(channel.guild.id)}
        )
        mentioned_roles = priority_settings["mentioned_roles"]
        content = ", ".join([f"<@&{role}>" for role in mentioned_roles])
        try:
            await channel.send(
                content, embed=embed, allowed_mentions=discord.AllowedMentions.all()
            )
        except discord.HTTPException:
            return HTTPException(status_code=404, detail="Channel not found")

        return {"op": 1, "code": 200}

    async def POST_send_loa(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        json_data = await request.json()
        s_loa = json_data.get("loa")  # OID -> dict { loa spec }
        s_loa_item = await self.bot.loas.find_by_id(s_loa)
        schema = s_loa_item
        guild = self.bot.get_guild(schema["guild_id"]) or await self.bot.fetch_guild(
            schema["guild_id"]
        )
        try:
            author = guild.get_member(schema["user_id"]) or await guild.get_member(
                schema["user_id"]
            )
        except:
            raise HTTPException(status_code=400, detail="Invalid author")

        request_type = schema["type"]
        settings = await self.bot.settings.find_by_id(guild.id)
        management_roles = settings.get("staff_management", {}).get(
            "management_role", []
        )
        loa_roles = settings.get("staff_management").get(f"{request_type.lower()}_role")

        embed = discord.Embed(title=f"{request_type} Request", color=BLANK_COLOR)
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else "")

        past_author_notices = [
            item
            async for item in self.bot.loas.db.find(
                {
                    "guild_id": guild.id,
                    "user_id": author.id,
                    "accepted": True,
                    "denied": False,
                    "expired": True,
                    "type": request_type.upper(),
                }
            )
        ]

        shifts = []
        storage_item = [
            i
            async for i in self.bot.shift_management.shifts.db.find(
                {"UserID": author.id, "Guild": guild.id}
            )
        ]

        for s in storage_item:
            if s["EndEpoch"] != 0:
                shifts.append(s)

        total_seconds = sum([get_elapsed_time(i) for i in shifts])

        embed.add_field(
            name="Staff Information",
            value=(
                f"> **Staff Member:** {author.mention}\n"
                f"> **Top Role:** {author.top_role.name}\n"
                f"> **Past {request_type}s:** {len(past_author_notices)}\n"
                f"> **Shift Time:** {td_format(datetime.timedelta(seconds=total_seconds))}"
            ),
            inline=False,
        )

        embed.add_field(
            name="Request Information",
            value=(
                f"> **Type:** {request_type}\n"
                f"> **Reason:** {schema['reason']}\n"
                f"> **Starts At:** <t:{schema.get('started_at', int(schema['_id'].split('_')[2]))}>\n"
                f"> **Ends At:** <t:{schema['expiry']}>"
            ),
        )

        view = LOAMenu(
            self.bot,
            management_roles,
            loa_roles,
            schema,
            author.id,
            (code := system_code_gen()),
        )

        staff_channel = settings.get("staff_management").get("channel")
        staff_channel = discord.utils.get(guild.channels, id=staff_channel)

        msg = await staff_channel.send(embed=embed, view=view)
        schema["message_id"] = msg.id
        await self.bot.views.insert(
            {
                "_id": code,
                "args": ["SELF", management_roles, loa_roles, schema, author.id, code],
                "view_type": "LOAMenu",
                "message_id": msg.id,
            }
        )

        ns = copy.copy(schema)
        del ns["_id"]
        await self.bot.loas.db.update_one({"_id": schema["_id"]}, {"$set": ns})

        return 200

    async def POST_accept_loa(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        json_data = await request.json()
        s_loa = json_data.get("loa")  # oid -> dict { loa spec }
        accepted_by = json_data.get("accepted_by")
        s_loa_item = await self.bot.loas.find_by_id(s_loa)
        s_loa = s_loa_item
        if s_loa.get('denied'):
            raise HTTPException(
                status_code=400, detail="This LOA has already been denied."
            )

        # fetch the actual accept roles
        guild_id = s_loa["guild_id"]
        config = await self.bot.settings.find_by_id(guild_id) or {}
        roles = (
            config.get("staff_management", {}).get(f"{s_loa['type']}_role", []) or []
        )

        self.bot.dispatch(
            "loa_accept", s_loa=s_loa, role_ids=roles, accepted_by=accepted_by
        )

        return 200

    async def POST_deny_loa(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        json_data = await request.json()
        s_loa = json_data.get("loa")
        denied_by = json_data.get("denied_by")
        reason = json_data.get("reason", "No reason provided.")
        s_loa_item = await self.bot.loas.find_by_id(s_loa)
        s_loa = s_loa_item
        if s_loa.get('accepted'):
            raise HTTPException(
                status_code=400, detail="This LOA has already been accepted."
            )

        self.bot.dispatch("loa_deny", s_loa=s_loa, denied_by=denied_by, reason=reason)

        return 200

    async def POST_send_application_wave(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        json_data = await request.json()
        if not json_data.get("Channel"):
            return HTTPException(status_code=400, detail="Bad Format")

        channel = await self.bot.fetch_channel(json_data["Channel"])
        embed = discord.Embed(
            title="Application Results",
            description=f"The applications for **{json_data['ApplicationName']}** have been released!\n\n",
            color=BLANK_COLOR,
        )
        embed_temp = discord.Embed(description="", color=BLANK_COLOR)
        embeds = [embed]

        for item in json_data["Applicants"]:
            new_content = f"<@{item['DiscordID']}>\n> Status: **{item['Status']}**\n> Reason: **{item['Reason']}**\n> Submission Time: <t:{int(item['SubmissionTime'])}>\n\n"

            current_desc = embeds[-1].description or ""
            if len(current_desc) + len(new_content) > 4000:
                new_embed = discord.Embed(description="", color=BLANK_COLOR)
                embeds.append(new_embed)

            embeds[-1].description = (embeds[-1].description or "") + new_content

        await channel.send(embeds=embeds)

    async def POST_all_members(
        self, authorization: Annotated[str | None, Header()], guild_id: int
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        guild = self.bot.get_guild(guild_id)
        if not guild:
            raise HTTPException(status_code=404, detail="Guild not found")

        if not guild.chunked:
            try:
                await guild.chunk(cache=True)
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Failed to fetch all members: {str(e)}"
                )

        member_data = []
        for member in guild.members:
            voice_state = member.voice
            member_info = {
                "id": member.id,
                "name": member.name,
                "nick": member.nick,
                "roles": [role.id for role in member.roles[1:]],
                "voice_state": None,
            }

            if voice_state:
                member_info["voice_state"] = {
                    "channel_id": (
                        voice_state.channel.id if voice_state.channel else None
                    ),
                    "channel_name": (
                        voice_state.channel.name if voice_state.channel else None
                    ),
                }

            member_data.append(member_info)

        response = {"members": member_data, "total_members": len(member_data)}

        return response

    async def POST_send_logging(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        json_data = await request.json()
        await secure_logging(
            self.bot,
            json_data["guild_id"],
            json_data["author_id"],
            json_data["interpret_type"],
            json_data["command_string"],
            json_data["attempted"],
        )
        return {"message": "Successfully logged!"}

    async def POST_get_staff_guilds(self, request: Request):
        json_data = await request.json()
        guild_ids = json_data.get("guilds")
        user_id = json_data.get("user")
        if not guild_ids:
            raise HTTPException(status_code=400, detail="No guilds specified")

        semaphore = asyncio.Semaphore(5)

        async def get_or_fetch(guild: discord.Guild, member_id: int):
            m = guild.get_member(member_id)
            if m:
                return m
            try:
                m = await guild.fetch_member(member_id)
            except:
                m = None
            return m

        async def process_guild(guild_id):
            async with semaphore:
                guild: discord.Guild = self.bot.get_guild(int(guild_id))
                if not guild:
                    return None
                try:
                    icon = guild.icon.with_size(512)
                    icon = icon.with_format("png")
                    icon = str(icon)
                except AttributeError:

                    icon = "https://cdn.discordapp.com/embed/avatars/0.png?size=512"

                try:
                    user = await asyncio.wait_for(
                        get_or_fetch(guild, user_id), timeout=5.0
                    )
                except (discord.NotFound, asyncio.TimeoutError):
                    return None

                if user is None:
                    return None

                permission_level = 0
                if await management_check(self.bot, guild, user):
                    permission_level = 2
                elif await admin_check(self.bot, guild, user):
                    permission_level = 3
                elif await staff_check(self.bot, guild, user):
                    permission_level = 1
                if permission_level > 0:
                    return {
                        "id": str(guild.id),
                        "name": str(guild.name),
                        "member_count": str(guild.member_count),
                        "icon_url": icon,
                        "permission_level": permission_level,
                    }
                return None

        guild_results = await asyncio.gather(
            *[process_guild(guild_id) for guild_id in guild_ids]
        )

        guilds = list(filter(lambda x: x is not None, guild_results))

        return guilds

    async def POST_check_staff_level(self, request: Request):
        json_data = await request.json()
        guild_id = json_data.get("guild")
        user_id = json_data.get("user")

        if not guild_id or not user_id:
            raise HTTPException(status_code=400, detail="Invalid guild or user ID")

        guild = None
        user = None

        guild = self.bot.get_guild(guild_id)
        if not guild:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except (discord.Forbidden, discord.HTTPException):
                raise HTTPException(status_code=400, detail="Invalid guild")

        user = guild.get_member(user_id)
        if not user:
            try:
                user = await guild.fetch_member(user_id)
            except (discord.Forbidden, discord.HTTPException):
                return {"permission_level": 0}

        permission_level = 0
        if await management_check(self.bot, guild, user):
            permission_level = 2
        elif await admin_check(self.bot, guild, user):
            permission_level = 3
        elif await staff_check(self.bot, guild, user):
            permission_level = 1

        return {"permission_level": permission_level}

    async def POST_get_guild_settings(self, request: Request):
        json_data = await request.json()
        guild_id = json_data.get("guild")
        if not guild_id:
            return HTTPException(status_code=400, detail="Invalid guild")
        guild: discord.Guild = self.bot.get_guild(int(guild_id))
        settings = await self.bot.settings.find_by_id(guild.id)
        if not settings:
            return HTTPException(status_code=400, detail="Invalid guild")

        return settings

    async def POST_update_guild_settings(self, request: Request):
        json_data = await request.json()
        guild_id = json_data.get("guild")

        for key, value in json_data.items():
            if key == "guild":
                continue
            if isinstance(value, dict):
                settings = await self.bot.settings.find_by_id(guild_id)
                if not settings:
                    return HTTPException(status_code=400, detail="Invalid guild")
                for k, v in value.items():
                    settings[key][k] = v
        await self.bot.settings.update_by_id(settings)

        if not guild_id:
            return HTTPException(status_code=400, detail="Invalid guild")
        guild: discord.Guild = self.bot.get_guild(int(guild_id))
        settings = await self.bot.settings.find_by_id(guild.id)
        if not settings:
            return HTTPException(
                status_code=404, detail="Guild does not have settings attribute"
            )

        return settings

    async def POST_get_guild_roles(self, request: Request):
        json_data = await request.json()
        guild_id = json_data.get("guild")

        if not guild_id:
            return HTTPException(status_code=400, detail="Invalid guild")
        guild: discord.Guild = self.bot.get_guild(int(guild_id))

        return [
            {"name": role.name, "id": role.id, "color": str(role.color)}
            for role in guild.roles
        ]

    async def POST_get_guild_channels(self, request: Request):
        json_data = await request.json()
        guild_id = json_data.get("guild")

        if not guild_id:
            return HTTPException(status_code=400, detail="Invalid guild")
        guild: discord.Guild = self.bot.get_guild(int(guild_id))

        return [
            {"name": channel.name, "id": channel.id, "type": channel.type}
            for channel in guild.channels
        ]

    async def POST_get_last_warnings(self, request):
        json_data = await request.json()
        guild_id = json_data.get("guild")
        # NOTE: This API is deprecated.
        return HTTPException(status_code=500, detail="This API is deprecated")

        # warning_objects = {}
        # async for document in self.bot.warnings.db.find(
        #         {"Guild": guild_id}
        # ).sort([("$natural", -1)]).limit(10):
        #     warning_objects[document["_id"]] = list(
        #         filter(lambda x: x["Guild"] == guild_id, document["warnings"])
        #     )

        # return warning_objects

    async def GET_get_token(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        """

        Generates a token for the API. Requires an unspecified private key.

        :param authorization:
        :param request:
        :return:
        """

        if authorization != config("API_PRIVATE_KEY"):
            raise HTTPException(status_code=401, detail="Invalid authorization")
        has_token = await self.bot.api_tokens.find_by_id(request.client.host)
        if has_token:
            if not int(datetime.datetime.now().timestamp()) > has_token["expires_at"]:
                return has_token
        # # # print(request)
        generated = tokenGenerator()
        object = {
            "_id": request.client.host,
            "token": generated,
            "created_at": int(datetime.datetime.now().timestamp()),
            "expires_at": int(datetime.datetime.now().timestamp()) + 2.592e6,
        }

        await self.bot.api_tokens.upsert(object)

        return object

    async def POST_authorize_token(
        self,
        authorization: Annotated[str | None, Header()],
        x_link_string: Annotated[str | None, Header()],
    ):
        """

        Authorizes a token for the API, and links a Discord server to the token. Requires a token and a transfer string, which is placed in the X-Link-String header.

        :param authorization:
        :param x_link_string:
        :return:
        """
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(
            self.bot, authorization, disable_static_tokens=True
        ):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )
        token_obj = await self.bot.api_tokens.db.find_one({"token": authorization})

        if not x_link_string:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        link_string_obj = await self.bot.link_strings.db.find_one(
            {"_id": x_link_string}
        )

        if not link_string_obj:
            raise HTTPException(status_code=401, detail="Invalid link string")

        link_string_obj["token"] = authorization
        link_string_obj["ip"] = token_obj["_id"]
        link_string_obj["link_string"] = link_string_obj["_id"]
        await self.bot.link_strings.update_by_id(link_string_obj)

        token_obj["link_string"] = link_string_obj["_id"]
        await self.bot.api_tokens.update_by_id(token_obj)

        return link_string_obj

    async def GET_get_link_string(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        """
        Given an authorization token as a header, returns a dictionary with information about the token.

        Parameters:
            authorization (str | None): The authorization token to be verified.
            request (fastapi.Request): The incoming HTTP request.

        Raises:
            HTTPException: If the authorization token is missing, invalid, or has expired.

        Returns:
            dict: A dictionary containing information about the authorization token, such as the token string,
                  its expiration timestamp, and any other associated data.
        """
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        token_obj = await self.bot.api_tokens.db.find_one({"token": authorization})

        if not token_obj:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if int(datetime.datetime.now().timestamp()) > token_obj["expires_at"]:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        return token_obj

    async def GET_get_current_token(self, request: Request):
        """
        Given the client host IP, returns a dictionary with information about the token.

        Parameters:
            request (fastapi.Request): The incoming HTTP request.

        Raises:
            HTTPException: If the authorization token is missing, invalid, or has expired.

        Returns:
            dict: A dictionary containing information about the authorization token, such as the token string,
                  its expiration timestamp, and any other associated data.
        """

        token_obj = await self.bot.api_tokens.db.find_one({"_id": request.client.host})
        ## # print(token_obj)
        # # print(request.client.host)
        if not token_obj:
            raise HTTPException(
                status_code=404, detail="Could not find token associated with IP"
            )

        return token_obj

    async def GET_get_online_staff(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        # Use the self.bot.shifts to get all current shifts for the guild ID associated with the link string associated with the token
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        token_obj = await self.bot.api_tokens.db.find_one({"token": authorization})

        if not token_obj:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if int(datetime.datetime.now().timestamp()) > token_obj["expires_at"]:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        link_string_obj = await self.bot.link_strings.db.find_one(
            {"_id": token_obj["link_string"]}
        )

        if not link_string_obj:
            raise HTTPException(status_code=401, detail="Invalid link string")

        guild = self.bot.get_guild(link_string_obj["guild"])

        if not guild:
            raise HTTPException(status_code=404, detail="Guild not found")

        shifts = []
        async for doc in self.bot.shift_management.shifts.db.find(
            {"data": {"$elemMatch": {"guild": link_string_obj["guild"]}}}
        ):
            item = [
                *list(
                    filter(
                        lambda x: (x or {}).get("guild") == link_string_obj["guild"],
                        doc["data"],
                    )
                )
            ][0]
            item["discord"] = doc["_id"]
            fivem_link = await self.bot.fivem_links.db.find_one(
                {"_id": item["discord"]}
            )
            item["fivem"] = (fivem_link or {}).get("steam_id")
            shifts.append(item)

        return shifts

    async def POST_get_discord(
        self,
        authorization: Annotated[str | None, Header()],
        body: Identification,
        request: Request,
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        token_obj = await self.bot.api_tokens.db.find_one({"token": authorization})

        if not token_obj:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if int(datetime.datetime.now().timestamp()) > token_obj["expires_at"]:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        link_string_obj = await self.bot.link_strings.db.find_one(
            {"_id": token_obj["link_string"]}
        )

        if not link_string_obj:
            raise HTTPException(status_code=401, detail="Invalid link string")

        if not body or not body.license:
            raise HTTPException(status_code=400, detail="Missing license")

        fivem_link = await self.bot.fivem_links.db.find_one({"license": body.license})
        return (
            {"status": "success"}.update(fivem_link)
            if fivem_link
            else {"status": "failed"}
        )

    async def POST_get_fivem(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        token_obj = await self.bot.api_tokens.db.find_one({"token": authorization})

        if not token_obj:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if int(datetime.datetime.now().timestamp()) > token_obj["expires_at"]:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        link_string_obj = await self.bot.link_strings.db.find_one(
            {"_id": token_obj["link_string"]}
        )

        if not link_string_obj:
            raise HTTPException(status_code=401, detail="Invalid link string")

        body = await request.json()
        if not body or not body.get("discord_id"):
            raise HTTPException(status_code=400, detail="Missing discord_id")

        fivem_link = await self.bot.fivem_links.db.find_one({"_id": body["discord_id"]})
        return (
            {"status": "success"}.update(fivem_link)
            if fivem_link
            else {"status": "failed"}
        )

    async def POST_duty_on_actions(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            return HTTPException(status_code=401, detail="Invalid authorization")

        base_auth = await validate_authorization(
            self.bot, authorization, disable_static_tokens=False
        )
        if not base_auth:
            return HTTPException(status_code=401, detail="Invalid authorization")
        data = request.query_params.get("ObjectId")
        if not data:
            return HTTPException(
                status_code=400, detail="Didn't provide 'ObjectId' parameter."
            )

        self.bot.dispatch("shift_start", ObjectId(data))
        return 200

    async def POST_duty_off_actions(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            return HTTPException(status_code=401, detail="Invalid authorization")

        base_auth = await validate_authorization(
            self.bot, authorization, disable_static_tokens=False
        )
        if not base_auth:
            return HTTPException(status_code=401, detail="Invalid authorization")
        data = request.query_params.get("ObjectId")
        if not data:
            return HTTPException(
                status_code=400, detail="Didn't provide 'ObjectId' parameter."
            )

        self.bot.dispatch("shift_end", ObjectId(data))
        return 200

    async def POST_duty_break_actions(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            return HTTPException(status_code=401, detail="Invalid authorization")

        base_auth = await validate_authorization(
            self.bot, authorization, disable_static_tokens=False
        )
        if not base_auth:
            return HTTPException(status_code=401, detail="Invalid authorization")
        data = request.query_params.get("ObjectId")
        if not data:
            return HTTPException(
                status_code=400, detail="Didn't provide 'ObjectId' parameter."
            )

        self.bot.dispatch("break_start", ObjectId(data))
        return 200

    async def POST_duty_end_break_actions(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            return HTTPException(status_code=401, detail="Invalid authorization")

        base_auth = await validate_authorization(
            self.bot, authorization, disable_static_tokens=False
        )
        if not base_auth:
            return HTTPException(status_code=401, detail="Invalid authorization")
        data = request.query_params.get("ObjectId")
        if not data:
            return HTTPException(
                status_code=400, detail="Didn't provide 'ObjectId' parameter."
            )

        self.bot.dispatch("break_end", ObjectId(data))
        return 200

    async def POST_duty_voided_actions(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            return HTTPException(status_code=401, detail="Invalid authorization")

        base_auth = await validate_authorization(
            self.bot, authorization, disable_static_tokens=False
        )

        if not base_auth:
            return HTTPException(status_code=401, detail="Invalid authorization")
        data = request.query_params.get("ObjectId")
        if not data:
            return HTTPException(
                status_code=400, detail="Didn't provide 'ObjectId' parameter."
            )

        dataobject = await self.bot.shift_management.fetch_shift(ObjectId(data))
        guild = await self.bot.fetch_guild(dataobject["Guild"])
        staff_member = await guild.fetch_member(dataobject["UserID"])

        self.bot.dispatch("shift_void", staff_member, ObjectId(data))
        return 200

    async def POST_punishment_logged(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            return HTTPException(status_code=401, detail="Invalid authorization")

        base_auth = await validate_authorization(
            self.bot, authorization, disable_static_tokens=False
        )
        # print(base_auth)
        if not base_auth:
            return HTTPException(status_code=401, detail="Invalid authorization")
        data = request.query_params.get("ObjectId")
        if not data:
            return HTTPException(
                status_code=400, detail="Didn't provide 'ObjectId' parameter."
            )

        self.bot.dispatch("punishment", ObjectId(data))
        return 200

    async def POST_duty_on(
        self,
        authorization: Annotated[str | None, Header()],
        identification: Identification,
        request: Request,
    ):
        # # print(request)
        # # print(await request.json())
        # # print("REQUEST ^^")
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        token_obj = await self.bot.api_tokens.db.find_one({"token": authorization})

        if not token_obj:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if int(datetime.datetime.now().timestamp()) > token_obj["expires_at"]:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        link_string_obj = await self.bot.link_strings.db.find_one(
            {"_id": token_obj["link_string"]}
        )

        if not link_string_obj:
            raise HTTPException(status_code=401, detail="Invalid link string")

        guild = self.bot.get_guild(link_string_obj["guild"])

        if not guild:
            raise HTTPException(status_code=404, detail="Guild not found")

        body = await request.json()

        if not body:
            raise HTTPException(status_code=400, detail="No body provided")

        if not body.get("steam_id"):
            raise HTTPException(status_code=400, detail="No steam ID provided")

        # # print(body)
        fivem_link = await self.bot.fivem_links.db.find_one(
            {"steam_id": body["steam_id"]}
        )

        if not fivem_link:
            raise HTTPException(status_code=404, detail="Could not find FiveM link")

        if not fivem_link.get("_id"):
            raise HTTPException(status_code=404, detail="Could not find FiveM link")

        try:
            member = await guild.fetch_member(fivem_link["_id"])
        except discord.NotFound:
            raise HTTPException(status_code=404, detail="Could not find Discord member")

        settings = await self.bot.settings.find_by_id(guild.id)
        if not settings:
            raise HTTPException(status_code=404, detail="Could not find settings")

        if settings.get("shift_types"):
            available_shift_types = []
            for shift_type in settings["shift_types"]:
                available_shift_types.append(shift_type["id"])

        if not body.get("shift_type"):
            await self.bot.shift_management.add_shift_by_user(member, {"guild": guild})
        else:
            if body["shift_type"] not in available_shift_types:
                raise HTTPException(status_code=400, detail="Invalid shift type")
            await self.bot.shift_management.add_shift_by_user(
                member, {"guild": guild, "shift_type": body["shift_type"]}
            )

        return {
            "status": "success",
            "member": member.id,
            "shift_type": body.get("shift_type"),
        }

    async def POST_duty_off(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(
            self.bot, authorization, disable_static_tokens=False
        ):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        token_obj = await self.bot.api_tokens.db.find_one({"token": authorization})

        if token_obj:
            link_string_obj = await self.bot.link_strings.db.find_one(
                {"_id": token_obj["link_string"]}
            )

            if not link_string_obj:
                raise HTTPException(status_code=401, detail="Invalid link string")

            guild = self.bot.get_guild(link_string_obj["guild"])
        else:
            data = await request.json()
            guild = data["guild"]

        if not guild:
            raise HTTPException(status_code=404, detail="Guild not found")

        body = await request.json()

        if not body:
            raise HTTPException(status_code=400, detail="No body provided")

        if token_obj:
            if not body.get("steam_id"):
                raise HTTPException(status_code=400, detail="No steam ID provided")

            fivem_link = await self.bot.fivem_links.db.find_one(
                {"steam_id": body["steam_id"]}
            )

            if not fivem_link:
                raise HTTPException(status_code=404, detail="Could not find FiveM link")

            if not fivem_link.get("_id"):
                raise HTTPException(status_code=404, detail="Could not find FiveM link")

        try:
            member = await guild.fetch_member(fivem_link["_id"])
        except discord.NotFound:
            raise HTTPException(status_code=404, detail="Could not find Discord member")

        settings = await self.bot.settings.find_by_id(guild.id)
        if not settings:
            raise HTTPException(status_code=404, detail="Could not find settings")

        shifts = await self.bot.shift_management.shifts.find_by_id(member.id)
        if not shifts:
            raise HTTPException(status_code=404, detail="Could not find user shifts")

        associated_shift = list(
            filter(lambda x: (x or {}).get("guild") == guild.id, shifts["data"])
        )
        if not associated_shift or len(associated_shift) == 0:
            raise HTTPException(status_code=404, detail="Could not find user shifts")
        else:
            associated_shift = associated_shift[0]

        await self.bot.shift_management.remove_shift_by_user(
            member, {"guild": guild, "shift": associated_shift}
        )

    async def POST_guild(
        self, authorization: Annotated[str | None, Header()], guild_id: int
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        guild = self.bot.get_guild(guild_id)

        if not guild:
            try:
                guild = await self.bot.fetch_guild(guild_id)
            except discord.NotFound:
                raise HTTPException(status_code=404, detail="Guild not found")
            except discord.Forbidden:
                raise HTTPException(
                    status_code=403, detail="Bot does not have access to this guild"
                )
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"Error fetching guild: {str(e)}"
                )

        guild_data = {
            "id": guild.id,
            "name": guild.name,
            "member_count": guild.member_count,
            "owner_id": guild.owner_id,
            "icon_url": str(guild.icon.url) if guild.icon else None,
            "features": guild.features,
            "created_at": int(guild.created_at.timestamp()),
        }

        return guild_data

    async def POST_issue_infraction(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        try:
            json_data = await request.json()
            user_id = int(json_data["user_id"])
            guild_id = int(json_data["guild_id"])
            original_infraction_type = json_data["infraction_type"]
            reason = json_data.get("reason", "No reason provided")
            issuer_id = json_data.get("issuer_id")

            guild = self.bot.get_guild(guild_id)
            if not guild:
                raise HTTPException(status_code=404, detail="Guild not found")

            settings = await self.bot.settings.find_by_id(guild_id)
            if not settings or "infractions" not in settings:
                raise HTTPException(
                    status_code=404, detail="No infraction settings found"
                )

            infraction_config = next(
                (
                    inf
                    for inf in settings["infractions"]["infractions"]
                    if inf["name"] == original_infraction_type
                ),
                None,
            )
            if not infraction_config:
                raise HTTPException(
                    status_code=404,
                    detail=f"Infraction type {original_infraction_type} not found in settings",
                )

            try:
                member = await guild.fetch_member(user_id)
                username = member.name
            except:
                username = "Unknown User"

            try:
                issuer = await guild.fetch_member(issuer_id)
                issuer_username = issuer.name
            except:
                issuer_username = "Unknown Issuer"

            will_escalate = False
            existing_count = 0
            current_type = original_infraction_type

            if infraction_config.get("escalation"):
                while True:
                    threshold = infraction_config["escalation"].get("threshold", 0)
                    next_infraction = infraction_config["escalation"].get(
                        "next_infraction"
                    )

                    if not threshold or not next_infraction:
                        break

                    existing_count = await self.bot.db.infractions.count_documents(
                        {
                            "user_id": user_id,
                            "guild_id": guild_id,
                            "type": current_type,
                            "revoked": {"$ne": True},
                        }
                    )

                    if (existing_count + 1) >= threshold:
                        next_config = next(
                            (
                                inf
                                for inf in settings["infractions"]["infractions"]
                                if inf["name"] == next_infraction
                            ),
                            None,
                        )
                        if not next_config:
                            break

                        current_type = next_infraction
                        will_escalate = True
                        infraction_config = next_config
                    else:
                        break

            if will_escalate:
                original_infraction_type = current_type
                reason = f"{reason}\n\nEscalated from {original_infraction_type} after reaching threshold"

            infraction_doc = {
                "user_id": user_id,
                "username": username,
                "guild_id": guild_id,
                "type": original_infraction_type,
                "reason": reason,
                "timestamp": datetime.datetime.now().timestamp(),
                "issuer_id": issuer_id,
                "issuer_username": issuer_username,
                "escalated": will_escalate,
                "escalation_count": existing_count + 1 if will_escalate else None,
            }

            result = await self.bot.db.infractions.insert_one(infraction_doc)
            infraction_doc["_id"] = result.inserted_id

            self.bot.dispatch("infraction_create", infraction_doc)

            return {
                "status": "success",
                "infraction_id": str(result.inserted_id),
                "escalated": will_escalate,
                "type": original_infraction_type,
            }

        except Exception as e:
            logger.error(f"Error issuing infraction: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )

    async def POST_revoke_infraction(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        try:
            json_data = await request.json()
            infraction_id = json_data.get("infraction_id")
            if not infraction_id:
                raise HTTPException(status_code=400, detail="Missing infraction_id")

            infraction = await self.bot.db.infractions.find_one(
                {"_id": ObjectId(infraction_id)}
            )
            if not infraction:
                raise HTTPException(status_code=404, detail="Infraction not found")

            if infraction.get("revoked", False):
                raise HTTPException(
                    status_code=400, detail="Infraction already revoked"
                )

            # Update the infraction
            await self.bot.db.infractions.update_one(
                {"_id": ObjectId(infraction_id)},
                {
                    "$set": {
                        "revoked": True,
                        "revoked_at": datetime.datetime.now(tz=pytz.UTC).timestamp(),
                        "revoked_by": json_data.get("revoked_by", 0),
                    }
                },
            )

            infraction["revoked"] = True
            infraction["revoked_at"] = datetime.datetime.now(tz=pytz.UTC).timestamp()
            infraction["revoked_by"] = json_data.get("revoked_by", 0)

            # Dispatch the event
            self.bot.dispatch("infraction_revoke", infraction)

            return {"status": "success", "infraction_id": infraction_id}

        except Exception as e:
            logger.error(f"Error revoking infraction: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )

    async def POST_get_infraction_wave_preview(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        try:
            json_data = await request.json()
            guild_id = int(json_data["guild_id"])
            infract_type = json_data.get("infract_type")
            quota_period = int(json_data.get("period", 7 * 24 * 60 * 60))
            omit_loas = json_data.get("omit_loas", False)

            settings = await self.bot.settings.find_by_id(guild_id)
            if not settings:
                raise HTTPException(status_code=404, detail="Guild not found")

            guild = self.bot.get_guild(guild_id)
            if not guild:
                raise HTTPException(status_code=404, detail="Guild not found")

            staff_roles = settings.get("staff_management", {}).get("role", [])
            role_quotas = settings.get("shift_management", {}).get("role_quotas", [])
            general_quota = settings.get("shift_management", {}).get("quota") or 0

            if not staff_roles:
                raise HTTPException(status_code=400, detail="No staff roles configured")

            end_time = datetime.datetime.now(tz=pytz.UTC).timestamp()
            start_time = end_time - quota_period

            active_loas = set()
            if omit_loas:
                current_time = datetime.datetime.now(tz=pytz.UTC).timestamp()
                async for loa in self.bot.loas.db.find(
                    {
                        "guild_id": guild_id,
                        "accepted": True,
                        "denied": False,
                        "expired": False,
                        "voided": False,
                        "expiry": {"$gt": current_time},
                    }
                ):
                    active_loas.add(loa["user_id"])

            all_staff = {}
            for role_id in staff_roles:
                role = guild.get_role(role_id)
                if role:
                    for member in role.members:
                        if member.id not in all_staff:
                            if omit_loas and member.id in active_loas:
                                all_staff[member.id] = {
                                    "user_id": member.id,
                                    "username": member.name,
                                    "shift_time": 0,
                                    "required_quota": 0,
                                    "met_quota": True,
                                    "infraction_type": None,
                                    "skipped_loa": True,
                                }
                                continue

                            required_quota = general_quota
                            for role_quota in role_quotas:
                                if role_quota["role"] in [r.id for r in member.roles]:
                                    required_quota = role_quota["quota"]
                                    break

                            # we need to make sure that users w/ 0 quota met their quota
                            met_quota = required_quota == 0

                            all_staff[member.id] = {
                                "user_id": member.id,
                                "username": member.name,
                                "shift_time": 0,
                                "required_quota": required_quota,
                                "met_quota": met_quota,
                                "infraction_type": None if met_quota else infract_type,
                                "skipped_loa": False,
                            }

            async for shift_doc in self.bot.shift_management.shifts.db.find(
                {"Guild": guild_id, "EndEpoch": {"$gt": start_time, "$lt": end_time}}
            ):
                member_id = shift_doc["UserID"]
                if member_id in all_staff:
                    shift_time = get_elapsed_time(shift_doc)
                    if shift_time < 100_000_000:
                        all_staff[member_id]["shift_time"] += shift_time
                        all_staff[member_id]["met_quota"] = (
                            all_staff[member_id]["shift_time"]
                            >= all_staff[member_id]["required_quota"]
                            or all_staff[member_id]["required_quota"] == 0
                        )
                        if all_staff[member_id]["met_quota"]:
                            all_staff[member_id]["infraction_type"] = None

            results = list(all_staff.values())
            skipped_loas = len([r for r in results if r.get("skipped_loa", False)])

            return {
                "preview": {
                    "total_users": len(results),
                    "users_below_quota": len(
                        [r for r in results if not r["met_quota"]]
                    ),
                    "users_above_quota": len(
                        [
                            r
                            for r in results
                            if r["met_quota"] and not r.get("skipped_loa", False)
                        ]
                    ),
                    "users_skipped_loa": skipped_loas,
                    "period_start": start_time,
                    "period_end": end_time,
                },
                "users": results,
            }

        except Exception as e:
            logger.error(f"Error generating infraction wave preview: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )

    async def POST_start_infraction_wave(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        try:
            json_data = await request.json()
            guild_id = int(json_data["guild_id"])
            infract_violators = json_data.get("infract_violators", False)
            infract_type = json_data.get("infract_type")
            issuer_id = json_data.get("issuer_id")
            quota_period = int(json_data.get("period", 7 * 24 * 60 * 60))

            preview_request = Request(scope={"type": "http"})
            preview_request._json = json_data

            preview_results = await self.POST_get_infraction_wave_preview(
                authorization=authorization, request=preview_request
            )

            if not infract_violators:
                return {
                    "message": "Dry run completed",
                    "would_infract": len(
                        [u for u in preview_results["users"] if not u["met_quota"]]
                    ),
                    "preview": preview_results,
                }

            infractions_issued = 0
            for user in preview_results["users"]:
                if not user["met_quota"] and not user.get("skipped_loa", False):
                    try:
                        infraction_request = Request(scope={"type": "http"})
                        infraction_request._json = {
                            "user_id": user["user_id"],
                            "guild_id": guild_id,
                            "infraction_type": infract_type,
                            "issuer_id": issuer_id,
                            "reason": f"Failed to meet quota requirement of {td_format(datetime.timedelta(seconds=user['required_quota']))} (Achieved: {td_format(datetime.timedelta(seconds=user['shift_time']))})",
                        }

                        await self.POST_issue_infraction(
                            authorization=authorization, request=infraction_request
                        )
                        infractions_issued += 1
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error(
                            f"Failed to issue infraction for user {user['user_id']}: {e}"
                        )

            return {
                "message": "Infraction wave completed",
                "infractions_issued": infractions_issued,
                "preview": preview_results,
            }

        except Exception as e:
            logger.error(f"Error running infraction wave: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )

    async def POST_search_guild_members(
        self, authorization: Annotated[str | None, Header()], request: Request
    ):
        if not authorization:
            raise HTTPException(status_code=401, detail="Invalid authorization")

        if not await validate_authorization(self.bot, authorization):
            raise HTTPException(
                status_code=401, detail="Invalid or expired authorization."
            )

        try:
            json_data = await request.json()
            guild_id = int(json_data.get("guild_id"))
            query = json_data.get("query")
            limit = min(int(json_data.get("limit", 1000)), 1000)

            guild = self.bot.get_guild(guild_id)
            if not guild:
                try:
                    guild = await self.bot.fetch_guild(guild_id)
                except discord.NotFound:
                    raise HTTPException(status_code=404, detail="Guild not found")

            if not guild.chunked:
                await guild.chunk()

            matching_members = []
            for member in guild.members:
                name_matches = query.lower() in member.name.lower()
                nick_matches = member.nick and query.lower() in member.nick.lower()

                if name_matches or nick_matches:
                    member_data = {
                        "user": {
                            "id": str(member.id),
                            "username": member.name,
                            "discriminator": member.discriminator,
                            "global_name": member.global_name,
                            "avatar": str(member.display_avatar.url),
                        },
                        "nick": member.nick,
                        "roles": [str(role.id) for role in member.roles],
                        "joined_at": (
                            member.joined_at.isoformat() if member.joined_at else None
                        ),
                        "premium_since": (
                            member.premium_since.isoformat()
                            if member.premium_since
                            else None
                        ),
                        "pending": member.pending,
                        "communication_disabled_until": (
                            member.timed_out_until.isoformat()
                            if member.timed_out_until
                            else None
                        ),
                    }
                    matching_members.append(member_data)

                if len(matching_members) >= limit:
                    break

            return {"members": matching_members[:limit], "total": len(matching_members)}

        except Exception as e:
            logger.error(f"Error searching members: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )


api = FastAPI()

from fastapi import Request


class MyMiddleware:
    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot

    async def __call__(self, request: Request, call_next):
        guild_id = ""
        try:
            if config("ENVIRONMENT") == "CUSTOM":
                raise Exception("We're already redirected.")

            request_json = await request.json()
            guild_id = int(
                request_json.get("guild_id")
                or request_json.get("guild")
                or request_json.get("GuildID")
            )

            doc = self.bot.whitelabel.db.find_one({"GuildID": str(guild_id)})
            if not doc:
                raise Exception("doc not found")

            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=request.method,
                    url=request.url._url.replace(
                        request.url._url.split("https://")[1].split("/")[0],
                        f"core-{guild_id}.erlc.site",
                    ),
                    body=request.body,
                    headers=request.headers,
                ) as resp:
                    resp_body = await resp.read()
                    return Response(
                        content=resp_body, status_code=resp.status, headers=resp.headers
                    )
        except:
            response = await call_next(request)
            return response


class ServerAPI(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.server = None
        self.server_task = None

    async def start_server(self):
        try:
            middleware = MyMiddleware(bot=self.bot)
            api.add_middleware(BaseHTTPMiddleware, dispatch=middleware)
            api.include_router(APIRoutes(self.bot).router)
            self.config = uvicorn.Config(
                "utils.api:api", port=5000, log_level="debug", host="0.0.0.0"
            )
            self.server = uvicorn.Server(self.config)
            await self.server.serve()
        except Exception as e:
            logger.error(f"Server error: {e}")
            await asyncio.sleep(5)
            self.server_task = asyncio.create_task(self.start_server())

    async def stop_server(self):
        try:
            if self.server:
                await self.server.shutdown()
            else:
                logger.info("Server was not running")
        except Exception as e:
            logger.error(f"Error stopping server: {e}")

    async def cog_load(self) -> None:
        self.server_task = asyncio.create_task(self.start_server())
        self.server_task.add_done_callback(self.server_error_handler)

    def server_error_handler(self, future: asyncio.Future):
        try:
            future.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Unhandled server error: {e}")
            self.server_task = asyncio.create_task(self.start_server())

    async def cog_unload(self) -> None:
        try:
            if self.server_task:
                self.server_task.cancel()
            await self.stop_server()
        except Exception as e:
            logger.error(f"Error during cog unload: {e}")


async def setup(bot):
    try:
        await bot.add_cog(ServerAPI(bot))
    except Exception as e:
        logger.error(f"Error setting up ServerAPI cog: {e}")
