import random
import string
from datetime import datetime, timedelta


def generate_password():
    return ''.join(random.choice(string.digits) for _ in range(4))


def password_expiration_to_string(password_expiration_date: datetime) -> str:
    if password_expiration_date > datetime.now():
        time_left = password_expiration_date - datetime.now()
        return f"{(time_left.seconds % 3600) // 60} мин. {time_left.seconds % 60} с."

    return f"пароль истёк!"
