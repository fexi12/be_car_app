import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
    DATABASE_URL = os.getenv("DATABASE_URL")  # Railway Postgres will set this
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "static/uploads")
