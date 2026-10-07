import os
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
pool=ConnectionPool(os.getenv("DATABASE_URL","postgresql://platform:platform_dev_password@localhost:5432/aiplatform"),kwargs={"row_factory":dict_row},open=False)
def init_pool(): pool.open(wait=True,timeout=20)
def query(sql,params=(),fetch=True):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql,params)
            if fetch: return cur.fetchall()
            conn.commit()

from contextlib import contextmanager

@contextmanager
def transaction():
    """Mọi lệnh trong block chạy chung 1 transaction: lỗi thì rollback hết."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            yield cur