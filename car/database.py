# car/database.py
import os
import sqlite3
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")  # set by Railway's Postgres

def is_pg() -> bool:
    return bool(DATABASE_URL)

def sqlp(query: str) -> str:
    """Adapta placeholders do SQLite (?) para Postgres (%s)."""
    return query.replace("?", "%s") if is_pg() else query

def create_connection():
    if is_pg():
        # força sslmode=require se não vier na URL (Railway/Postgres costuma pedir)
        url = DATABASE_URL
        if "sslmode=" not in (url or ""):
            sep = "&" if "?" in (url or "") else "?"
            url = f"{url}{sep}sslmode=require"
        return psycopg2.connect(url)
    conn = sqlite3.connect("database.db", check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def create_tables():
    conn = create_connection()
    cur = conn.cursor()

    if is_pg():
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
    else:
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
