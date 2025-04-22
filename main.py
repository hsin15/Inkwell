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

# CONFIGURE ADMIN ROLE NAME
ADMIN_ROLE_NAME = "Admin"

# Dictionary to track user project channels and last update times
# Structure: {user_id: [(channel_id, project_name, last_update, goal_wc, tracker_msg_id, current_stage)]}
user_projects = {}
user_categories = {}
user_goals = {}
user_project_metadata = {}  # {channel_id: (user_id, project_name, genre, goal_word_count)}

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

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    weekly_goal_prompt.start()
    inactivity_reminder.start()

@bot.event
async def on_member_join(member):
    print(f"📅 on_member_join triggered for {member.name} at {datetime.utcnow().isoformat()}")
    guild = member.guild

    def check(m):
        return m.author == member and isinstance(m.channel, discord.DMChannel)

    try:
        await member.send("\ud83d\udc3e Well, well. Another writer in need of a cozy corner...")

        await member.send("What’s your name?")
        name_msg = await bot.wait_for("message", check=check, timeout=300)
        user_name = name_msg.content.strip()
        
        word_to_num = {
                "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
            }
        while True:
            await member.send("How many projects are you juggling?\n(Enter a number or a word between 1 and 10, e.g. `3` or `three`)")
            num_projects_msg = await bot.wait_for("message", check=check, timeout=300)
            num_text = num_projects_msg.content.strip().lower()

            try:
                num_projects = int(num_text) if num_text.isdigit() else word_to_num[num_text]
                break  # valid input received
            except (KeyError, ValueError):
                await member.send("❌ That wasn’t a valid number. Try again with something like `2` or `two`.")

        admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True
            ),
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True
            )

        category_name = f"{user_name}'s Projects"
        category = await guild.create_category(name=category_name, overwrites=overwrites)

        user_projects[member.id] = []
        user_categories[member.id] = category.id

        for i in range(1, num_projects + 1):
            while True:
                await member.send(f"Project #{i}? Reply with: `Title, Genre, Current Word Count, Goal Word Count, Stage`")
                details = await bot.wait_for("message", check=check, timeout=300)
                parts = [p.strip() for p in details.content.split(",")]

                if len(parts) < 5:
                    await member.send("❌ I need all five details. Try again.")
                    continue

                try:
                    project_name, genre, word_count, goal_word_count, stage = parts
                    current_wc = int(word_count)
                    goal_wc = int(goal_word_count)
                except ValueError:
                    await member.send("❌ Word counts must be numbers. Try again.")
                    continue

                channel_name = project_name.lower().replace(" ", "-")
                project_channel = await guild.create_text_channel(name=channel_name, category=category)

                tracker_message = await project_channel.send(
                    build_tracker(project_name, genre, stage, current_wc, goal_wc)
                )
                await tracker_message.pin()

                user_projects[member.id].append((project_channel.id, project_name, datetime.utcnow(), goal_wc, tracker_message.id, stage))
                user_project_metadata[project_channel.id] = (member.id, project_name, genre, goal_wc)
                break

        await member.send("All done! Your writing den is ready.")

    except Exception as e:
        print(f"❌ Error collecting info: {e}")
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
                except Exception as e:
                    print(f"❌ Couldn't DM {member.name}: {e}")

@tasks.loop(hours=24)
async def inactivity_reminder():
    now = datetime.utcnow()
    for member_id, projects in user_projects.items():
        inactive_projects = [name for _, name, last, _, _, _ in projects if now - last > timedelta(days=14)]
        if inactive_projects:
            user = await bot.fetch_user(member_id)
            if user:
                await user.send(
                    "📆 *rustles through old pages* Ahem. I couldn’t help but notice your project log has been gathering a *touch* of dust...\n\n"
                    "**You haven’t updated the following in a while:**\n"
                    + "\n".join(f"• {p}" for p in inactive_projects) +
                    "\n\nPop back in and give me something to file, would you? I do so love a progress update.\n\n"
                    "—Inkwell, HRH, Meow-th of His Name"
                )
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
            project_name, genre, word_count, goal_word_count, stage = parts
            current_wc = int(word_count)
            goal_wc = int(goal_word_count)
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

        channel_name = project_name.lower().replace(" ", "-")
        project_channel = await guild.create_text_channel(name=channel_name, category=category)

        tracker_message = await project_channel.send(
            build_tracker(project_name, genre, stage, current_wc, goal_wc)
        )
        await tracker_message.pin()

        user_projects[member.id].append((project_channel.id, project_name, datetime.utcnow(), goal_wc, tracker_message.id, stage))
        user_project_metadata[project_channel.id] = (member.id, project_name, genre, goal_wc)

        await member.send(f"✅ Project '{project_name}' has been added to your writing den!")

    except Exception as e:
        await member.send("❌ Something went wrong while setting up your project.")
        print(f"❌ Error in addproject command: {e}")

@bot.event
async def on_message(message):
    if message.author.bot or not isinstance(message.channel, discord.TextChannel):
        return

    channel_id = message.channel.id
    if channel_id not in user_project_metadata:
        return

    user_id, project_name, genre, goal_wc = user_project_metadata[channel_id]
    project_data_list = user_projects.get(user_id, [])

    for i, (chan_id, proj_name, last_update, goal, tracker_msg_id, stage) in enumerate(project_data_list):
        if chan_id != channel_id:
            continue

        wc_match = re.search(r"Current Word Count:\s*(\d+)", message.content, re.IGNORECASE)
        stage_match = re.search(r"Stage:\s*(.+)", message.content, re.IGNORECASE)

        if not wc_match and not stage_match:
            break

        new_wc = int(wc_match.group(1)) if wc_match else goal
        new_stage = stage_match.group(1).strip() if stage_match else stage

        try:
            tracker_message = await message.channel.fetch_message(tracker_msg_id)
            user_projects[user_id][i] = (
                chan_id, proj_name, datetime.utcnow(), new_wc, tracker_msg_id, new_stage
            )
            updated_content = build_tracker(proj_name, genre, new_stage, new_wc, goal_wc)
            await tracker_message.edit(content=updated_content)
            print(f"✅ Updated tracker for '{proj_name}' in #{message.channel.name}")
        except Exception as e:
            print(f"❌ Failed to update tracker in #{message.channel.name}: {e}")
        break

    await bot.process_commands(message)

bot.run(os.getenv("DISCORD_TOKEN"))