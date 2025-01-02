import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)
from datetime import datetime, timedelta
import secrets
import random

# Enable logging
logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


# Data Models
class User:
    def __init__(self, username: str, is_admin: bool = False):
        self.username = username


class Group:
    def __init__(self, id: str, admin: User):
        self.id = id
        self.admin: User = admin
        self.users: list[User] = []
        self.settings = Settings()


class Settings:
    def __init__(self):
        self.deadline = datetime.now() + timedelta(days=1)
        self.accept_odd = False
        self.include_admin = False


GROUP_PREFIX = "group_"
GROUP_PENDING_PREFIX = "pending_"


# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Bot started")
    assert update.message

    await update.message.reply_text(
        "Welcome to the Secret Santa Bot! Use /help for available commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Help command called")
    assert update.message

    help_text = (
        "Available Commands:\n"
        "/create_group - Create a new Secret Santa group\n"
        "/join_group <group_id> - Request to join a group\n"
        "/leave_group - Leave your current group\n"
        "/settings - View group settings\n"
        "/start_matching - Start the Secret Santa matching process (Admin Only)"
    )
    await update.message.reply_text(help_text)


async def create_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Create group command called")
    assert update.effective_user and update.effective_user.username
    assert update.message
    groups: dict[str, Group] = context.bot_data

    admin = User(username=update.effective_user.username)
    group_id = f"{GROUP_PREFIX}{secrets.token_hex(4)}"
    group = Group(id=group_id, admin=admin)
    groups[group_id] = group
    logging.info(f"Created group {group_id} by {update.effective_user.username}")

    await update.message.reply_text(
        f"Group created successfully! Your group ID is: {group_id}"
    )


async def join_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Join group command called")
    assert update.effective_user and update.effective_user.username
    assert update.message
    assert context.args is not None
    groups: dict[str, Group] = context.bot_data

    if len(context.args) < 1:
        logging.info("Join group has no arguments")
        await update.message.reply_text("Usage: /join_group <group_id>")
        return

    group_id = context.args[0]
    logging.info(f"Join group has group id {group_id}")
    if get_group_id(group_id) not in groups:
        logging.info(f"Join group has invalid group id {group_id}")
        await update.message.reply_text("Invalid group ID.")
        return

    group = groups[get_group_id(group_id)]
    group_pending = groups[get_pending_group_id(group_id)]
    user = User(username=update.effective_user.username)

    if user in group_pending.users:
        logging.info(f"Join group failed becuase user has already requested to join")
        await update.message.reply_text(
            "You have already requested to join this group. and your request is still pending."
        )
        return

    if user in group.users:
        logging.info(f"Join group failed because user has already joined")
        await update.message.reply_text("You are already in the group.")
        return

    logging.info(f"Join group succesfully added to a pending group")
    group_pending.users.append(user)

    # TODO: send message to admin to accept the user

    await update.message.reply_text(
        f"You have requested to join group {group_id}. Please wait for admin approval."
    )


async def leave_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Leave group command called")
    assert update.effective_user and update.effective_user.username
    assert update.message
    groups: dict[str, Group] = context.bot_data

    username = update.effective_user.username

    for group in groups.values():
        for user in group.users:
            if user.username == username:
                # also remove from request

                # TODO: admin cannot leave group

                logging.info(
                    f"Leave group successful with user {username} leaving group {group.id}"
                )
                group.users.remove(user)
                await update.message.reply_text("You have left the group.")
                return

    logging.info(f"Leave group failed because user has no group")
    await update.message.reply_text("You are not part of any group.")


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"settings command called")
    assert update.effective_user and update.effective_user.username
    assert update.message
    groups: dict[str, Group] = context.bot_data

    username = update.effective_user.username
    for group in groups.values():
        for user in group.users:
            if user.username == username:  # add this logic in a permission decorator
                settings = group.settings
                settings_text = (
                    f"Settings:\n"
                    f"Deadline: {settings.deadline}\n"
                    f"Accept Odd Participants: {settings.accept_odd}\n"
                    f"Include Admin in Matching: {settings.include_admin}"
                )

                keyboard = [
                    [
                        InlineKeyboardButton(
                            "Change Deadline", callback_data="change_deadline"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "Toggle Accept Odd Participants",
                            callback_data="toggle_accept_odd",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "Toggle Include Admin", callback_data="toggle_include_admin"
                        )
                    ],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                is_admin = group.admin.username == username

                logging.info(
                    f"settings command successfull"
                    + (" admin buttons" if is_admin else "")
                )
                await update.message.reply_text(
                    settings_text, reply_markup=(reply_markup if is_admin else None)
                )
                return

    await update.message.reply_text("You are not part of any group.")


async def handle_settings_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.effective_user and update.effective_user.username
    assert update.callback_query

    groups: dict[str, Group] = context.bot_data
    query = update.callback_query

    await query.answer()

    username = update.effective_user.username

    for group in groups.values():
        if group.admin.username == username:
            if query.data == "change_deadline":
                group.settings.deadline += timedelta(days=1)
                await query.edit_message_text(
                    f"Deadline updated to: {group.settings.deadline}"
                )

            elif query.data == "toggle_accept_odd":
                group.settings.accept_odd = not group.settings.accept_odd
                await query.edit_message_text(
                    f"Accept Odd Participants set to: {group.settings.accept_odd}"
                )

            elif query.data == "toggle_include_admin":
                group.settings.include_admin = not group.settings.include_admin
                await query.edit_message_text(
                    f"Include Admin in Matching set to: {group.settings.include_admin}"
                )

            return

    await query.edit_message_text("You do not have permission to change settings.")


async def start_matching(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.effective_user and update.effective_user.username
    assert update.message
    groups: dict[str, Group] = context.bot_data

    username = update.effective_user.username

    # Find the group of the admin
    admin_group = None
    for group in groups.values():
        for user in group.users:
            is_admin = group.admin.username == username
            if user.username == username and is_admin:
                admin_group = group
                break

    if not admin_group:
        await update.message.reply_text(
            "You are not an admin or not part of any group."
        )
        return

    group = admin_group
    users = group.users.copy()

    if not group.settings.include_admin:
        users = [user for user in users if not user.is_admin]

    if len(users) < 2:
        await update.message.reply_text("Not enough participants for matching.")
        return

    random.shuffle(users)
    matches = {
        users[i].username: users[(i + 1) % len(users)].username
        for i in range(len(users))
    }

    for user in group.users:
        if user.username in matches:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"Hi {user.username}, your Secret Santa match is {matches[user.username]}!",
            )


# Helper functions
def get_group_id(group_id: str):
    return GROUP_PREFIX + group_id


def get_pending_group_id(group_id: str):
    return GROUP_PENDING_PREFIX + group_id


# Main Function
def main():

    persistence = PicklePersistence(filepath="group-storage.pickle")

    application = (
        Application.builder().token("YOUR_BOT_TOKEN").persistence(persistence).build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("create_group", create_group))
    application.add_handler(CommandHandler("join_group", join_group))
    application.add_handler(CommandHandler("leave_group", leave_group))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("start_matching", start_matching))

    application.run_polling()


if __name__ == "__main__":
    main()
