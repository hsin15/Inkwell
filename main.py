import discord
from discord.ext import commands, tasks
import os
from datetime import datetime, timedelta
import pytz
import re

# SETUP INTENTS
intents = discord.Intents.default()
intents.members = True
intents.messages = True
intents.message_content = True

# CONFIGURE BOT
bot = commands.Bot(command_prefix="!", intents=intents)

# ADMIN ROLE
ADMIN_ROLE_NAME = "Admin"

# IN-MEMORY STORAGE
user_projects = {}
user_categories = {}
user_goals = {}
user_project_metadata = {}

# UTIL: TRACKER BUILDER
def build_tracker(name, genre, stage, current_wc, goal_wc):
    try:
        percent = round(current_wc / goal_wc * 100)
        bar = "█" * (percent // 10) + "░" * (10 - percent // 10)
    except (ValueError, ZeroDivisionError):
        percent = 0
        bar = "░" * 10
        current_wc, goal_wc = 0, 1

    return (
        f"📌 **Progress Tracker for _{name}_**\n"
        f"**Genre:** {genre}\n"
        f"**Stage:** {stage}\n"
        f"`{bar}` {percent}% complete\n"
        f"**Word Count:** {current_wc} / {goal_wc}\n"
        f"_Last updated: {datetime.utcnow().strftime('%Y-%m-%d')}_\n\n"
        f"To update, even if one is the same, post both of the below in matching format:\n"
        "`Current Word Count: [new count]`\n"
        "`Stage: [new stage]`"
    )

# BOT READY
def start_tasks():
    if not weekly_goal_prompt.is_running():
        weekly_goal_prompt.start()
    if not inactivity_reminder.is_running():
        inactivity_reminder.start()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    start_tasks()

# NEW MEMBER INTAKE
@bot.event
async def on_member_join(member):
    guild = member.guild

    def check(msg):
        return msg.author == member and isinstance(msg.channel, discord.DMChannel)

    try:
        await member.send("🐾 Well, well. Another writer in need of a cozy corner...")
        await member.send("What’s your name?")
        name_msg = await bot.wait_for("message", check=check, timeout=300)
        user_name = name_msg.content.strip()

        word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                       "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

        while True:
            await member.send("How many projects are you juggling?\n(Enter a number or a word between 1 and 10, e.g. `3` or `three`)")
            try:
                response = await bot.wait_for("message", check=check, timeout=300)
                num_text = response.content.strip().lower()
                num_projects = int(num_text) if num_text.isdigit() else word_to_num[num_text]
                break
            except (KeyError, ValueError):
                await member.send("❌ That wasn’t a valid number. Try again with something like `2` or `two`.")

        admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)

        category = await guild.create_category(name=f"{user_name}'s Projects", overwrites=overwrites)
        user_categories[member.id] = category.id
        user_projects[member.id] = []

        for i in range(1, num_projects + 1):
            while True:
                await member.send(f"📘 Project #{i}? Reply with: `Title, Genre, Current Word Count, Goal Word Count, Stage`")
                msg = await bot.wait_for("message", check=check, timeout=300)
                parts = [p.strip() for p in msg.content.split(",")]

                if len(parts) < 5:
                    await member.send("❌ I need all five details. Try again.")
                    continue

                try:
                    title, genre, current, goal, stage = parts
                    current_wc = int(current)
                    goal_wc = int(goal)
                except ValueError:
                    await member.send("❌ Word counts must be numbers. Try again.")
                    continue

                channel = await guild.create_text_channel(name=title.lower().replace(" ", "-"), category=category)
                tracker = await channel.send(build_tracker(title, genre, stage, current_wc, goal_wc))
                await tracker.pin()
                user_projects[member.id].append((channel.id, title, datetime.utcnow(), goal_wc, tracker.id, stage))
                user_project_metadata[channel.id] = (member.id, title, genre, goal_wc)
                break

        await member.send("✅ All done! Your writing den is ready.")

    except Exception as e:
        print(f"❌ Intake error: {e}")

# WEEKLY GOAL DM
@tasks.loop(minutes=1)
async def weekly_goal_prompt():
    now = datetime.now(pytz.timezone("Australia/Sydney"))
    if now.weekday() == 6 and now.hour == 15 and now.minute == 0:
        for guild in bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                try:
                    await member.send(
                        "🐾 Good afternoon, authorling. The scribbling hour is upon us once more.\n\n"
                        "**How’s your project going?**\n"
                        "Update your personal channel logbook when you can, and let me know:\n\n"
                        "**What’s your writing goal this week?**\n"
                        "Reply to this message, and I shall transcribe it into #weekly-writing-goals in my most elegant pawwriting.\n\n"
                        "—Inkwell, HRH, Meow-th of His Name"
                    )
                    user_goals[member.id] = True
                except:
                    continue

# INACTIVITY REMINDER
@tasks.loop(hours=24)
async def inactivity_reminder():
    now = datetime.utcnow()
    for uid, projects in user_projects.items():
        inactive = [title for _, title, last, _, _, _ in projects if now - last > timedelta(days=14)]
        if inactive:
            try:
                user = await bot.fetch_user(uid)
                await user.send(
                    "📆 *rustles through old pages* Ahem. I couldn’t help but notice your project log has been gathering a *touch* of dust...\n\n"
                    "**You haven’t updated the following in a while:**\n"
                    + "\n".join(f"• {p}" for p in inactive) +
                    "\n\nPop back in and give me something to file, would you? I do so love a progress update.\n\n"
                    "—Inkwell, HRH, Meow-th of His Name"
                )
            except:
                continue

# MANUAL PROJECT ADD
@bot.command(name="addproject")
async def add_project(ctx):
    member = ctx.author
    if member.bot:
        return

    def check(m):
        return m.author == member and isinstance(m.channel, discord.DMChannel)

    try:
        await member.send("📦 Time to hatch a new project? I’m listening.\nReply with: `Title, Genre, Current Word Count, Goal Word Count, Stage`")
        details = await bot.wait_for("message", check=check, timeout=300)
        parts = [p.strip() for p in details.content.split(",")]

        if len(parts) < 5:
            await member.send("❌ I need all five details. Try again with the format: `Title, Genre, Current WC, Goal WC, Stage`.")
            return

        try:
            title, genre, current, goal, stage = parts
            current_wc = int(current)
            goal_wc = int(goal)
        except ValueError:
            await member.send("❌ Word counts must be numbers. Try again.")
            return

        guild = ctx.guild
        category_id = user_categories.get(member.id)
        if not category_id:
            await member.send("Hmm. I couldn’t find your writing den. Try rejoining the server to start fresh.")
            return

        category = discord.utils.get(guild.categories, id=category_id)
        if not category:
            await member.send("Your category has vanished like an idea at 3am. I can’t add a project without it.")
            return

        channel = await guild.create_text_channel(name=title.lower().replace(" ", "-"), category=category)
        tracker = await channel.send(build_tracker(title, genre, stage, current_wc, goal_wc))
        await tracker.pin()
        user_projects[member.id].append((channel.id, title, datetime.utcnow(), goal_wc, tracker.id, stage))
        user_project_metadata[channel.id] = (member.id, title, genre, goal_wc)
        await member.send(f"✅ Project '{title}' has been added to your writing den!")

    except Exception as e:
        await member.send("❌ Something went wrong while setting up your project.")
        print(f"❌ Error in addproject command: {e}")

# TRACKER AUTO-UPDATE
@bot.event
async def on_message(message):
    if message.author.bot or not isinstance(message.channel, discord.TextChannel):
        return

    channel_id = message.channel.id
    if channel_id not in user_project_metadata:
        await bot.process_commands(message)
        return

    user_id, title, genre, goal_wc = user_project_metadata[channel_id]
    for i, (chan_id, _, _, _, tracker_id, stage) in enumerate(user_projects[user_id]):
        if chan_id != channel_id:
            continue

        wc_match = re.search(r"Current Word Count:\s*(\d+)", message.content, re.IGNORECASE)
        stage_match = re.search(r"Stage:\s*(.+)", message.content, re.IGNORECASE)
        if not wc_match and not stage_match:
            break

        new_wc = int(wc_match.group(1)) if wc_match else goal_wc
        new_stage = stage_match.group(1).strip() if stage_match else stage

        try:
            tracker_message = await message.channel.fetch_message(tracker_id)
            user_projects[user_id][i] = (chan_id, title, datetime.utcnow(), goal_wc, tracker_id, new_stage)
            await tracker_message.edit(content=build_tracker(title, genre, new_stage, new_wc, goal_wc))
        except Exception as e:
            print(f"❌ Tracker update failed: {e}")
        break

    await bot.process_commands(message)

# RUN BOT
bot.run(os.getenv("DISCORD_TOKEN"))
