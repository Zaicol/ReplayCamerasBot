from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from database.models import Courts


def get_courts_keyboard(courts_list: list[Courts]):
    buttons = [
        KeyboardButton(text=court.name)
        for court in courts_list
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=[buttons], resize_keyboard=True)
    return keyboard


def get_back_keyboard():
    keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 К выбору корта")]], resize_keyboard=True)
    return keyboard


def get_saverec_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🎥 Сохранить видео"),
                   KeyboardButton(text="🔙 К выбору корта")]],
        resize_keyboard=True)
    return keyboard
