# car/database.py
import os
import sqlite3
import psycopg2
import pymysql
from urllib.parse import urlparse

DATABASE_URL = os.getenv("DATABASE_URL")  # postgres://... OR mysql+pymysql://...
MYSQL_HOST = os.getenv("MYSQL_HOST")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306")) if os.getenv("MYSQL_PORT") else None
MYSQL_DB   = os.getenv("MYSQL_DB")
MYSQL_USER = os.getenv("MYSQL_USER")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")

def is_pg() -> bool:
    return bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))

def is_mysql() -> bool:
    # Accept either mysql URL or discrete env vars
    if DATABASE_URL and DATABASE_URL.startswith(("mysql://", "mysql+pymysql://")):
        return True
    return all([MYSQL_HOST, MYSQL_DB, MYSQL_USER, MYSQL_PASSWORD])

def sqlp(query: str) -> str:
    """
    Placeholder adapter:
      - SQLite uses "?"
      - Postgres & MySQL use "%s"
    """
    if is_pg() or is_mysql():
        return query.replace("?", "%s")
    return query

def _connect_mysql_from_url(url: str):
    # mysql+pymysql://user:pass@host:port/dbname
    parsed = urlparse(url)
    user = parsed.username
    pwd = parsed.password
    host = parsed.hostname
    port = parsed.port or 3306
    db   = parsed.path.lstrip("/")
    return pymysql.connect(
        host=host, port=port, user=user, password=pwd, database=db,
        charset="utf8mb4", autocommit=False, cursorclass=pymysql.cursors.Cursor
    )

def create_connection():
    if is_pg():
        url = DATABASE_URL
        if "sslmode=" not in (url or ""):
            sep = "&" if "?" in (url or "") else "?"
            url = f"{url}{sep}sslmode=require"
        return psycopg2.connect(url)

    if is_mysql():
        if DATABASE_URL and DATABASE_URL.startswith(("mysql://", "mysql+pymysql://")):
            return _connect_mysql_from_url(DATABASE_URL)
        return pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT or 3306, user=MYSQL_USER,
            password=MYSQL_PASSWORD, database=MYSQL_DB,
            charset="utf8mb4", autocommit=False, cursorclass=pymysql.cursors.Cursor
        )

    # Fallback: SQLite
    conn = sqlite3.connect("database.db", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def create_tables():
    conn = create_connection()
    cur = conn.cursor()

    if is_pg():
        # PostgreSQL
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
          id SERIAL PRIMARY KEY,
          marca TEXT,
          modelo TEXT,
          CC INTEGER,
          cor TEXT,
          matricula TEXT UNIQUE,
          ano INTEGER,
          num_lugares INTEGER,
          local_garagem TEXT,
          estado_geral TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_photos (
          id SERIAL PRIMARY KEY,
          vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE CASCADE,
          photo TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id SERIAL PRIMARY KEY,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL
        );
        """)

    elif is_mysql():
        # MySQL (InnoDB for FK support)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
          id INT AUTO_INCREMENT PRIMARY KEY,
          marca VARCHAR(255),
          modelo VARCHAR(255),
          CC INT,
          cor VARCHAR(255),
          matricula VARCHAR(255) UNIQUE,
          ano INT,
          num_lugares INT,
          local_garagem VARCHAR(255),
          estado_geral VARCHAR(255)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_photos (
          id INT AUTO_INCREMENT PRIMARY KEY,
          vehicle_id INT,
          photo VARCHAR(1024),
          CONSTRAINT fk_vehicle
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id)
            ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id INT AUTO_INCREMENT PRIMARY KEY,
          username VARCHAR(255) UNIQUE NOT NULL,
          password_hash VARCHAR(255) NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

    else:
        # SQLite
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          marca TEXT,
          modelo TEXT,
          CC INTEGER,
          cor TEXT,
          matricula TEXT UNIQUE,
          ano INTEGER,
          num_lugares INTEGER,
          local_garagem TEXT,
          estado_geral TEXT
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_photos (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          vehicle_id INTEGER,
          photo TEXT,
          FOREIGN KEY(vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL
        );
        """)

    conn.commit()
    conn.close()
