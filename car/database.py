# car/database.py
import os
import sqlite3
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")  # set by Railway's Postgres

def is_pg(): return bool(DATABASE_URL)

def create_connection():
    if is_pg():
        return psycopg2.connect(DATABASE_URL)
    return sqlite3.connect("database.db", check_same_thread=False)

def create_tables():
    conn = create_connection()
    cur = conn.cursor()

    if is_pg():
        # PostgreSQL schema
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
          id SERIAL PRIMARY KEY,
          brand TEXT,
          model TEXT,
          year INTEGER,
          plate TEXT UNIQUE
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
        # SQLite schema (adjust to match your current columns)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          brand TEXT,
          model TEXT,
          year INTEGER,
          plate TEXT UNIQUE
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
