import logging
from copy import deepcopy
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    PicklePersistence,
    filters,
)
from enum import Enum
from datetime import datetime, timedelta
import secrets
import random
import os
from dotenv import load_dotenv
import time

load_dotenv()

# Enable logging
logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)

BOT_USER_NAME = "t.me/gena_secret_santa_bot"
PERSISTENCE_FILE = os.environ.get("PERSISTENT_PICKLE_PATH", "")
GROUP_PREFIX = "group_"
GROUP_PENDING_PREFIX = "pending_"


class Group:
    def __init__(self, id: int, admin: User):
        self.id = id
        self.admin: User = admin
        self.settings = Settings()


class Settings:
    def __init__(self):
        self.deadline = datetime.now() + timedelta(days=1)
        self.accept_odd = False
        self.include_admin = False


class UserFiniteState(Enum):
    JoinedGroup = 0
    PendingGroup = 1
    NoGroup = 2


class GroupStateException(Exception):
    pass


class GroupState:
    def __init__(self) -> None:
        self.__groups: dict[int, Group] = {}
        self.__user_to_group: dict[int, tuple[User, int]] = {}
        self.__pending_requests: dict[int, tuple[User, list[int]]] = {}

    def get_group(self, group_id: int) -> Optional[Group]:
        """Get a group by its ID."""
        return self.__groups.get(group_id)

    def get_user_group(self, user_id: int) -> Optional[int]:
        """Get the group ID the user belongs to."""
        return self.__user_to_group.get(user_id, (None, None))[1]

    def add_group(self, group: Group) -> None:
        """Add a new group."""
        self.__groups[group.id] = group

    def add_pending_request(self, user: User, group_id: int) -> None:
        """
        Add a pending join request for a user.
        Raises:
            GroupStateException: If the group does not exist
            GroupStateException: If the user is already part of a group.
        """
        if group_id not in self.__groups:
            raise GroupStateException("Group does not exist.")
        if user.id in self.__user_to_group:
            raise GroupStateException("User is already part of a group.")

        self.__pending_requests.setdefault(user.id, (user, []))[1].append(group_id)

    def approve_pending_request(self, user: User, group_id: int) -> None:
        """
        Approve a user's pending request and add them to the group.
        Also removes the request from the pending list.
        """
        if group_id not in self.__groups:
            raise GroupStateException("Group does not exist.")
        if group_id not in self.__pending_requests.get(user.id, (None, []))[1]:
            raise GroupStateException(
                "No pending request found for this user and group."
            )

        # Add user to the group by updating the user-to-group mapping
        self.__user_to_group[user.id] = (user, group_id)

        # Remove the pending request
        self.__pending_requests.pop(user.id)

    def remove_user_from_group(self, user: User) -> None:
        """
        Remove a user from their current group.
        """
        group_id = self.__user_to_group.pop(user.id, None)
        if not group_id:
            raise GroupStateException("User is not part of any group.")

    def remove_user_from_pending_group(self, user: User) -> None:
        """
        Remove a user from their current pending group.
        """
        group_id = self.__pending_requests.pop(user.id, None)
        if not group_id:
            raise GroupStateException("User is not pending to join any group.")

    def get_pending_requests(self, group_id: int) -> list[User]:
        """Get all pending user for a group."""
        return [
            groups[0]
            for user_id, groups in self.__pending_requests.items()
            if group_id in groups[1]
        ]

    def get_pending_request_for_user(
        self, user_id: int
    ) -> Optional[tuple[User, list[int]]]:
        return self.__pending_requests.get(user_id)

    def is_user_in_group(self, user: User) -> bool:
        """Check if a user is part of any group."""
        return user.id in self.__user_to_group

    def is_user_pending(self, user: User) -> bool:
        return user.id in self.__pending_requests

    def is_user_in_group_or_pending(self, user: User) -> bool:
        return self.is_user_pending(user) or self.is_user_in_group(user)

    def is_user_admin(self, user: User) -> bool:
        for group in self.__groups.values():
            if group.admin.id == user.id:
                return True
        return False

    def get_all_groups(self) -> dict[int, Group]:
        """Get all groups."""
        return self.__groups


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Inputs:
        - normal start: should send welcome message
        - with args: should join other groups
        - with other state
    """
    logging.info("Bot started")

    assert update.message
    await update.message.reply_text(
        "Welcome to the Secret Santa Bot! Use /help for available commands."
    )

    args = context.args
    if args and len(args) > 0:
        logging.info(
            f"START: Bot started with arguments, user {update.effective_user.first_name if update.effective_user else 'Unkown'} joining group {args[0]}"
        )
        # execute the join_gorup command
        await join_group(update, context)


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

    group_state: GroupState = context.bot_data.setdefault("group_state", GroupState())
    group = Group(id=update.effective_user.id, admin=update.effective_user)

    # check if the user is in a group or has a group
    if group_state.is_user_in_group_or_pending(
        update.effective_user
    ) or group_state.is_user_admin(update.effective_user):
        logging.info(f"create group failed because user is in a group")
        await update.message.reply_text("you are already in a group.")
        return

    # create a user for the admin
    group_state.add_group(group)

    logging.info(
        f"CREATE_GROUP: successfull with user {update.effective_user.id} creating group {group.id}"
    )
    await update.message.reply_text(
        f"Group created successfully! Your group ID is: {group.id}\nShare this for others to join: {BOT_USER_NAME}?start={group.id}"
    )
    print("Group State: \n", context.bot_data["group_state"].get_all_groups())


async def join_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    State Before:
        - group_id(in args) should already exist in __groups
        - user should not be in any group, that is:
            - user should not be in __user_to_group
            - user should not be admin of any group in __group

    State After:
        - user is in __pending_requests for the group_id(in args)
        - user removed from any pending requests
    """
    logging.info("Join group command called")
    assert update.effective_user and update.effective_user.id
    assert update.message

    group_state: GroupState = context.bot_data.setdefault("group_state", GroupState())

    if context.args and len(context.args) < 1:
        logging.info("Join group has no arguments")
        await update.message.reply_text("Usage: /join_group <group_id>")
        return

    assert context.args
    group_id = context.args[0]

    if group_id not in group_state.get_all_groups():
        logging.info(f"Join group has invalid group id {group_id}")
        await update.message.reply_text("Invalid group ID.")
        return

    if group_state.is_user_in_group(update.effective_user) or group_state.is_user_admin(
        update.effective_user
    ):
        logging.info(f"Join group failed because user is in a group")
        await update.message.reply_text("You are already in a group.")
        return

    group_state.add_pending_request(update.effective_user, group_id)
    group_state.remove_user_from_group(update.effective_user)

    group = group_state.get_group(group_id)
    assert group is not None  # group should be guaranteed to exist here

    # TODO: send message to admin to accept the user
    await update.get_bot().send_message(
        chat_id=group.admin.id,
        text=f"User {update.effective_user.first_name} has requested to join group {group_id}.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Accept",
                        callback_data=f"accept@{update.effective_user.id}",
                    )
                ]
            ]
        ),
    )
    #
    await update.message.reply_text(
        f"You have requested to join group {group_id}. Please wait for admin approval."
    )


async def leave_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info(f"Leave group command called")
    assert update.effective_user and update.effective_user.id
    assert update.message
    groups: dict[str, Group] = context.bot_data

    for group in groups.values():
        for user in group.users:
            if user == update.effective_user:
                # also remove from request

                if user == group.admin:
                    logging.info(f"Leave group failed because user is admin")
                    await update.message.reply_text("You cannot leave your own group.")
                    return

                logging.info(
                    f"Leave group successful with user {user.id} leaving group {group.id}"
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
        if (
            group.admin == update.effective_user
            or update.effective_user not in group.users
        ):

            settings = group.settings
            settings_text = get_settings_message(settings)
            reply_markup = InlineKeyboardMarkup(get_settings_keyboard())

            is_admin = group.admin == update.effective_user

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
        is_admin = group.admin == update.effective_user
        if is_admin or user_id in group.users:
            user_list = "\n".join(
                [f"{i+1} - {user.first_name}" for i, user in enumerate(group.users)]
            )
            await update.message.reply_text(
                f"Users in the group:\n{group.admin.first_name}\n{user_list}"
            )
            return

    await update.message.reply_text("You are not part of any group.")


async def handle_settings_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    assert update.effective_user and update.effective_user.id
    assert update.callback_query

    group_state: GroupState = context.bot_data.setdefault("group_state", GroupState())
    query = update.callback_query
    await query.answer()

    if query.data and query.data.startswith("accept@"):
        """
        State Before:
            - user is in pending group
            - user is not in group

        State After:
            - user is in group
            - user is not in group
        """
        user_details = query.data.split("@")[1]
        user = group_state.get_pending_request_for_user(int(user_details))

        if user and group_state.is_user_in_group(user[0]):
            logging.info("Accept command failed because user is in a group")
            await update.callback_query.edit_message_text("You are already in a group.")
            await update.callback_query.edit_message_reply_markup(None)
            return
        #
        # if not user or user[1]:
        #     logging.info("Accept command failed because user is not in pending group")
        #     await update.callback_query.edit_message_text("Sorry the user has not requested to join any group")
        #     await update.callback_query.edit_message_reply_markup(None)

        if user and group_state.is_user_admin(user[0]):
            logging.info("Accept command failed because user is admin")
            await update.callback_query.edit_message_text("You are already in a group.")
            await update.callback_query.edit_message_reply_markup(None)
            return

        for group_id, group in group_state.get_all_groups().items():
            if group.admin == update.effective_user:  # get admin group
                # check if the user is pending in the same group
                if user and group.id not in user[1]:
                    logging.info(
                        "Accept command failed because user is not in pending group"
                    )
                    await update.callback_query.edit_message_text(
                        "Sorry the user has not requested to join any group"
                    )
                    await update.callback_query.edit_message_reply_markup(None)
                    return

                assert user is not None
                group_state.add_pending_request(user[0], group_id)
                await update.callback_query.edit_message_text("User accepted.")
                await update.callback_query.edit_message_reply_markup(None)
                return

        await update.callback_query.edit_message_text(
            "You are not qualified to add a user to a group."
        )
        await update.callback_query.edit_message_reply_markup(None)

    for group_id, group in group_state.get_all_groups().items():
        if group.admin == update.effective_user:
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
            if group.admin == update.effective_user:
                try:
                    assert update.message.text
                    deadline = int(update.message.text)
                except AssertionError as e:
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

    # Find the group of the admin
    admin_group = None
    for group in groups.values():
        for user in group.users:
            is_admin = group.admin == update.effective_user
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
            chat_id=giver.id,
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
        f"Deadline: {settings.deadline.strftime('%Y-%m-%d %H:%M')}\n"
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

    persistence = PicklePersistence(filepath=PERSISTENCE_FILE)

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
