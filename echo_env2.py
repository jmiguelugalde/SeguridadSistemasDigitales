from dotenv import load_dotenv
from pathlib import Path
import os
load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)
print("ENV:", os.getenv("ENV"))
print("DB_HOST:", os.getenv("DB_HOST"))
print("DB_PORT:", os.getenv("DB_PORT"))
print("DB_USER:", os.getenv("DB_USER"))
print("DB_NAME:", os.getenv("DB_NAME"))
