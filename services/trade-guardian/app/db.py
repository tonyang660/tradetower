import psycopg

from config import DB_CONFIG


def get_conn():
    return psycopg.connect(**DB_CONFIG)
