import os

from dotenv import load_dotenv


load_dotenv()

BASE_URL = os.getenv("MINIMALL_BASE_URL", "http://localhost:3000")
TIMEOUT = float(os.getenv("MINIMALL_TIMEOUT", "5"))
PREFERRED_PRODUCT_ID = int(os.getenv("MINIMALL_PRODUCT_ID", "3"))
VALID_PHONE = os.getenv("MINIMALL_VALID_PHONE", "13800138001")
VALID_PASSWORD = os.getenv("MINIMALL_VALID_PASSWORD", "Test123")
