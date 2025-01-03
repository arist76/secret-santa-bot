import logging
from copy import deepcopy
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    TypeHandler,
    filters,
)
from datetime import datetime, timedelta
import secrets
import random
import os
from dotenv import load_dotenv
import time

# Enable logging
logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)

BOT_USER_NAME = "t.me/gena_secret_santa_bot"


# Data Models
class User:
    def __init__(self, user_id: int, first_name: str):
        self.user_id = user_id
        self.first_name = first_name


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
    args = context.args

    print(f"start command called with args {args}")
    if args and len(args) > 0:
        print("executing start to join_gorup")
        # execute the join_gorup command
        await join_group(update, context)

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
        "/all_users - View all users in your group\n"
        "/settings - View group settings\n"
        "/start_matching - Start the Secret Santa matching process (Admin Only)"
    )
    await update.message.reply_text(help_text)


async def create_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Create group command called")
    assert update.effective_user and update.effective_user.id
    assert update.message
    groups: dict[str, Group] = context.bot_data

    admin = User(
        user_id=update.effective_user.id, first_name=update.effective_user.first_name
    )
    group_id_token = secrets.token_hex(4)
    group_id = f"{GROUP_PREFIX}{group_id_token}"
    pending_group_id = f"{GROUP_PENDING_PREFIX}{group_id_token}"
    group = Group(id=group_id, admin=admin)

    # check if the user is in a group or has a group
    for group in groups.values():
        if group.admin.user_id == update.effective_user.id:
            logging.info(f"create group failed because user is in a group")
            await update.message.reply_text("you are already in a group.")
            return

        for user in group.users:
            if user.user_id == update.effective_user.id:
                logging.info(f"create group failed because user is in a group")
                await update.message.reply_text("you are already in a group.")
                return

    groups[group_id] = group
    groups[pending_group_id] = deepcopy(group)
    logging.info(f"Created group {group_id} by {update.effective_user.id}")

    await update.message.reply_text(
        f"Group created successfully! Your group ID is: {group_id}\nShare this for others to join: {BOT_USER_NAME}?start={group_id}"
    )


async def join_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Join group command called")
    assert update.effective_user and update.effective_user.id
    assert update.message
    assert context.args is not None
    groups: dict[str, Group] = context.bot_data

    if len(context.args) < 1:
        logging.info("Join group has no arguments")
        await update.message.reply_text("Usage: /join_group <group_id>")
        return

    group_id = context.args[0]
    logging.info(f"Join group has group id {group_id}")
    if group_id not in groups:
        logging.info(f"Join group has invalid group id {group_id}")
        await update.message.reply_text("Invalid group ID.")
        return

    group_id_token = group_id.split("_")[1]
    group = groups[group_id]
    group_pending = groups[f"{GROUP_PENDING_PREFIX}{group_id_token}"]
    user = User(
        user_id=update.effective_user.id, first_name=update.effective_user.first_name
    )

    if group.admin.user_id == user.user_id:
        logging.info(f"Join group failed because user is admin")
        await update.message.reply_text("You cannot join your own group.")
        return

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
    await update.get_bot().send_message(
        chat_id=group.admin.user_id,
        text=f"User {user.user_id} has requested to join group {group_id}.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Accept",
                        callback_data=f"accept@{user.user_id}#{user.first_name}",
                    )
                ]
            ]
        ),
    )

    await update.message.reply_text(
        f"You have requested to join group {group_id}. Please wait for admin approval."
    )


async def leave_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Leave group command called")
    assert update.effective_user and update.effective_user.id
    assert update.message
    groups: dict[str, Group] = context.bot_data

    user_id = update.effective_user.id

    for group in groups.values():
        for user in group.users:
            if user.user_id == user_id:
                # also remove from request

                if user.user_id == group.admin.user_id:
                    logging.info(f"Leave group failed because user is admin")
                    await update.message.reply_text("You cannot leave your own group.")
                    return

                logging.info(
                    f"Leave group successful with user {user_id} leaving group {group.id}"
                )
                group.users.remove(user)
                await update.message.reply_text("You have left the group.")
                return

    logging.info(f"Leave group failed because user has no group")
    await update.message.reply_text("You are not part of any group.")


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"settings command called")
    assert update.effective_user and update.effective_user.id
    assert update.message
    groups: dict[str, Group] = context.bot_data

    user_id = update.effective_user.id
    for group in groups.values():
        if group.admin.user_id == user_id or user_id not in [
            user.user_id for user in group.users
        ]:

            settings = group.settings
            settings_text = get_settings_message(settings)
            reply_markup = InlineKeyboardMarkup(get_settings_keyboard())

            is_admin = group.admin.user_id == user_id

            logging.info(
                f"settings command successfull" + (" admin buttons" if is_admin else "")
            )
            await update.message.reply_text(
                settings_text, reply_markup=(reply_markup if is_admin else None)
            )
            return

    await update.message.reply_text("You are not part of any group.")


async def all_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.effective_user and update.effective_user.id
    assert update.message

    groups: dict[str, Group] = context.bot_data

    user_id = update.effective_user.id
    for group in groups.values():
        is_admin = group.admin.user_id == user_id
        if is_admin or user_id in [user.user_id for user in group.users]:
            user_list = "\n".join([str(user.first_name) for user in group.users])
            await update.message.reply_text(
                f"Users in the group:\n{group.admin.first_name}\n{user_list}"
            )
            return

    await update.message.reply_text("You are not part of any group.")


async def handle_settings_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.effective_user and update.effective_user.id
    assert update.callback_query

    groups: dict[str, Group] = context.bot_data
    query = update.callback_query

    await query.answer()

    user_id = update.effective_user.id

    if query.data and query.data.startswith("accept@"):
        print("accepting user!!!")
        user_details = query.data.split("@")[1].split("#")
        requesting_user_id = user_details[0]
        first_name = user_details[1]
        for group in groups.values():
            if group.admin.user_id == user_id and group.id.startswith(
                GROUP_PENDING_PREFIX
            ):
                print(
                    f"Removing user {requesting_user_id} from pending group {group.id}"
                )
                group.users = list(
                    filter(lambda x: x.user_id != requesting_user_id, group.users)
                )

            if group.admin.user_id == user_id and group.id.startswith(GROUP_PREFIX):
                print(f"Adding user {requesting_user_id} to group {group.id}")
                group.users.append(
                    User(user_id=int(requesting_user_id), first_name=first_name)
                )
                await query.edit_message_text("User accepted.")

            return

    for group in groups.values():
        if group.admin.user_id == user_id:
            if context.chat_data and query.data == "change_deadline":
                context.chat_data["deadline_change"] = True
                await query.edit_message_text(
                    "Please send the new deadline in seconds (as an integer):"
                )
                return

            elif query.data == "toggle_accept_odd":
                group.settings.accept_odd = not group.settings.accept_odd

            elif query.data == "toggle_include_admin":
                group.settings.include_admin = not group.settings.include_admin

            context.bot_data[group.id] = group

            reply_markup = InlineKeyboardMarkup(get_settings_keyboard())
            settings_message = get_settings_message(group.settings)
            await query.edit_message_text(settings_message, reply_markup=reply_markup)

            return

    await query.edit_message_text("You do not have permission to change settings.")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.effective_user and update.effective_user.id
    assert update.message

    groups: dict[str, Group] = context.bot_data
    user_id = update.effective_user.id

    if context.chat_data and context.chat_data.get("deadline_change"):

        for group in groups.values():
            if group.admin.user_id == user_id:
                try:
                    deadline = int(update.message.text)
                except:
                    await update.message.reply_text(
                        "Invalid deadline. Please send a number of seconds."
                    )

                    context.chat_data["deadline_change"] = False
                    return
                group.settings.deadline = datetime.now() + timedelta(seconds=deadline)
                reply_markup = InlineKeyboardMarkup(get_settings_keyboard())
                await update.message.reply_text(
                    get_settings_message(group.settings), reply_markup=reply_markup
                )
                return

            await update.message.reply_text(
                "You do not have permission to change deadline."
            )

    await update.message.reply_text("Hmmmmmmmmmmmmmmm.")


async def start_matching(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.effective_user and update.effective_user.id
    assert update.effective_chat
    assert update.message
    groups: dict[str, Group] = context.bot_data

    user_id = update.effective_user.id

    # Find the group of the admin
    admin_group = None
    for group in groups.values():
        for user in group.users:
            is_admin = group.admin.user_id == user_id
            if is_admin:
                admin_group = group
                break

    if not admin_group:
        await update.message.reply_text(
            "You are not an admin or not part of any group."
        )
        return

    group = admin_group
    users = group.users

    # if group.settings.include_admin:
    users.append(group.admin)

    if len(users) < 2:
        await update.message.reply_text("Not enough participants for matching.")
        return

    random.shuffle(users)
    pairings = secret_santa_pairing(users)

    for giver, receiver in pairings.items():
        await context.bot.send_message(
            chat_id=giver.user_id,
            text=f"You're Secret Santa match is {receiver.first_name}!\n",
        )


# Helper functions
# def get_group_id(group_id: str):
#     return GROUP_PREFIX + group_id
#
#
# def get_pending_group_id(group_id: str):
#     return GROUP_PENDING_PREFIX + group_id


def get_settings_message(settings: Settings):
    return (
        f"Settings:\n"
        f"Deadline: {settings.deadline.strftime("%Y-%m-%d %H:%M")}\n"
        f"Accept Odd Participants: {settings.accept_odd}\n"
        f"Include Admin in Matching: {settings.include_admin}"
    )


def get_settings_keyboard():
    return [
        [InlineKeyboardButton("Change Deadline", callback_data="change_deadline")],
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


def secret_santa_pairing(users: list[User]) -> dict[User, User]:
    """
    Assigns Secret Santa pairs from a list of users.

    Args:
        users (list): List of User objects.

    Returns:
        dict: A dictionary with users as keys and their assigned giftees as values.
    """
    pairs = loop(users, {})

    return pairs


TIMEOUT = 0.2

random.seed()


def loop(users: list[User], invalid_links):
    """Determine who gives to whom. `people`: a list of Person objects. `invalid_links`: a dict that defines who
    can't give to whom. Returns a dict. Raises SolvingError if it cannot solve."""
    start_time = time.time()
    random.shuffle(users)
    while not is_valid(dictize(users), invalid_links):
        random.shuffle(users)
        if start_time + TIMEOUT < time.time():
            raise ValueError("Could not solve.")
    return dictize(users)


def is_valid(people_dict, invalid_links):
    for gifter, giftee in people_dict.items():
        if giftee in invalid_links.get(gifter, ()):
            return False
    return True


def dictize(people_list):
    people = {}
    last_person = people_list[-1]
    for this_person in people_list:
        people[last_person] = this_person
        last_person = this_person
    return people


# Main Function
def main():
    load_dotenv()

    persistence = PicklePersistence(filepath="group-storage.pickle")

    application = (
        Application.builder()
        .token(os.environ["BOT_TOKEN"])
        .persistence(persistence)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("create_group", create_group))
    application.add_handler(CommandHandler("join_group", join_group))
    application.add_handler(CommandHandler("leave_group", leave_group))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("start_matching", start_matching))
    application.add_handler(CommandHandler("all_users", all_users))
    application.add_handler(CallbackQueryHandler(handle_settings_change))
    application.add_handler(MessageHandler(filters.TEXT, text_handler))

    application.run_polling()


if __name__ == "__main__":
    main()
