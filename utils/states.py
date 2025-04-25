from aiogram.fsm.state import StatesGroup, State


# Определение состояний
class SetupFSM(StatesGroup):
    select_court = State()
    input_password = State()
    save_video = State()


class AddCourtFSM(StatesGroup):
    input_court_name = State()


class DeleteCourtFSM(StatesGroup):
    input_court_id = State()

class AddCameraFSM(StatesGroup):
    input_camera_name = State()
    input_camera_login = State()
    input_camera_password = State()
    input_camera_ip = State()
    input_camera_port = State()
