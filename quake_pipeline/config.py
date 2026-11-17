"""Settings, read from environment variables (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("PIPELINE_MODEL", "gemini-3.8-flash")

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "gcs").lower()  # "gcs" or "s3"
BUCKET_NAME = os.getenv("BUCKET_NAME", "")
BUCKET_PREFIX = os.getenv("BUCKET_PREFIX", "earthquakes").strip("/")

DATA_DIR = Path(os.getenv("PIPELINE_DATA_DIR", "data"))
OUTPUT_DIR = Path(os.getenv("PIPELINE_OUTPUT_DIR", "output"))

USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_{period}.geojson"
VALID_PERIODS = ("day", "week", "month")
