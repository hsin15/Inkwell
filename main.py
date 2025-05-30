import discord
from discord.ext import commands, tasks
import os
from datetime import datetime, timedelta
import pytz
import re
import json

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
    load_data()   
    start_tasks()

# NEW MEMBER INTAKE
# Global set to track onboarding users
onboarding_users = set()

@bot.event
async def on_member_join(member):
    guild = member.guild

    # Prevent simultaneous onboarding (but allow rejoining users later)
    if member.id in onboarding_users:
        print(f"⏳ Onboarding already in progress for {member.name} ({member.id}) — skipping.")
        return
    onboarding_users.add(member.id)

    def check(m):
        return m.author == member and isinstance(m.channel, discord.DMChannel)

    try:
        # ✅ ACTUAL INTAKE BEGINS
        await member.send("🐾 Well, well. Another writer in need of a cozy corner...")
        await member.send("What’s your name?")
        name_msg = await bot.wait_for("message", check=check, timeout=300)
        user_name = name_msg.content.strip()

        word_to_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
        }

        while True:
            await member.send("How many projects are you juggling?\n(Enter a number or a word between 1 and 10, e.g. `3` or `three`)")
            try:
                response = await bot.wait_for("message", check=check, timeout=300)
                num_text = response.content.strip().lower()
                num_projects = int(num_text) if num_text.isdigit() else word_to_num[num_text]
                break
            except (KeyError, ValueError):
                await member.send("❌ That wasn’t a valid number. Try again with something like `2` or `two`.")

        # Set permissions
        admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)

        # Create category
        category = await guild.create_category(name=f"{user_name}'s Projects", overwrites=overwrites)
        user_categories[member.id] = category.id
        user_projects[member.id] = []  # Always reinitialise in case they're rejoining

        for i in range(1, num_projects + 1):
            while True:
                await member.send(
                    f"📘 Project #{i}? Reply with: `Title, Genre, Current Word Count, Goal Word Count, Stage`\n"
                    "Please separate each with a comma, and don’t use spaces in numbers."
                )
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
        print(f"❌ Error during onboarding for {member.name}: {e}")

    finally:
        onboarding_users.discard(member.id)

@bot.event
async def on_member_remove(member):
    guild = member.guild
    user_id = member.id

    # Remove their category and all project channels
    if user_id in user_categories:
        category_id = user_categories[user_id]
        category = discord.utils.get(guild.categories, id=category_id)

        if category:
            for channel in category.channels:
                try:
                    await channel.delete()
                    print(f"🗑️ Deleted channel: {channel.name}")
                except Exception as e:
                    print(f"❌ Failed to delete channel {channel.name}: {e}")
            try:
                await category.delete()
                print(f"🗑️ Deleted category: {category.name}")
            except Exception as e:
                print(f"❌ Failed to delete category {category.name}: {e}")

        # Clean up from memory
        del user_categories[user_id]
        del user_projects[user_id]

        # Remove from project metadata
        for cid in list(user_project_metadata):
            if user_project_metadata[cid][0] == user_id:
                del user_project_metadata[cid]

        print(f"✅ Cleaned up data for {member.name}")

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

DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        print("📂 No data.json found. Skipping load.")
        return
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            global user_projects, user_categories, user_project_metadata
            user_projects = {
                int(k): [
                    (item[0], item[1], datetime.fromisoformat(item[2]), item[3], item[4], item[5])
                    for item in v
                ] for k, v in data["user_projects"].items()
            }
            user_categories = {int(k): v for k, v in data["user_categories"].items()}
            user_project_metadata = {int(k): tuple(v) for k, v in data["user_project_metadata"].items()}
        print("✅ Successfully loaded project data from file.")
    except Exception as e:
        print(f"❌ Failed to load data: {e}")



@bot.command(name="saveprojects")
@commands.has_role("Admin")
async def save_projects(ctx):
    """Saves all project and category data based on real channel-to-user mapping."""

    global user_categories
    user_categories = {}

    try:
        # Infer each user's category by tracing their project channels
        for user_id, projects in user_projects.items():
            for chan_id, _, _, _, _, _ in projects:
                for guild in bot.guilds:
                    channel = discord.utils.get(guild.channels, id=chan_id)
                    if channel and channel.category:
                        user_categories[user_id] = channel.category.id
                        break  # Once we find one, stop checking for that user
                if user_id in user_categories:
                    break

        # Convert datetime objects to strings
        serializable_user_projects = {}
        for user_id, projects in user_projects.items():
            serializable_user_projects[user_id] = []
            for channel_id, title, last_update, goal_wc, tracker_id, stage in projects:
                serializable_user_projects[user_id].append((
                    channel_id,
                    title,
                    last_update.isoformat(),
                    goal_wc,
                    tracker_id,
                    stage
                ))

        data = {
            "user_projects": serializable_user_projects,
            "user_categories": user_categories,
            "user_project_metadata": user_project_metadata,
        }

        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)

        await ctx.send("✅ Successfully saved project data to file.")

        try:
            with open(DATA_FILE, "rb") as f:
                await ctx.author.send("📂 Here's the latest saved `data.json` file:", file=discord.File(f, "data.json"))
        except Exception as e:
            await ctx.send("❌ Saved, but failed to DM you the file.")
            print(f"❌ Failed to DM data.json: {e}")

    except Exception as e:
        await ctx.send(f"❌ Failed to save data: {e}")
        print(f"❌ Save error: {e}")


        
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

@bot.command(name="sendgoalprompt")
async def send_goal_prompt(ctx):
    """Manually triggers the weekly goal prompt DM for yourself."""
    member = ctx.author
    if member.bot:
        return

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
        await ctx.send("✅ I've sent you the goal prompt!")
    except Exception as e:
        await ctx.send("❌ Failed to send you the goal prompt.")
        print(f"❌ Error sending manual goal prompt: {e}")


@bot.command(name="adminsetupme")
@commands.has_role(ADMIN_ROLE_NAME)
async def admin_setup_me(ctx):
    member = ctx.author
    guild = ctx.guild

    # Skip if user already has a project setup
    if member.id in user_projects:
        await member.send("🗂 You already have a writing den set up.")
        return

    def check(m):
        return m.author == member and isinstance(m.channel, discord.DMChannel)

    try:
        await member.send("🐾 Well, well. Another writer in need of a cozy corner...")
        await member.send("What’s your name?")
        name_msg = await bot.wait_for("message", check=check, timeout=300)
        user_name = name_msg.content.strip()

        word_to_num = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
        }

        while True:
            await member.send("How many projects are you juggling?\n(Enter a number or a word between 1 and 10, e.g. `3` or `three`)")
            try:
                response = await bot.wait_for("message", check=check, timeout=300)
                num_text = response.content.strip().lower()
                num_projects = int(num_text) if num_text.isdigit() else word_to_num[num_text]
                break
            except (KeyError, ValueError):
                await member.send("❌ That wasn’t a valid number. Try again with something like `2` or `two`.")

        # Set permissions
        admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)

        # Create category
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
        await member.send("❌ Something went wrong while setting up your den.")
        print(f"❌ Error in adminsetupme: {e}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Handle writing goal DM replies
    if isinstance(message.channel, discord.DMChannel) and message.author.id in user_goals:
        for guild in bot.guilds:
            channel = discord.utils.get(guild.text_channels, name="weekly-writing-goals")
            if channel:
                now = datetime.now(pytz.timezone("Australia/Sydney")).strftime("%d %B %Y")
                await channel.send(
                f"📝 __**{message.author.display_name}'s Weekly Goal**__ ({now}):\n"
                f"> {message.content}"
                )
                break
        user_goals.pop(message.author.id, None)
        await bot.process_commands(message)
        return  # Stop here if it was a DM (don't try updating trackers)

    # Handle project tracker updates in text channels
    if isinstance(message.channel, discord.TextChannel):
        channel_id = message.channel.id
        if channel_id in user_project_metadata:
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
bot.run(os.getenv("YOUR_BOT_TOKEN"))
