import discord
from discord.ext import commands
import asyncio
import datetime
import pytz
from erm import is_management, is_staff, is_admin
from utils.advanced import FakeMessage
from utils.constants import BLANK_COLOR, GREEN_COLOR
from menus import ManageActions, CounterButton, ViewVotersButton
from discord import app_commands
from utils.autocompletes import action_autocomplete
from utils.paginators import CustomPage, SelectPagination
from utils.utils import get_prefix, interpret_content, interpret_embed, log_command_usage


class Actions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: commands.Bot = bot

    @commands.hybrid_group(
        name="actions", description="Manage your ERM Actions easily."
    )
    async def actions(self, ctx: commands.Context):
        pass

    @actions.command(name="manage", description="Manage your ERM Actions easily.")
    @is_admin()
    async def actions_manage(self, ctx: commands.Context):
        await log_command_usage(self.bot, ctx.guild, ctx.author, f"Actions Manage")
        actions = [i async for i in self.bot.db.actions.find({"Guild": ctx.guild.id})]

        embeds = []
        current_embed = discord.Embed(title="Actions", color=BLANK_COLOR).set_author(
            name=ctx.guild.name, icon_url=ctx.guild.icon
        )

        for item in actions:
            if len(current_embed.fields) >= 5:
                embeds.append(current_embed)
                current_embed = discord.Embed(
                    title="Actions (cont.)", color=BLANK_COLOR
                )

            current_embed.add_field(
                name=item["ActionName"],
                value=(
                    f"> **Name:** {item['ActionName']}\n"
                    f"> **ID:** `{item['ActionID']}`\n"
                    f"> **Triggered:** {item['Triggers']}"
                ),
                inline=False,
            )

        if len(current_embed.fields) == 0:
            current_embed.add_field(
                name="No Actions",
                value="> There are no actions in this server.",
                inline=False,
            )

        embeds.append(current_embed)

        view = ManageActions(self.bot, ctx.author.id)
        if len(embeds) > 9:
            paginator = SelectPagination(
                self.bot, ctx.author.id, [CustomPage(
                    embeds=embeds[i],
                    view=view,
                    identifier=i
                ) for i in range(len(embeds))], timeout=60
            )
            await ctx.send(embeds=embeds[0].embeds, view=paginator.get_current_view())
        else:
            await ctx.send(embeds=embeds, view=view)
        timeout = await view.wait()
        if timeout:
            return

    @actions.command(name="execute", description="Execute an ERM Action in your server")
    @is_staff()
    @app_commands.autocomplete(action=action_autocomplete)
    async def action_execute(self, ctx: commands.Context, *, action: str):

        verbose = False
        dnr = False
        if "--verbose" in action:
            action = action.replace(" --verbose", "")
            verbose = True
        try:
            dnr = getattr(ctx, "dnr")  # prevent privilege bypassing! no black hats
        except Exception as _:
            dnr = False

        ctx.verbose = verbose

        actions = [
            i async for i in self.bot.actions.db.find({"Guild": ctx.guild.id})
        ] or []
        action_obj = None
        for item in actions:
            if item["ActionName"] == action:
                action_obj = item
                break
        if not action_obj and not dnr:
            return await ctx.send(
                embed=discord.Embed(
                    title="Invalid Action Name",
                    description="The name you provided does not correspond with an action on this server. Run `/actions manage` for details.",
                    color=BLANK_COLOR,
                )
            )

        if action_obj.get("AccessRoles"):
            if (
                not any(
                    [discord.utils.get(ctx.guild.roles, id=i) in ctx.author.roles]
                    for i in action_obj.get("AccessRoles")
                )
                and not dnr
            ):
                return await ctx.send(
                    embed=discord.Embed(
                        title="Access Denied",
                        description="You do not hold the roles required to use this action. Contact your Server Administrator for details.",
                        color=BLANK_COLOR,
                    )
                )
        #   actions = [
        #     'Execute Custom Command',
        #     'Pause Reminder',
        #     'Force All Staff Off Duty',
        #     'Send ER:LC Command',
        #     'Send ER:LC Message',
        #     'Send ER:LC Hint',
        #     'Delay'
        # ]

        funcs = [
            self.execute_custom_command,
            self.pause_reminder,
            self.force_off_duty,
            self.send_erlc_command,
            self.send_erlc_message,
            self.send_erlc_hint,
            self.delay,
            self.add_role,
            self.remove_role,
            self.execute_erm_command
        ]

        if not dnr:
            msg = await ctx.send(
                embed=discord.Embed(
                    title=f"{self.bot.emoji_controller.get_emoji('success')} Running Action",
                    description=f"**(0/{len(action_obj['Integrations'])})** I am currently running your action!",
                    color=GREEN_COLOR,
                )
            )

        chosen_funcs = []
        for item in action_obj["Integrations"]:
            chosen_funcs.append(
                [funcs[item["IntegrationID"]], item["ExtraInformation"]]
            )

        returns = []
        if dnr:
            chosen_funcs = list(
                filter(
                    lambda x: x not in [self.add_role, self.remove_role], chosen_funcs
                )
            )

        for func, param in chosen_funcs:
            if param is None:
                returns.append(await func(self.bot, ctx.guild.id, ctx))
            else:
                returns.append(await func(self.bot, ctx.guild.id, ctx, param))
            if not dnr:
                await msg.edit(
                    embed=discord.Embed(
                        title=f"{self.bot.emoji_controller.get_emoji('success')} Running Action",
                        description=f"**({len(list(filter(lambda x: x == 0, returns)))}/{len(action_obj['Integrations'])})** I am currently running your action!{' `{}`'.format(returns) if verbose else ''}",
                        color=GREEN_COLOR,
                    )
                )

    @staticmethod
    async def add_role(bot: commands.Bot, guild_id: int, context, role_id: int):
        try:
            guild = await bot.fetch_guild(guild_id)
            role = guild.get_role(role_id)
        except discord.HTTPException:
            return 1

        if not role:
            return 1

        try:
            await context.author.add_roles(role)
        except discord.HTTPException:
            return 1

    @staticmethod
    async def remove_role(bot: commands.Bot, guild_id: int, context, role_id: int):
        try:
            guild = await bot.fetch_guild(guild_id)
            role = guild.get_role(role_id)
        except discord.HTTPException:
            return 1

        if not role:
            return 1

        try:
            await context.author.remove_roles(role)
        except discord.HTTPException:
            return 1

    @staticmethod
    async def execute_custom_command(
        bot, guild_id: int, context, custom_command_name: str
    ):
        Data = await bot.custom_commands.find_by_id(guild_id)
        guild = context.guild
        if Data is None:
            return 1

        is_command = False
        selected = None
        if "commands" in Data.keys():
            if isinstance(Data["commands"], list):
                for cmd in Data["commands"]:
                    if cmd["name"].lower().replace(
                        " ", ""
                    ) == custom_command_name.lower().replace(" ", ""):
                        is_command = True
                        selected = cmd

        if not is_command:
            return 1

        channel = None
        if not channel:
            if selected.get("channel") is None:
                channel = context.channel
            else:
                channel = (
                    discord.utils.get(guild.text_channels, id=selected["channel"])
                    if discord.utils.get(guild.text_channels, id=selected["channel"])
                    is not None
                    else context.channel
                )
        embeds = []
        for embed in selected["message"]["embeds"]:
            embeds.append(
                await interpret_embed(bot, context, channel, embed, selected["id"])
            )

        view = discord.ui.View()
        for item in selected.get("buttons", []):
            if item["label"] == "0" and "row" in item:
                counter_button = CounterButton(row=item["row"])
                view_voters_button = ViewVotersButton(
                    row=item["row"], counter_button=counter_button
                )
                view.add_item(counter_button)
                view.add_item(view_voters_button)
            else:
                view.add_item(
                    discord.ui.Button(
                        label=item["label"],
                        url=item["url"],
                        row=item["row"],
                        style=discord.ButtonStyle.url,
                    )
                )

        if (
            selected["message"]["content"] in [None, ""]
            and len(selected["message"]["embeds"]) == 0
        ):
            return 1

        msg = await channel.send(
            await interpret_content(
                bot, context, channel, selected["message"]["content"], selected["id"]
            ),
            embeds=embeds,
            view=view,
            allowed_mentions=discord.AllowedMentions(
                everyone=True, users=True, roles=True, replied_user=True
            ),
        )

        # Fetch ICS entry
        doc = await bot.ics.find_by_id(selected["id"]) or {}
        if doc in [None, {}]:
            return 0  # This is still successful, just means it doesn't use ICS
        doc["associated_messages"] = (
            [(channel.id, msg.id)]
            if not doc.get("associated_messages")
            else doc["associated_messages"] + [(channel.id, msg.id)]
        )
        await bot.ics.update_by_id(doc)
        return 0

    @staticmethod
    async def pause_reminder(bot, guild_id: int, context, reminder_name: str):
        reminder_data = await bot.reminders.find_by_id(guild_id) or []

        for index, item in enumerate(reminder_data["reminders"]):
            if item["name"] == reminder_name:
                if item.get("paused") is True:
                    item["paused"] = False
                    reminder_data["reminders"][index] = item
                    await bot.reminders.upsert(reminder_data)
                    return 0
                else:
                    item["paused"] = True
                    reminder_data["reminders"][index] = item
                    await bot.reminders.upsert(reminder_data)
                    return 0

        return 1

    @staticmethod
    async def force_off_duty(bot, guild_id: int, context):
        docs = [
            i
            async for i in bot.shift_management.shifts.db.find(
                {"Guild": guild_id, "EndEpoch": 0}
            )
        ]
        for item in docs:
            id = item["_id"]
            await bot.shift_management.shifts.db.update_one(
                {"_id": id},
                {
                    "$set": {
                        "EndEpoch": int(datetime.datetime.now(tz=pytz.UTC).timestamp())
                    }
                },
            )
            bot.dispatch("shift_end", id)
            if context.verbose:
                await context.send(item)
        return 0

    @staticmethod
    async def send_erlc_command(bot, guild_id: int, context, command: str):
        if command[0] != ":":
            command = ":" + command

        command_response = await bot.prc_api.run_command(guild_id, f"{command}")
        if command_response[0] == 200:
            return 0

        if command_response[0] != 429:
            return 1

        wait_time = command_response[1]["retry_after"]
        await asyncio.sleep(wait_time + 1)
        command_response = await bot.prc_api.run_command(guild_id, f"{command}")
        if command_response[0] == 200:
            return 0

        if command_response[0] != 429:
            return 1

    @staticmethod
    async def send_erlc_message(bot, guild_id: int, context, message: str):
        if message[:3] == ":m ":
            message = message[3:]
        elif message[:2] == "m ":
            message = message[2:]

        command_response = await bot.prc_api.run_command(guild_id, f":m {message}")
        if command_response[0] == 200:
            return 0

        if command_response[0] != 429:
            return 1

        wait_time = command_response[1]["retry_after"]
        await asyncio.sleep(wait_time + 1)
        command_response = await bot.prc_api.run_command(guild_id, f":m {message}")
        if command_response[0] == 200:
            return 0

        if command_response[0] != 429:
            return 1
        
    @staticmethod
    async def execute_erm_command(bot, guild_id: int, context, command: str):
        guild: discord.Guild = bot.get_guild(guild_id) or await bot.fetch_guild(guild_id)
        message = FakeMessage(
            content=bot.user.mention + " " + command,
            author=context.author,
            channel=await context.author.create_dm() if context.author else guild.system_channel or guild.text_channels[0],
            state=bot._connection
        )
        message.guild = guild
        try:
            await bot.process_commands(message)
        except:
            return 1
        return 0

    @staticmethod
    async def send_erlc_hint(bot, guild_id: int, context, hint: str):
        if hint[:3] == ":h ":
            hint = hint[3:]

        command_response = await bot.prc_api.run_command(guild_id, f":h {hint}")
        if command_response[0] == 200:
            return 0

        if command_response[0] != 429:
            return 1

        wait_time = command_response[1]["retry_after"]
        await asyncio.sleep(wait_time + 1)
        command_response = await bot.prc_api.run_command(guild_id, f":h {hint}")
        if command_response[0] == 200:
            return 0

        if command_response[0] != 429:
            return 1

    @staticmethod
    async def delay(bot, guild_id, context, timer: int):
        ## FOR THIS EXAMPLE, WE DO NOT NEED BOT AND GUILD ID
        try:
            await asyncio.sleep(int(timer))
        except:
            return 1
        return 0


async def setup(bot: commands.Bot):
    await bot.add_cog(Actions(bot))
