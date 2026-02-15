import os

from dotenv import load_dotenv

load_dotenv()

DEBUG = (os.getenv('DEBUG', 'False') == 'True')
DATABASE_URL = os.getenv("DATABASE_URL", "postgres://postgres:postgres@localhost:6432/exjournalist")
