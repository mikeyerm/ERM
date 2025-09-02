import aiohttp
import discord
from discord.ext import commands
from bson import ObjectId
from decouple import config
from datamodels.ShiftManagement import ShiftItem


class PRCPermissions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api_base = "https://apis.policeroleplay.community"
        self.api_key = config("PRC_API_KEY")  # store securely in .env

        # 🔑 Map shift types to PRC permission names
        self.shift_permission_map = {
            "Moderator": "Moderator",
            "Administrator": "Administrator",
            
            
        }

    async def set_permission(self, roblox_id: int, permission: str):
        """Grant a permission via PRC API"""
        url = f"{self.api_base}/SetPermission"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers={"Authorization": self.api_key},
                json={"UserId": roblox_id, "Permission": permission},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"Failed to set permission: {resp.status} - {text}")

    async def remove_permission(self, roblox_id: int, permission: str):
        """Remove a permission via PRC API"""
        url = f"{self.api_base}/RemovePermission"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                headers={"Authorization": self.api_key},
                json={"UserId": roblox_id, "Permission": permission},
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    print(f"Failed to remove permission: {resp.status} - {text}")

    @commands.Cog.listener()
    async def on_shift_start(self, object_id: ObjectId):
        """When a shift starts, grant permissions based on shift type"""
        shift: ShiftItem = await self.bot.shift_management.fetch_shift(object_id)
        roblox_id = shift.roblox_id  # assumes ShiftItem stores Roblox ID
        shift_type = shift.type

        permission = self.shift_permission_map.get(shift_type)
        if permission:
            await self.set_permission(roblox_id, permission)
        else:
            print(f"No PRC permission mapped for shift type: {shift_type}")

    @commands.Cog.listener()
    async def on_shift_end(self, object_id: ObjectId):
        """When a shift ends, remove permissions based on shift type"""
        shift: ShiftItem = await self.bot.shift_management.fetch_shift(object_id)
        roblox_id = shift.roblox_id
        shift_type = shift.type

        permission = self.shift_permission_map.get(shift_type)
        if permission:
            await self.remove_permission(roblox_id, permission)
        else:
            print(f"No PRC permission mapped for shift type: {shift_type}")


async def setup(bot: commands.Bot):
    await bot.add_cog(PRCPermissions(bot))
