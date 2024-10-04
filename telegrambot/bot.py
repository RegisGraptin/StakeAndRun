import io
import os 
import logging
import pathlib
from typing import Any
import dotenv
import base64
import qrcode
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import filters, MessageHandler, ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import uuid
import requests
import json
from datetime import datetime, time, timedelta
#import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import random
import openai
from typing import List, Optional, Type, TypeVar
from pydantic import BaseModel, Field, StrictStr
import requests
from datetime import date

T = TypeVar('T', bound=BaseModel) 
SYSTEM_PROMPT = pathlib.Path("system_prompt.txt").read_text()
USDC_CONTRACT_ADDRESS = '0x2C9678042D52B97D27f2bD2947F7111d93F3dD0D'
CHALLENGE_CONTRACT_ADDRESS = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'
CHAIN_ID = "534351" # scroll sepolia chain id


dotenv.load_dotenv()
openai.api_key = os.getenv('OPENAI_API_KEY')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def load_json_as_model(path: str, model: Type[T]) -> T:
    with open(path, 'r') as file:
        return model.model_validate_json(file.read())

def store_json_as_model(path: str, model: BaseModel):
    with open(path, 'w') as file:
        file.write(model.model_dump_json())

class StoreableBaseModel(BaseModel):
    def save(self, path: str):
        store_json_as_model(path, self)
    
    @classmethod
    def load(cls, path: str):
        return load_json_as_model(path, cls)  
    

class FitnessUser(StoreableBaseModel):
    telegram_id: int
    username: str
    total_kilometers: float = Field(default=0)
    valid_days: int = Field(default=0)
    rest_days: int = Field(default=0)
    last_run_date: Optional[date] = Field(default=None)
    join_date: date = Field(default_factory=date.today)

    def add_run(self, kilometers: float):
        self.total_kilometers += kilometers
        self.valid_days += 1
        self.last_run_date = date.today()

    def add_rest_day(self):
        self.rest_days += 1   

    @classmethod
    def load_user(cls, telegram_id: int):
        path = f'data/fitness_users/{telegram_id}.json'
        try:
            return cls.load(path)
        except FileNotFoundError:
            return None
        except Exception as e:
            logging.error(f"Error loading user data for {telegram_id}: {e}")
            return None

    def save_user(self):
        path = f'data/fitness_users/{self.telegram_id}.json'
        self.save(path)

class RunEvaluation(BaseModel):
    date: str
    valid: bool
    kilometers: float
    message: str

class MockChallengeContract(StoreableBaseModel):
    staking_amount: float = Field(default=10.0)
    members: set[int] = Field(default_factory=set)
    pool: float = Field(default=0.0)
    
    def join(self, telegram_id: int) -> bool:
        if telegram_id in self.members:
            return False
        self.members.add(telegram_id)
        self.pool += self.staking_amount
        return True

try:
    CHALLENGE = MockChallengeContract.load("data/challenge.json")
except FileNotFoundError:
    CHALLENGE = MockChallengeContract(staking_amount=10.0)



async def join_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat is None or update.effective_user is None:
        logging.error(f"Invalid update object, missing effective chat or user: {update}")
        return

    try:
        if update.effective_user.id in CHALLENGE.members:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="You're already part of the challenge!")
            return
    except Exception as e:
        logging.error(f"Error loading user data: {e}")
        # If there's an error loading the user, we'll create a new one

    # Create a new user
    user = FitnessUser(
        telegram_id=update.effective_user.id,
        username=update.effective_user.username or "",
        join_date=date.today()  # Explicitly set join_date
    )
    user.save_user()
    
    CHALLENGE.join(user.telegram_id)
    CHALLENGE.save("data/challenge.json")

# Generate QR code for USDC staking
    amount = CHALLENGE.staking_amount
    eip681_url = f"ethereum:pay-{USDC_CONTRACT_ADDRESS}@{CHAIN_ID}/transfer?address={CHALLENGE_CONTRACT_ADDRESS}&uint256={int(amount * 1e6)}"
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(eip681_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    bio = io.BytesIO()
    img.save(bio, 'PNG')
    bio.seek(0)
    
    metamask_deep_link = f"https://metamask.app.link/send/{eip681_url}"

    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=bio,
        caption=f"Scan this QR code with your mobile wallet to stake USDC and join the challenge.\n\n<a href='{metamask_deep_link}'>Or click here to send directly via MetaMask</a>",
        parse_mode=telegram.constants.ParseMode.HTML
    )










