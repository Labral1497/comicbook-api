# app/lib/openai_client.py
from openai import OpenAI
from app.config import config

client = OpenAI(api_key=config.openai_api_key)
