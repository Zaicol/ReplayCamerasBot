from datetime import datetime, timedelta
from pyotp import TOTP, random_base32

from config.config import totp_dict


def generate_password():
    return random_base32()


def password_expiration_to_string(password_expiration_delta: timedelta) -> str:
    return f"{(password_expiration_delta.seconds % 3600) // 60} мин. {password_expiration_delta.seconds % 60} с."


def update_totp_dict(court) -> None:
    totp_dict[court.id] = TOTP(court.totp_secret, interval=3600, digits=4)


async def get_totp_for_all_day(court_id: int) -> list[str]:
    totp_list = []
    today = datetime.now().replace(microsecond=0, second=0, minute=0, hour=0)
    for i in range(24):
        totp_list.append(totp_dict[court_id].at(today + timedelta(hours=i)))
    return totp_list


def get_time_until_full_hour() -> timedelta:
    now = datetime.now()
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    until_full_hour = next_hour - now
    return until_full_hour
