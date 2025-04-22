import random
import string


def generate_password():
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(6))
