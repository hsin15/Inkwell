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
user_project_metadata = {}  # {channel_id: (user_id, project_name, goal_word_count)}

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
            print(f"📥 on_member_join triggered for {member.name} at {datetime.utcnow().isoformat()}")
            guild = member.guild
            print(f"🕐 New member joined: {member.name}")

            def check(m):
                return m.author == member and isinstance(m.channel, discord.DMChannel)

            try:
                await member.send("🐾 Well, well. Another writer in need of a cozy corner. Let’s get your writing space purring along.\n\n")

                await member.send("And who, may I ask, shall I scratch into the ledger? What’s your name?")
                name_msg = await bot.wait_for("message", check=check, timeout=300)
                user_name = name_msg.content.strip()

                await member.send("How many projects are you currently juggling? Don’t worry, I won’t knock them off the desk… probably.")
                num_projects_msg = await bot.wait_for("message", check=check, timeout=300)
                num_text = num_projects_msg.content.strip().lower()
                word_to_num = {
                    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
                }

                try:
                    num_projects = int(num_text) if num_text.isdigit() else word_to_num[num_text]
                except (KeyError, ValueError):
                    await member.send("❌ Please enter a digit or a word (e.g., '2' or 'two'). Setup cancelled.")
                    return

                admin_role = discord.utils.get(guild.roles, name=ADMIN_ROLE_NAME)
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    member: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
                }
                if admin_role:
                    overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, manage_channels=True)

                category_name = f"{user_name}'s Projects"
                category = await guild.create_category(name=category_name, overwrites=overwrites)

                user_projects[member.id] = []
                user_categories[member.id] = category.id

                for i in range(1, num_projects + 1):
                    while True:
                        await member.send(
                            f"📚 Project #{i}, then. Curl up and reply with:\n"
                            "`Title, Genre, Current Word Count, Goal Word Count, Stage`\n\n"
                            "(Example: `The Cat Who Wrote a Novel, Fantasy, 15000, 50000, First Draft`)\n\n"
                            "No pressure—just five little details. Your stage can be whatever you want (Editing, Awaiting Feedback, Revising Act II, lining the bottom of a kitty litter, etc). I’ll be watching from a warm spot on your manuscript."
                        )
                        details = await bot.wait_for("message", check=check, timeout=300)
                        parts = [p.strip() for p in details.content.split(",")]

                        if len(parts) < 5:
                            await member.send("❌ I need all five details, my dear. Please try again.")
                            continue

                        try:
                            project_name, genre, word_count, goal_word_count, stage = parts
                            current_wc = int(word_count)
                            goal_wc = int(goal_word_count)
                        except ValueError:
                            await member.send("❌ Please ensure the Word Count and Goal Word Count are numbers. Try again.")
                            continue

                        channel_name = project_name.lower().replace(" ", "-")
                        project_channel = await guild.create_text_channel(name=channel_name, category=category)

                        tracker_message = await project_channel.send(
                            build_tracker(project_name, genre, stage, current_wc, goal_wc)
                        )
                        await tracker_message.pin()

                        user_projects[member.id].append((project_channel.id, project_name, datetime.utcnow(), goal_wc, tracker_message.id, stage))
                        user_project_metadata[project_channel.id] = (member.id, project_name, goal_wc)

                        break  # Only move on when valid input has been processed

                await member.send("✅ All done! Your project nest is ready. Go give it a stretch and a scratch—er, I mean, a write.\n\n—yours sincerely, \n\n Inkwell, HRH, Meow-th of His Name")

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
@bot.event
async def on_voice_state_update(member, before, after):
    # Check if they just joined a voice channel (and it's the one we're watching)
    if before.channel is None and after.channel and after.channel.name == "writing-live":
        general_chat = discord.utils.get(member.guild.text_channels, name="general-chat")
        if general_chat:
            await general_chat.send(
                f"📣 Ahem.\n\n"
                f"🐾 {member.display_name} has just slinked into the **#writing-live** voice den.\n"
                f"They’re likely scratching away at a story or plotting the fall of an empire.\n\n"
                f"If you’d like to join them for a writing session, the quill is warm and the catnip tea is steeped.\n\n"
                f"—Inkwell, HRH, Meow-th of His Name"
            )
@bot.event
async def on_member_remove(member):
    # Delete the user's category and channels if they leave
    guild = member.guild
    category_id = user_categories.get(member.id)

    if category_id:
        category = discord.utils.get(guild.categories, id=category_id)
        if category:
            # Delete all channels in the category
            for channel in category.channels:
                try:
                    await channel.delete()
                except Exception as e:
                    print(f"❌ Failed to delete channel {channel.name}: {e}")
            try:
                await category.delete()
                print(f"🗑️ Deleted category for {member.name}")
            except Exception as e:
                print(f"❌ Failed to delete category {category.name}: {e}")

    # Clean up from tracking dictionaries
    user_projects.pop(member.id, None)
    user_categories.pop(member.id, None)
    user_goals.pop(member.id, None)

@bot.command()
async def test_weekly_prompt(ctx):
    admin_role = discord.utils.get(ctx.guild.roles, name=ADMIN_ROLE_NAME)
    if admin_role in ctx.author.roles:
        await ctx.author.send(
            "🐾 Ahem! It’s that time again, dear scribbler.\n\n"
            "How’s your project coming along? Don’t forget to update your logbook so we can all marvel at your progress (or at least admire your ambition).\n\n"
            "**What’s your writing goal this week?**\n"
            "Just reply to this message and I’ll tuck it into the #weekly-writing-goals channel where it can stretch its legs.\n\n"
            "—Inkwell, HRH, Meow-th of His Name"
        )
        user_goals[ctx.author.id] = True
        await ctx.send("✅ Weekly goal DM sent.")

@bot.command()
async def new_project(ctx):
    member = ctx.author

    if member.id not in user_categories:
        await ctx.send("❌ You don’t have a writing category set up yet. Try `!setup_me` first.")
        return

    def check(m):
        return m.author == member and isinstance(m.channel, discord.DMChannel)

    try:
        await member.send("Let’s set up your new writing project! Please reply with:\n`Title, Genre, Current Word Count, Goal Word Count, Stage`")
        details = await bot.wait_for("message", check=check, timeout=300)
        parts = [p.strip() for p in details.content.split(",")]

        if len(parts) < 5:
            await member.send("❌ I need all five details. Please try again by retyping `!new_project`.")
            return

        project_name, genre, word_count, goal_word_count, stage = parts
        channel_name = project_name.lower().replace(" ", "-")

        guild = ctx.guild
        category_id = user_categories.get(member.id)
        category = guild.get_channel(category_id)
        if not category:
            await member.send("❌ Your category no longer exists. Please contact an admin.")
            return

        project_channel = await guild.create_text_channel(name=channel_name, category=category)

        try:
            current_wc = int(word_count)
            goal_wc = int(goal_word_count)
        except ValueError:
            current_wc, goal_wc = 0, 1

        tracker_message = await project_channel.send(
            build_tracker(project_name, genre, stage, current_wc, goal_wc)
        )
        await tracker_message.pin()

        user_projects.setdefault(member.id, []).append(
            (project_channel.id, project_name, datetime.utcnow(), goal_wc, tracker_message.id, stage)
        )
        user_project_metadata[project_channel.id] = (member.id, project_name, goal_wc)

        await member.send(f"✅ Your new project channel **{project_name}** has been created!")

    except Exception as e:
        print(f"❌ Error during new project setup: {e}")
        await member.send("❌ Something went wrong. Please try again or contact an admin.")

@bot.command()
async def setup_me(ctx):
    admin_role = discord.utils.get(ctx.guild.roles, name=ADMIN_ROLE_NAME)
    if admin_role in ctx.author.roles:
        if ctx.author.id in user_categories:
            await ctx.send("✅ You're already set up!")
        else:
            await on_member_join(ctx.author)
    else:
        await ctx.send("❌ Only admins can run this command.")

@bot.command()
async def test_inactivity(ctx):
    admin_role = discord.utils.get(ctx.guild.roles, name=ADMIN_ROLE_NAME)
    if admin_role in ctx.author.roles:
        await inactivity_reminder()
        await ctx.send("✅ Inactivity check complete.")
        
@bot.event
async def on_message(message):
    if message.author.bot or not isinstance(message.channel, discord.TextChannel):
        return

    channel_id = message.channel.id

    # Only proceed if this channel is a tracked project channel
    if channel_id not in user_project_metadata:
        return

    user_id, project_name, goal_wc = user_project_metadata[channel_id]
    project_data_list = user_projects.get(user_id, [])

    for i, (chan_id, proj_name, last_update, goal, tracker_msg_id, stage) in enumerate(project_data_list):
        if chan_id != channel_id:
            continue

        # Look for both current word count and stage updates
        wc_match = re.search(r"Current Word Count:\s*(\d+)", message.content, re.IGNORECASE)
        stage_match = re.search(r"Stage:\s*(.+)", message.content, re.IGNORECASE)

        if not wc_match and not stage_match:
            break  # No updates to process

        # Update stored data
        new_wc = int(wc_match.group(1)) if wc_match else None
        new_stage = stage_match.group(1).strip() if stage_match else stage

        try:
            tracker_message = await message.channel.fetch_message(tracker_msg_id)
            updated_wc = new_wc if new_wc is not None else goal
            user_projects[user_id][i] = (
                chan_id, proj_name, datetime.utcnow(), updated_wc, tracker_msg_id, new_stage
            )

            updated_content = build_tracker(proj_name, "Unknown", new_stage, updated_wc, goal_wc)
            await tracker_message.edit(content=updated_content)
            print(f"✅ Updated tracker for '{proj_name}' in #{message.channel.name}")
        except Exception as e:
            print(f"❌ Failed to update tracker in #{message.channel.name}: {e}")
        break

    await bot.process_commands(message)  # Allow commands to keep working

bot.run(os.getenv("DISCORD_TOKEN"))
