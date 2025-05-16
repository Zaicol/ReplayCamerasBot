import random
import string


def generate_password():
    return ''.join(random.choice(string.digits) for _ in range(4))
