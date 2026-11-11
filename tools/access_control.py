"""Explicit Telegram membership for the TOVARNO workspace."""
import os


def is_allowed(user_id):
    configured = os.environ.get("ALLOWED_TELEGRAM_IDS") or os.environ.get("OWNER_TELEGRAM_IDS", "")
    members = {int(value.strip()) for value in configured.split(",") if value.strip().isdigit()}
    return type(user_id) is int and user_id in members
