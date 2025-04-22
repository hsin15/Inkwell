import discord
from discord.ext import commands
import os

# SETUP INTENTS
intents = discord.Intents.default()
intents.members = True  # Required for member join/leave tracking

# CONFIGURE BOT
bot = commands.Bot(command_prefix="!", intents=intents)

# CONFIGURE ADMIN ROLE NAME
ADMIN_ROLE_NAME = "Admin"

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.event
async def on_member_join(member):
    guild = member.guild
    print(f"👤 New member joined: {member.name}")

    # Get the Admin role
    admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)

    # Check bot's permissions
    bot_member = guild.get_member(bot.user.id)
    bot_perms = guild.me.guild_permissions
    print(f"🛠 Bot permissions in guild: {bot_perms}")

    if not bot_perms.manage_channels:
        print("❌ Bot does not have 'Manage Channels' permission.")
        return

    # Set up permissions
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }
    if admin_role:
        overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, manage_channels=True)

    # Create category
    category_name = f"{member.name}'s Projects"
    try:
        category = await guild.create_category(name=category_name, overwrites=overwrites)
        print(f"✅ Created category: {category.name}")

        # Create text channel
        project_channel = await guild.create_text_channel(name="project", category=category)
        welcome_message = (
            f"Welcome, {member.mention}! This is your space to track writing projects.\n"
            f"\"{member.name}'s Projects\" is your category, and where you are reading now is your writing project! Please rename both the category to your actual name (not your username) by right clicking and selecting 'Edit Category'. You can similarly rename your project (this page) to the name of your current WIP by right clicking and selecting 'Edit Channel'.\n\n"
            "I recommend you create a new channel within your category for each project. You can do this by selecting the + symbol next to the category and selecting 'Create Text Channel'. You can also delete this channel if you don't need it or if you choose not to proceed with a project anymore.\n\n"
            "This is the space where other members will get to see where you're up to and what's happening with your work. I recommend using the below format when updating your project, a little bit like a logbook so we can see where you are at:\n\n"
            "Title:\n"
            "Genre:\n"
            "Word Count:\n"
            "Stage: (e.g. outlining/ideas, drafting, 2nd draft, editing, dev edits, line edits, copy edits, published)\n\n"
            "If you leave the server, this category (and its channels) will be deleted automatically.\n\n"
            "Message Henry if you have any questions or need help!"
        )
        await project_channel.send(welcome_message)
        print(f"✅ Created 'project' channel for {member.name}")

    except discord.Forbidden:
        print("❌ Permission error while creating category/channel.")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

@bot.event
async def on_member_remove(member):
    guild = member.guild
    category_name = f"{member.name}'s Projects"

    # Search for the category
    category = discord.utils.get(guild.categories, name=category_name)
    if category:
        try:
            for channel in category.channels:
                await channel.delete()
            await category.delete()
            print(f"🗑️ Deleted category and channels for {member.name}")
        except Exception as e:
            print(f"❌ Failed to delete category: {e}")

# RUN THE BOT
bot.run(os.getenv("YOUR_BOT_TOKEN"))