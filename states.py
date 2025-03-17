from aiogram.fsm.state import StatesGroup, State

class AiState(StatesGroup):
    waiting_for_query = State()

class AddProductState(StatesGroup):
    waiting_for_product_id = State()

class RemoveProductState(StatesGroup):
    waiting_for_remove_id = State()

class SupportState(StatesGroup):
    waiting_for_message = State()

class SearchState(StatesGroup):
    waiting_for_query = State()
