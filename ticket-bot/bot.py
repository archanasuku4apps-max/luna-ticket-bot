import discord
from discord.ext import commands, tasks
import os
import asyncio
import io
from datetime import timezone

TOKEN = os.environ.get("DISCORD_TICKET_BOT_TOKEN")
if not TOKEN:
raise RuntimeError("DISCORD_TICKET_BOT_TOKEN environment variable is required.")

STAFF_ROLES = ["Owner", "Admin", "Moderator", "Discord Staff"]
TICKET_CATEGORY_NAME = "Support"
BANNER_PATH = os.path.join(os.path.dirname(file), "panel_banner.gif")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

── helpers ────────────────────────────────────────────────────────────────────

def is_staff(member: discord.Member) -> bool:
return any(
discord.utils.get(member.guild.roles, name=r) in member.roles
for r in STAFF_ROLES
)

── Ticket type dropdown ───────────────────────────────────────────────────────

class TicketTypeSelect(discord.ui.Select):
def init(self):
options = [
discord.SelectOption(
label="General Support",
description="Get help with a general question",
emoji="🎫",
value="general",
),
discord.SelectOption(
label="Report a User",
description="Report a rule-breaking member",
emoji="🚨",
value="report",
),
discord.SelectOption(
label="Appeal a Punishment",
description="Appeal a mute, kick, or ban",
emoji="⚖️",
value="appeal",
),
discord.SelectOption(
label="Other",
description="Any other request or question",
emoji="❓",
value="other",
),
]
super().init(
placeholder="Select a ticket category…",
min_values=1,
max_values=1,
options=options,
custom_id="ticket_type_select",
)

async def callback(self, interaction: discord.Interaction):  
    await interaction.response.defer(ephemeral=True)  
    guild = interaction.guild  
    member = interaction.user  

    # Find or create the Support category  
    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)  
    if category is None:  
        overwrites = {  
            guild.default_role: discord.PermissionOverwrite(view_channel=False),  
        }  
        for role_name in STAFF_ROLES:  
            role = discord.utils.get(guild.roles, name=role_name)  
            if role:  
                overwrites[role] = discord.PermissionOverwrite(  
                    view_channel=True,  
                    send_messages=True,  
                    read_message_history=True,  
                )  
        category = await guild.create_category(TICKET_CATEGORY_NAME, overwrites=overwrites)  

    # Check if member already has an open ticket  
    existing = discord.utils.get(  
        category.channels,  
        name=f"ticket-{member.name.lower()}"  
    )  
    if existing:  
        await interaction.followup.send(  
            f"❌ You already have an open ticket: {existing.mention}",  
            ephemeral=True,  
        )  
        return  

    ticket_type = self.values[0]  

    # Channel permissions  
    overwrites = {  
        guild.default_role: discord.PermissionOverwrite(view_channel=False),  
        member: discord.PermissionOverwrite(  
            view_channel=True,  
            send_messages=True,  
            read_message_history=True,  
        ),  
    }  
    for role_name in STAFF_ROLES:  
        role = discord.utils.get(guild.roles, name=role_name)  
        if role:  
            overwrites[role] = discord.PermissionOverwrite(  
                view_channel=True,  
                send_messages=True,  
                read_message_history=True,  
                manage_messages=True,  
            )  

    channel = await category.create_text_channel(  
        name=f"ticket-{member.name.lower()}",  
        overwrites=overwrites,  
        topic=f"Ticket by {member} | Type: {ticket_type} | Claimed by: Unclaimed",  
    )  

    staff_mentions = " ".join(  
        role.mention  
        for role_name in STAFF_ROLES  
        if (role := discord.utils.get(guild.roles, name=role_name))  
    )  

    label_map = {  
        "general": "General Support",  
        "report": "Report a User",  
        "appeal": "Appeal a Punishment",  
        "other": "Other",  
    }  

    embed = discord.Embed(  
        title="🎫 Support Ticket",  
        description=(  
            f"Hello {member.mention}, welcome to your ticket!\n\n"  
            f"**Type:** {label_map.get(ticket_type, ticket_type)}\n"  
            f"**Claimed by:** Unclaimed\n\n"  
            "Please describe your issue and a staff member will assist you shortly.\n\n"  
            f"Staff: {staff_mentions if staff_mentions else '*(no staff roles found)*'}"  
        ),  
        color=discord.Color.blurple(),  
    )  
    embed.set_footer(text="Use the buttons below to claim or close this ticket.")  

    await channel.send(  
        content=member.mention,  
        embed=embed,  
        view=TicketActionView(),  
    )  

    await interaction.followup.send(  
        f"✅ Your ticket has been created: {channel.mention}",  
        ephemeral=True,  
    )

class TicketPanelView(discord.ui.View):
def init(self):
super().init(timeout=None)
self.add_item(TicketTypeSelect())

── Ticket action buttons (Claim + Close) ─────────────────────────────────────

class TicketActionView(discord.ui.View):
def init(self):
super().init(timeout=None)

@discord.ui.button(  
    label="✋ Claim Ticket",  
    style=discord.ButtonStyle.success,  
    custom_id="claim_ticket",  
)  
async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):  
    member = interaction.user  
    channel = interaction.channel  

    if not is_staff(member):  
        await interaction.response.send_message(  
            "❌ Only staff members can claim tickets.",  
            ephemeral=True,  
        )  
        return  

    # Update channel topic to reflect claimer  
    old_topic = channel.topic or ""  
    new_topic = old_topic.replace(  
        "Claimed by: Unclaimed",  
        f"Claimed by: {member}",  
    )  
    if "Claimed by:" not in new_topic:  
        new_topic += f" | Claimed by: {member}"  
    await channel.edit(topic=new_topic)  

    # Disable the claim button so it can't be re-claimed  
    button.disabled = True  
    button.label = f"✋ Claimed by {member.display_name}"  
    await interaction.response.edit_message(view=self)  

    embed = discord.Embed(  
        description=f"✅ This ticket has been claimed by {member.mention}.",  
        color=discord.Color.green(),  
    )  
    await channel.send(embed=embed)  

@discord.ui.button(  
    label="🔒 Close Ticket",  
    style=discord.ButtonStyle.danger,  
    custom_id="close_ticket",  
)  
async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):  
    channel = interaction.channel  
    member = interaction.user  

    is_owner = channel.topic and str(member) in channel.topic  

    if not is_staff(member) and not is_owner:  
        await interaction.response.send_message(  
            "❌ Only the ticket owner or staff can close this ticket.",  
            ephemeral=True,  
        )  
        return  

    await interaction.response.defer()  

    # ── Build transcript ───────────────────────────────────────────────────  
    messages = [m async for m in channel.history(limit=None, oldest_first=True)]  

    lines = [  
        f"Transcript for: #{channel.name}",  
        f"Server: {channel.guild.name}",  
        f"Closed by: {member} ({member.id})",  
        f"Total messages: {len(messages)}",  
        "=" * 60,  
        "",  
    ]  
    for m in messages:  
        ts = m.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")  
        content = m.content or ""  
        if m.embeds:  
            content += " [embed]" * len(m.embeds)  
        if m.attachments:  
            content += " " + " ".join(f"[attachment: {a.filename}]" for a in m.attachments)  
        lines.append(f"[{ts}] {m.author} ({m.author.id}): {content}")  

    transcript_text = "\n".join(lines)  
    transcript_file = discord.File(  
        fp=io.BytesIO(transcript_text.encode("utf-8")),  
        filename=f"transcript-{channel.name}.txt",  
    )  

    # ── Parse ticket owner from topic ──────────────────────────────────────  
    # topic format: "Ticket by User#0000 | Type: ... | Claimed by: ..."  
    ticket_owner = None  
    if channel.topic and "Ticket by " in channel.topic:  
        owner_str = channel.topic.split("Ticket by ")[1].split(" |")[0].strip()  
        ticket_owner = discord.utils.find(  
            lambda m: str(m) == owner_str,  
            channel.guild.members,  
        )  

    # ── DM transcript to ticket owner ──────────────────────────────────────  
    dm_sent = False  
    if ticket_owner:  
        try:  
            dm_embed = discord.Embed(  
                title="📄 Your Ticket Transcript",  
                description=(  
                    f"Your ticket **#{channel.name}** in **{channel.guild.name}** has been closed.\n"  
                    "A full transcript of the conversation is attached below."  
                ),  
                color=discord.Color.blurple(),  
            )  
            dm_embed.set_footer(text=f"Closed by {member}")  
            transcript_file_dm = discord.File(  
                fp=io.BytesIO(transcript_text.encode("utf-8")),  
                filename=f"transcript-{channel.name}.txt",  
            )  
            await ticket_owner.send(embed=dm_embed, file=transcript_file_dm)  
            dm_sent = True  
        except discord.Forbidden:  
            pass  

    # ── Post to #ticket-transcripts log channel if it exists ───────────────  
    log_channel = discord.utils.get(channel.guild.text_channels, name="ticket-transcripts")  
    if log_channel:  
        log_embed = discord.Embed(  
            title="📄 Ticket Closed",  
            description=(  
                f"**Channel:** #{channel.name}\n"  
                f"**Opened by:** {ticket_owner.mention if ticket_owner else 'Unknown'}\n"  
                f"**Closed by:** {member.mention}\n"  
                f"**Messages:** {len(messages)}"  
            ),  
            color=discord.Color.orange(),  
        )  
        transcript_file_log = discord.File(  
            fp=io.BytesIO(transcript_text.encode("utf-8")),  
            filename=f"transcript-{channel.name}.txt",  
        )  
        await log_channel.send(embed=log_embed, file=transcript_file_log)  

    # ── Closing message then delete ────────────────────────────────────────  
    close_embed = discord.Embed(  
        title="🔒 Ticket Closing",  
        description=(  
            f"Closed by {member.mention}.\n"  
            f"{'📬 Transcript sent to your DMs.' if dm_sent else '📬 Could not DM transcript (DMs may be disabled).'}\n\n"  
            "Deleting in 5 seconds…"  
        ),  
        color=discord.Color.red(),  
    )  
    await interaction.followup.send(embed=close_embed)  
    await asyncio.sleep(5)  
    await channel.delete(reason=f"Ticket closed by {member}")

── Information Center dropdown ────────────────────────────────────────────────

INFO_RESPONSES = {
"ticket": {
"title": "🎫 How to Open a Ticket",
"description": (
"Follow these steps to open a support ticket:\n\n"
"1. Go to the Ticket Panel.\n"
"2. Select the appropriate category.\n"
"3. Explain your issue clearly.\n"
"4. Wait for a staff member to respond.\n\n"
"Our staff will assist you as soon as possible."
),
},
"rules": {
"title": "📜 Server Rules",
"description": (
"Please follow these rules at all times:\n\n"
"1. Respect all members.\n"
"2. No spam or advertising.\n"
"3. No NSFW content.\n"
"4. Follow staff instructions.\n\n"
"Failure to comply may result in a mute, kick, or ban."
),
},
"info": {
"title": "🎮 Server Information",
"description": (
"Welcome to our community!\n\n"
"This server provides community support, events, updates, "
"and a friendly environment for all members.\n\n"
"🌐 Languages Supported: English & Malayalam\n"
"🛡️ Moderation: Active staff team\n"
"🎉 Events: Regular community events\n\n"
"We're glad to have you here!"
),
},
"staff": {
"title": "👑 Staff Applications",
"description": (
"Unfortunately, it is not possible to apply as a Moderator.\n\n"
"We select trusted and active members from the community to fill this role "
"based on their behaviour, activity, and contributions.\n\n"
"⚠️ Please keep in mind that asking to become a Moderator will not increase "
"your chances of being chosen — it may actually lower them.\n\n"
"Keep being a positive member of the community!"
),
},
"bug": {
"title": "🐞 Bug Reports",
"description": (
"When reporting a bug, please include:\n\n"
"📸 Provide screenshots if possible.\n"
"📝 Explain the issue clearly.\n"
"🔁 Include steps to reproduce the problem.\n\n"
"Detailed reports help us fix issues faster. Thank you!"
),
},
"faq": {
"title": "❓ Frequently Asked Questions",
"description": (
"Q: How long does support take?\n"
"A: Usually within 24 hours.\n\n"
"Q: Can I open multiple tickets?\n"
"A: No, only one ticket at a time.\n\n"
"Q: Where can I contact staff?\n"
"A: Through the ticket system.\n\n"
"If your question isn't here, open a ticket!"
),
},
}

class InfoSelect(discord.ui.Select):
def init(self):
options = [
discord.SelectOption(
label="How to Open a Ticket",
description="Step-by-step guide to opening a support ticket",
emoji="🎫",
value="ticket",
),
discord.SelectOption(
label="Server Rules",
description="Rules every member must follow",
emoji="📜",
value="rules",
),
discord.SelectOption(
label="Server Information",
description="Learn about this community server",
emoji="🎮",
value="info",
),
discord.SelectOption(
label="Staff Applications",
description="Find out about becoming a staff member",
emoji="👑",
value="staff",
),
discord.SelectOption(
label="Bug Reports",
description="How to properly report a bug",
emoji="🐞",
value="bug",
),
discord.SelectOption(
label="Frequently Asked Questions",
description="Answers to common questions",
emoji="❓",
value="faq",
),
]
super().init(
placeholder="📖 Select a topic to learn more…",
min_values=1,
max_values=1,
options=options,
custom_id="info_select",
)

async def callback(self, interaction: discord.Interaction):  
    data = INFO_RESPONSES.get(self.values[0])  
    if not data:  
        await interaction.response.send_message("❌ Unknown option.", ephemeral=True)  
        return  

    embed = discord.Embed(  
        title=data["title"],  
        description=data["description"],  
        color=0x9B59B6,  
    )  
    embed.set_footer(text="DIOS PROJECTION • Information Center")  
    await interaction.response.send_message(embed=embed, ephemeral=True)

class InfoPanelView(discord.ui.View):
def init(self):
super().init(timeout=None)
self.add_item(InfoSelect())

── !panel command ─────────────────────────────────────────────────────────────

@bot.command(name="panel")
@commands.has_permissions(manage_guild=True)
async def panel(ctx: commands.Context):
embed = discord.Embed(
title="🎫 Support Tickets",
description=(
"Need help? Open a ticket by selecting a category from the dropdown below.\n\n"
"Categories:\n"
"🎫 General Support\n"
"🚨 Report a User\n"
"⚖️ Appeal a Punishment\n"
"❓ Other"
),
color=discord.Color.blurple(),
)
embed.set_image(url="attachment://panel_banner.gif")
embed.set_footer(text="Support • Select a category below to open a ticket")

file = discord.File(BANNER_PATH, filename="panel_banner.gif")  
await ctx.send(embed=embed, file=file, view=TicketPanelView())  
await ctx.message.delete()

@panel.error
async def panel_error(ctx, error):
if isinstance(error, commands.MissingPermissions):
await ctx.reply("❌ You need Manage Server permission to use this command.")

── !infopanel command ─────────────────────────────────────────────────────────

@bot.command(name="infopanel")
@commands.has_permissions(manage_guild=True)
async def infopanel(ctx: commands.Context):
embed = discord.Embed(
title="📚 Information Center",
description=(
"Welcome to our Community Support Center.\n\n"
"Please read the information below before opening a support ticket.\n\n"
"🌐 English and Malayalam support are available.\n\n"
"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
"🎫 How to Open a Ticket\n"
"📜 Server Rules\n"
"🎮 Server Information\n"
"👑 Staff Applications\n"
"🐞 Bug Reports\n"
"❓ Frequently Asked Questions\n"
"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
"Select a topic from the dropdown below to learn more."
),
color=0x9B59B6,
)
embed.set_footer(text="DIOS PROJECTION • Information Center • Only visible to you when selected")
await ctx.send(embed=embed, view=InfoPanelView())
await ctx.message.delete()

@infopanel.error
async def infopanel_error(ctx, error):
if isinstance(error, commands.MissingPermissions):
await ctx.reply("❌ You need Manage Server permission to use this command.")

── Heartbeat ──────────────────────────────────────────────────────────────────

@tasks.loop(hours=1)
async def heartbeat():
guilds = len(bot.guilds)
latency = round(bot.latency * 1000)
print(f"💓 Heartbeat — ticket bot alive | guilds={guilds} | ping={latency}ms")

── Persist views on restart ───────────────────────────────────────────────────

@bot.event
async def on_ready():
bot.add_view(TicketPanelView())
bot.add_view(TicketActionView())
bot.add_view(InfoPanelView())
print(f"✅ Ticket bot online as {bot.user} ({bot.user.id})")
if not heartbeat.is_running():
heartbeat.start()

bot.run(TOKEN)
