import typing
from copy import copy

import aiohttp
import pymongo.operations
from bson import ObjectId
from decouple import config
from discord.ext import commands
import discord

from utils.utils import generator
from utils.mongo import Document


class WarningItem:
    id: str
    username: str
    user_id: int
    warning_type: str
    reason: str
    moderator_name: str
    moderator_id: int
    guild_id: int
    time_epoch: int
    until_epoch: typing.Optional[int]
    snowflake: int

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __getitem__(self, item):
        legacy_correspondents = {
            "_id": "id",
            "userid": "user_id",
            "type": "warning_type",
            "moderator": "moderator_name",
            "moderatorid": "moderator_id",
            "guild": "guild_id",
            "epoch": "time_epoch",
            "untilepoch": "until_epoch",
        }
        if legacy_correspondents.get(item.lower()) is not None:
            item = legacy_correspondents[item.lower()]
        return getattr(self, item.lower())


class Warnings(Document):
    """
    Also known as the punishment module, this is used for intermediary methods for the Warnings database <-> ERM.
    """

    def __init__(self, bot):
        self.bot = bot
        super().__init__(bot.db, "punishments")
        self.recovery = Document(bot.db, "recovery")

    async def get_warnings(self, user: int, guild: int) -> list[WarningItem]:
        """
        Gets the warnings for a user in a guild.
        """
        return [
            WarningItem(
                id=i["_id"],
                snowflake=i["Snowflake"],
                username=i["Username"],
                user_id=i["UserID"],
                warning_type=i["Type"],
                reason=i["Reason"],
                moderator_name=i["Moderator"],
                moderator_id=i["ModeratorID"],
                guild_id=i["Guild"],
                time_epoch=i["Epoch"],
                until_epoch=None if i.get("UntilEpoch") == 0 else i["UntilEpoch"],
            )
            async for i in self.db.find({"Guild": guild, "UserID": user})
        ]

    async def fetch_warning(self, warning_id: str) -> WarningItem | None:
        """
        Fetches a warning by its ID.
        """
        i = await self.db.find_one({"_id": ObjectId(warning_id)})
        if i is None:
            return None
        return WarningItem(
            id=i["_id"],
            snowflake=i["Snowflake"],
            username=i["Username"],
            user_id=i["UserID"],
            warning_type=i["Type"],
            reason=i["Reason"],
            moderator_name=i["Moderator"],
            moderator_id=i["ModeratorID"],
            guild_id=i["Guild"],
            time_epoch=i["Epoch"],
            until_epoch=None if i.get("UntilEpoch") == 0 else i["UntilEpoch"],
        )

    async def get_warning(self, warning_id: str) -> dict:
        """
        Gets a warning by its ID.
        """
        return await self.db.find_one({"_id": ObjectId(warning_id)})

    async def remove_warning(self, warning_id: str):
        """
        Removes a warning by its ID.
        """
        await self.db.delete_one({"_id": ObjectId(warning_id)})

    async def get_warning_by_snowflake(self, snowflake: int) -> dict:
        """
        Gets a warning by its ID.
        """
        return await self.db.find_one({"Snowflake": snowflake})

    async def get_global_warnings(self, user: int) -> list[dict]:
        """
        Gets the warnings for a user globally.
        """
        return [i async for i in self.db.find({"UserID": user})]

    async def get_guild_bolos(self, guild: int) -> list[dict]:
        """
        Gets the BOLOs for a guild.
        """
        return [
            i
            async for i in self.db.find(
                {"Guild": guild, "Type": {"$in": ["BOLO", "Bolo"]}}
            )
        ]

    async def insert_warning(
        self,
        staff_id: int,
        staff_name: str,
        user_id: int,
        user_name: str,
        guild_id: int,
        reason: str,
        moderation_type: str,
        time_epoch: int,
        until_epoch: int | None = None,
    ) -> ObjectId | ValueError:
        """
        Inserts a warning into the database.
        {
          "_id": 123456789012345678,
          "Username": "1friendlydoge",
          "UserID": 123456789012345678,
          "Type": "Warning",
          "Reason": "Nerd",
          "Moderator": "Noah",
          "ModeratorID": 123456789012345678,
          "Guild": 12345678910111213,
          "Epoch": 706969420,
          "UntilEpoch": 706969420
        }
        """
        if all([until_epoch is None, moderation_type == "Temporary Ban"]):
            return ValueError("Epoch must be provided for temporary bans.")

        if any(
            not i
            for i in [
                staff_id,
                staff_name,
                user_id,
                user_name,
                guild_id,
                reason,
                moderation_type,
            ]
        ):
            return ValueError("All arguments must be provided.")

        identifier = ObjectId()

        await self.db.insert_one(
            {
                "_id": identifier,
                "Snowflake": next(generator),
                "Username": user_name,
                "UserID": user_id,
                "Type": moderation_type,
                "Reason": reason,
                "Moderator": staff_name,
                "ModeratorID": staff_id,
                "Guild": guild_id,
                "Epoch": int(time_epoch),
                "UntilEpoch": int(until_epoch if until_epoch is not None else 0),
            }
        )

        try:
            url_var = config("BASE_API_URL")
            panel_url_var = config("PANEL_API_URL")
            if url_var not in ["", None]:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{url_var}/Internal/SyncCreatePunishment/{identifier}",
                        headers={"Authorization": config("INTERNAL_API_AUTH")},
                    ):
                        pass
            if panel_url_var not in ["", None]:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{panel_url_var}/{guild_id}/SyncCreatePunishment?ID={identifier}",
                        headers={"Authorization": config("INTERNAL_API_AUTH")},
                    ):
                        pass
        except:
            pass

        return identifier

    async def find_warning_by_spec(
        self,
        guild_id: int,
        identifier: str | ObjectId | None = None,
        snowflake: int | None = None,
        warning_type: str | None = None,
        moderator_id: int | None = None,
        user_id: int | None = None,
    ):
        """
        Removes a warning from the database by a particular specification. Useful for removing many warnings at one time.
        """
        if all(
            [
                identifier is None,
                warning_type is None,
                moderator_id is None,
                user_id is None,
                snowflake is None,
            ]
        ):
            return ValueError("At least one argument must be provided.")

        if snowflake is not None and all(
            [
                warning_type is None,
                moderator_id is None,
                user_id is None,
                identifier is None,
            ]
        ):
            return await self.db.find_one({"Snowflake": snowflake})

        if identifier is not None and all(
            [
                warning_type is None,
                moderator_id is None,
                user_id is None,
                snowflake is None,
            ]
        ):
            return await self.db.find_one({"_id": ObjectId(identifier)})

        map = {
            "Snowflake": snowflake,
            "Type": warning_type,
            "ModeratorID": moderator_id,
            "UserID": user_id,
            "Guild": guild_id,
        }

        for i, v in copy(map).items():
            if v is None:
                del map[i]

        return await self.db.find_one(map)

    def find_warnings_by_spec(
        self,
        guild_id: int,
        identifier: int | None = None,
        snowflake: int | None = None,
        warning_type: str | None = None,
        moderator_id: int | None = None,
        user_id: int | None = None,
        bolo: bool = False,
    ):
        """
        Finds a warnings by a specification.
        """
        if all(
            [
                identifier is None,
                warning_type is None,
                moderator_id is None,
                user_id is None,
                bolo is False,
            ]
        ):
            return ValueError("At least one argument must be provided.")

        if snowflake is not None and all(
            [
                warning_type is None,
                moderator_id is None,
                user_id is None,
                identifier is None,
            ]
        ):
            return self.db.find({"Snowflake": snowflake})

        if identifier is not None and all(
            [
                warning_type is None,
                moderator_id is None,
                user_id is None,
                snowflake is None,
            ]
        ):
            return self.db.find({"_id": identifier})

        if bolo and not warning_type:
            warning_type = {"$regex": "bolo", "$options": "i"}

        map = {
            "Snowflake": snowflake,
            "Type": warning_type,
            "ModeratorID": moderator_id,
            "UserID": user_id,
            "Guild": guild_id,
        }

        for i, v in copy(map).items():
            if v is None:
                del map[i]

        return self.db.find(map)

    async def remove_warnings_by_spec(
        self,
        guild_id: int,
        identifier: int | None = None,
        warning_type: str | None = None,
        moderator_id: int | None = None,
        user_id: int | None = None,
    ):
        """
        Removes a warning from the database by a particular specification. Useful for removing many warnings at one time.
        """
        # # print("!!!!")
        if all(
            [
                identifier is None,
                warning_type is None,
                moderator_id is None,
                user_id is None,
                guild_id is None,
            ]
        ):
            return ValueError("At least one argument must be provided.")

        if identifier is not None and all(
            [
                warning_type is None,
                moderator_id is None,
                user_id is None,
                guild_id is None,
            ]
        ):
            return await self.db.delete_many({"Snowflake": identifier})

        map = {
            "Snowflake": identifier,
            "Type": warning_type,
            "ModeratorID": moderator_id,
            "UserID": user_id,
            "Guild": guild_id,
        }

        for i, v in copy(map).items():
            if v is None:
                del map[i]

        storage = []
        async for i in self.db.find(map):
            storage.append(i)
            await self.db.delete_one({"_id": i["_id"]})

        bulk_writes = []
        for i in storage:
            l = copy(i)
            del l["_id"]
            bulk_writes.append(
                pymongo.operations.UpdateOne(
                    {"_id": i["_id"]}, {"$set": l}, upsert=True
                )
            )

        await self.recovery.db.bulk_write(bulk_writes)
        # await self.recovery.db.insert_many(storage)

    async def remove_warning_by_snowflake(
        self, identifier: int, guild_id: int | None = None
    ):
        """
        Removes a warning from the database by its snowflake.
        """

        selected_item = await self.db.find_one({"Snowflake": identifier})
        if selected_item["Guild"] == (guild_id or selected_item["Guild"]):
            try:
                url_var = config("BASE_API_URL")
                panel_url_var = config("PANEL_API_URL")
                if url_var not in ["", None]:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{url_var}/Internal/SyncDeletePunishment/{selected_item['_id']}",
                            headers={"Authorization": config("INTERNAL_API_AUTH")},
                        ):
                            pass
                if panel_url_var not in ["", None]:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{panel_url_var}/{guild_id}/SyncDeletePunishment?ID={identifier}",
                            headers={"Authorization": config("INTERNAL_API_AUTH")},
                        ):
                            pass
            except ValueError:
                pass
            return await self.db.delete_one({"Snowflake": identifier})
        else:
            return ValueError("Warning does not exist.")

    async def count_warnings(
        self,
        identifier: int | None = None,
        warning_type: str | None = None,
        moderator_id: int | None = None,
        user_id: int | None = None,
        guild_id: int | None = None,
    ):
        """
        Counts the warnings in the database.
        """

        map = {
            "Snowflake": identifier,
            "Type": warning_type,
            "ModeratorID": moderator_id,
            "UserID": user_id,
            "Guild": guild_id,
        }

        for i, v in copy(map).items():
            if v is None:
                del map[i]

        return await self.db.count_documents(map)
