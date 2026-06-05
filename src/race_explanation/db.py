import os

import psycopg
from psycopg.rows import dict_row


def connect():
    return psycopg.connect(
        host=os.environ.get("RE_DB_HOST", "localhost"),
        port=int(os.environ.get("RE_DB_PORT", "5432")),
        dbname=os.environ.get("RE_DB_NAME", "chartbase"),
        user=os.environ.get("RE_DB_USER", "handycapper"),
        password=os.environ.get("RE_DB_PASSWORD", "handycapper"),
        row_factory=dict_row,
    )
