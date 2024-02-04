import logging
import random
import string
from datetime import datetime

from prefect.runtime import flow_run

logger = logging.getLogger(__name__)
ALPHA_NUM = string.ascii_letters + string.digits


def generate_random_alphanum(length: int = 20) -> str:
    return "".join(random.choices(ALPHA_NUM, k=length))


def generate_flow_run_name():
    flow_name = flow_run.flow_name
    date = datetime.utcnow()
    return f"{flow_name}/{date.strftime('%Y-%m-%d %H:%M:%S')}"
