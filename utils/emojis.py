import os
import asyncio
import nest_asyncio

nest_asyncio.apply()  # dangerous!

default_emojis = {
    "check": 1163142000271429662,
    "xmark": 1166139967920164915,
    "success": 1163149118366040106,
    "error": 1164666124496019637,
    "WarningIcon": 1035258528149033090,
    "loa": 1169799727143977090,
    "log": 1163524830319104171,
    "shift": 1169801400545452033,
    "Clock": 1035308064305332224,
    "ShiftStarted": 1178033763477889175,
    "ShiftBreak": 1178034531702411375,
    "ShiftEnded": 1178035088655646880,
    "arrow": 1169695690784518154,
    "l_arrow": 1169754353326903407,
    "security": 1169804198741823538,
}


class EmojiController:
    def __init__(self, bot):
        self.environment = bot.environment
        self.bot = bot
        self.emojis = {}

    async def prefetch_emojis(self):

        application_emojis = await self.bot.fetch_application_emojis()
        for item in os.listdir("assets/emojis"):
            if item.endswith(".png"):
                if item.replace(".png", "") not in [i.name for i in application_emojis]:
                    emoji_name = item.replace(".png", "")
                    image_data = open(f"assets/emojis/{item}", "rb").read()
                    await self.bot.create_application_emoji(
                        name=emoji_name, image=image_data
                    )

        new_application_emojis = await self.bot.fetch_application_emojis()
        for emoji in new_application_emojis:
            self.emojis[emoji.name] = emoji.id

    def get_emoji(self, emoji_name):
        if not self.emojis:
            asyncio.run(self.prefetch_emojis())

        return "<:{}:{}>".format(emoji_name, self.emojis[emoji_name])
