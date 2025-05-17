from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from database.models import Courts
from utils.texts import *


def get_courts_keyboard(courts_list: list[Courts]):
    buttons = [
        KeyboardButton(text=court.name)
        for court in courts_list
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=[buttons], resize_keyboard=True)
    return keyboard


def get_back_keyboard():
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=back_text)]], resize_keyboard=True)
    return keyboard


def get_saverec_short_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=save_video_text),
                   KeyboardButton(text=back_text)]],
        resize_keyboard=True)
    return keyboard


def get_saverec_full_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=save_video_text),
                   KeyboardButton(text=back_text)]],
        resize_keyboard=True)
    return keyboard
