import discord
from discord.ext import commands, tasks
import os
import re
from datetime import datetime, timedelta
import pytz

intents = discord.Intents.default()
intents.members = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

ADMIN_ROLE_NAME = "Admin"

user_projects = {}
user_categories = {}
user_goals = {}
user_project_metadata = {}

def build_tracker(name, genre, stage, current_wc, goal_wc):
    try:
        percent = round(current_wc / goal_wc * 100)
        bar = "█" * (percent // 10) + "░" * (10 - percent // 10)
    except (ValueError, ZeroDivisionError):
        percent, bar, current_wc, goal_wc = 0, "░" * 10, 0, 1

    return (
        f"\U0001f4cc **Progress Tracker for _{name}_**\n"
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
    guild = member.guild
    def check(m):
        return m.author == member and isinstance(m.channel, discord.DMChannel)

    try:
        await member.send("🐾 Well, well. Another writer in need of a cozy corner...")
        await member.send("What’s your name?")
        name_msg = await bot.wait_for("message", check=check, timeout=300)
        user_name = name_msg.content.strip()

        word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                       "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

        while True:
            await member.send("How many projects are you juggling?\n(Enter a number or a word between 1 and 10, e.g. `3` or `three`)")
            msg = await bot.wait_for("message", check=check, timeout=300)
            num = msg.content.strip().lower()
            try:
                project_count = int(num) if num.isdigit() else word_to_num[num]
                break
            except (ValueError, KeyError):
                await member.send("❌ That wasn’t a valid number. Try again with something like `2` or `two`.")

        admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            member: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)

        category = await guild.create_category(f"{user_name}'s Projects", overwrites=overwrites)
        user_categories[member.id] = category.id
        user_projects[member.id] = []

        for i in range(1, project_count + 1):
            while True:
                await member.send(f"📘 Project #{i}? Reply with: `Title, Genre, Current Word Count, Goal Word Count, Stage`")
                response = await bot.wait_for("message", check=check, timeout=300)
                parts = [p.strip() for p in response.content.split(",")]
                if len(parts) < 5:
                    await member.send("❌ I need all five details. Try again.")
                    continue
                try:
                    name, genre, wc, gwc, stage = parts
                    current_wc = int(wc)
                    goal_wc = int(gwc)
                    break
                except ValueError:
                    await member.send("❌ Word counts must be numbers. Try again.")

            ch_name = name.lower().replace(" ", "-")
            ch = await guild.create_text_channel(name=ch_name, category=category)
            tracker = await ch.send(build_tracker(name, genre, stage, current_wc, goal_wc))
            await tracker.pin()

            user_projects[member.id].append((ch.id, name, datetime.utcnow(), goal_wc, tracker.id, stage))
            user_project_metadata[ch.id] = (member.id, name, genre, goal_wc)

        await member.send("✅ All done! Your writing den is ready.")

    except Exception as e:
        print(f"❌ Error onboarding {member.name}: {e}")

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
    for uid, projects in user_projects.items():
        stale = [name for _, name, last, _, _, _ in projects if now - last > timedelta(days=14)]
        if stale:
            user = await bot.fetch_user(uid)
            if user:
                await user.send(
                    "📆 *rustles through old pages* Ahem. I couldn’t help but notice your project log has been gathering a *touch* of dust...\n\n"
                    "**You haven’t updated the following in a while:**\n"
                    + "\n".join(f"• {name}" for name in stale) +
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
            name, genre, wc, gwc, stage = parts
            current_wc = int(wc)
            goal_wc = int(gwc)
        except ValueError:
            await member.send("❌ Word counts must be numbers. Try again.")
            return

        guild = ctx.guild
        cat_id = user_categories.get(member.id)
        if not cat_id:
            await member.send("Hmm. I couldn’t find your writing den. Try rejoining the server to start fresh.")
            return

        category = discord.utils.get(guild.categories, id=cat_id)
        if not category:
            await member.send("Your category has vanished like an idea at 3am. I can’t add a project without it.")
            return

        ch_name = name.lower().replace(" ", "-")
        ch = await guild.create_text_channel(name=ch_name, category=category)
        tracker = await ch.send(build_tracker(name, genre, stage, current_wc, goal_wc))
        await tracker.pin()

        user_projects[member.id].append((ch.id, name, datetime.utcnow(), goal_wc, tracker.id, stage))
        user_project_metadata[ch.id] = (member.id, name, genre, goal_wc)

        await member.send(f"✅ Project '{name}' has been added to your writing den!")

    except Exception as e:
        await member.send("❌ Something went wrong while setting up your project.")
        print(f"❌ Error in addproject command: {e}")

@bot.event
async def on_message(message):
    if message.author.bot or not isinstance(message.channel, discord.TextChannel):
        return

    chan_id = message.channel.id
    if chan_id not in user_project_metadata:
        return

    uid, name, genre, goal_wc = user_project_metadata[chan_id]
    data = user_projects.get(uid, [])

    for i, (cid, pname, last, goal, tracker_id, stage) in enumerate(data):
        if cid != chan_id:
            continue

        wc = re.search(r"Current Word Count:\s*(\d+)", message.content, re.IGNORECASE)
        st = re.search(r"Stage:\s*(.+)", message.content, re.IGNORECASE)

        if not wc and not st:
            break

        new_wc = int(wc.group(1)) if wc else goal
        new_stage = st.group(1).strip() if st else stage

        try:
            tracker = await message.channel.fetch_message(tracker_id)
            user_projects[uid][i] = (cid, pname, datetime.utcnow(), new_wc, tracker_id, new_stage)
            updated = build_tracker(pname, genre, new_stage, new_wc, goal_wc)
            await tracker.edit(content=updated)
            print(f"✅ Updated tracker for '{pname}' in #{message.channel.name}")
        except Exception as e:
            print(f"❌ Failed to update tracker in #{message.channel.name}: {e}")
        break

    await bot.process_commands(message)

bot.run(os.getenv("DISCORD_TOKEN"))
