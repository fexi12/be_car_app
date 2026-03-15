# car/database.py
import os
import sqlite3
from urllib.parse import urlparse
from contextlib import contextmanager

# ---- Env & defaults ---------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///local.db")  # e.g., sqlite:////data/app.db
# Admin bootstrap: comma-separated usernames (max 3 used), plus a default password
# Example:
#   ADMIN_USERS=admin,alice,bob
#   ADMIN_DEFAULT_PASSWORD=change-me
ADMIN_USERS = [u.strip() for u in os.getenv("ADMIN_USERS", "admin,admin2,admin3").split(",") if u.strip()][:3]
ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD", "admin123")


# ---- DB kind helpers ---------------------------------------------------------

def is_pg() -> bool:
    u = (DATABASE_URL or "").lower()
    return u.startswith("postgres://") or u.startswith("postgresql://")

def is_mysql() -> bool:
    u = (DATABASE_URL or "").lower()
    return u.startswith("mysql://") or u.startswith("mysql+pymysql://")

def is_sqlite() -> bool:
    u = (DATABASE_URL or "").lower()
    return u.startswith("sqlite:")

def _sqlite_path(url: str) -> str:
    # sqlite:///relative.db   -> relative.db
    # sqlite:////absolute.db  -> /absolute.db
    return url.split("sqlite:///", 1)[1]


def sqlp(query: str) -> str:
    """
    Placeholder adapter:
      - SQLite uses "?"
      - Postgres/MySQL use "%s"
    Keep writing queries with "?" and run through sqlp() before executing.
    """
    if is_pg() or is_mysql():
        return query.replace("?", "%s")
    return query


# ---- Connections (lazy imports for drivers) ---------------------------------

def _connect_pg(url: str):
    # Ensure ssl on prod hosts (Railway PG often requires it)
    if "sslmode=" not in url and "localhost" not in url and "127.0.0.1" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    import psycopg2  # lazy
    return psycopg2.connect(url)

def _connect_mysql_from_url(url: str):
    # mysql+pymysql://user:pass@host:port/dbname
    import pymysql  # lazy
    p = urlparse(url)
    return pymysql.connect(
        host=p.hostname, port=p.port or 3306,
        user=p.username, password=p.password,
        database=(p.path or "/").lstrip("/"),
        charset="utf8mb4", autocommit=False, cursorclass=pymysql.cursors.Cursor
    )

def _connect_mysql_from_env():
    import pymysql  # lazy
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DB"),
        charset="utf8mb4", autocommit=False, cursorclass=pymysql.cursors.Cursor
    )

def _connect_sqlite(url: str):
    path = _sqlite_path(url)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def create_connection():
    if is_pg():
        return _connect_pg(DATABASE_URL)
    if is_mysql():
        if DATABASE_URL.lower().startswith(("mysql://", "mysql+pymysql://")):
            return _connect_mysql_from_url(DATABASE_URL)
        return _connect_mysql_from_env()
    # SQLite fallback (default)
    return _connect_sqlite(DATABASE_URL)


@contextmanager
def db_cursor(commit: bool = False):
    conn = create_connection()
    cur = conn.cursor()
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- Schema (with roles) + tiny migrations ----------------------------------

def create_tables():
    """
    Create tables for:
    - vehicles, vehicle_photos, users (with role): car management
    - scraped_listings, listing_price_history: Standvirtual price tracker
    Role is 'admin' or 'user'; default is 'user'.
    """
    with db_cursor(commit=True) as cur:
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
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user'))
            );
            """)
            # Migrate old users table without role
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user';")
            
            # Standvirtual scraper tables
            cur.execute("""
            CREATE TABLE IF NOT EXISTS scraped_listings (
              id SERIAL PRIMARY KEY,
              listing_id TEXT NOT NULL UNIQUE,
              brand TEXT,
              model TEXT,
              year INTEGER,
              price INTEGER,
              url TEXT,
              mileage INTEGER,
              fuel_type TEXT,
              transmission TEXT,
              current_price INTEGER,
              scraped_at TIMESTAMPTZ DEFAULT now(),
              updated_at TIMESTAMPTZ DEFAULT now()
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scraped_listings_listing_id ON scraped_listings(listing_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scraped_listings_brand ON scraped_listings(brand);")
            
            cur.execute("""
            CREATE TABLE IF NOT EXISTS listing_price_history (
              id SERIAL PRIMARY KEY,
              listing_id TEXT NOT NULL REFERENCES scraped_listings(listing_id) ON DELETE CASCADE,
              price INTEGER NOT NULL,
              recorded_at TIMESTAMPTZ DEFAULT now()
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_listing_price_history_listing_id ON listing_price_history(listing_id);")

        elif is_mysql():
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
              CONSTRAINT fk_vehicle FOREIGN KEY (vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
              id INT AUTO_INCREMENT PRIMARY KEY,
              username VARCHAR(255) UNIQUE NOT NULL,
              password_hash VARCHAR(255) NOT NULL,
              role ENUM('admin','user') NOT NULL DEFAULT 'user'
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            # If legacy users table exists without role, add it
            try:
                cur.execute("ALTER TABLE users ADD COLUMN role ENUM('admin','user') NOT NULL DEFAULT 'user';")
            except Exception:
                pass  # column already exists
            
            # Standvirtual scraper tables
            cur.execute("""
            CREATE TABLE IF NOT EXISTS scraped_listings (
              id INT AUTO_INCREMENT PRIMARY KEY,
              listing_id VARCHAR(255) NOT NULL UNIQUE,
              brand VARCHAR(255),
              model VARCHAR(255),
              year INT,
              price INT,
              url VARCHAR(1024),
              mileage INT,
              fuel_type VARCHAR(255),
              transmission VARCHAR(255),
              current_price INT,
              scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scraped_listings_listing_id ON scraped_listings(listing_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scraped_listings_brand ON scraped_listings(brand);")
            
            cur.execute("""
            CREATE TABLE IF NOT EXISTS listing_price_history (
              id INT AUTO_INCREMENT PRIMARY KEY,
              listing_id VARCHAR(255) NOT NULL,
              price INT NOT NULL,
              recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              CONSTRAINT fk_listing_id FOREIGN KEY (listing_id) REFERENCES scraped_listings(listing_id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_listing_price_history_listing_id ON listing_price_history(listing_id);")

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
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user'))
            );
            """)
            # Add role column to legacy users
            cols = [r[1] for r in cur.execute("PRAGMA table_info(users);").fetchall()]
            if "role" not in cols:
                # SQLite can't ADD COLUMN with CHECK reliably on old versions; add basic column
                cur.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user';")
            
            # Standvirtual scraper tables
            cur.execute("""
            CREATE TABLE IF NOT EXISTS scraped_listings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              listing_id TEXT NOT NULL UNIQUE,
              brand TEXT,
              model TEXT,
              year INTEGER,
              price INTEGER,
              url TEXT,
              mileage INTEGER,
              fuel_type TEXT,
              transmission TEXT,
              current_price INTEGER,
              scraped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scraped_listings_listing_id ON scraped_listings(listing_id);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scraped_listings_brand ON scraped_listings(brand);")
            
            cur.execute("""
            CREATE TABLE IF NOT EXISTS listing_price_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              listing_id TEXT NOT NULL,
              price INTEGER NOT NULL,
              recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(listing_id) REFERENCES scraped_listings(listing_id) ON DELETE CASCADE
            );
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_listing_price_history_listing_id ON listing_price_history(listing_id);")


# ---- Admin seeding (exactly up to three admin accounts) ----------------------

def seed_admin_users():
    """
    Create up to three admin users (from ADMIN_USERS) with ADMIN_DEFAULT_PASSWORD
    if they don't exist yet. If they exist but are non-admin, upgrade them to admin.
    """
    from werkzeug.security import generate_password_hash  # lazy

    usernames = ADMIN_USERS or []
    if not usernames:
        return

    with db_cursor(commit=True) as cur:
        for uname in usernames[:3]:
            # Does user exist?
            cur.execute(sqlp("SELECT id, role FROM users WHERE username = ?"), (uname,))
            row = cur.fetchone()
            if row:
                # Ensure role is admin
                if (row[1] or "user") != "admin":
                    cur.execute(sqlp("UPDATE users SET role = ? WHERE id = ?"), ("admin", row[0]))
                continue

            # Create new admin
            cur.execute(sqlp(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)"
            ), (uname, generate_password_hash(ADMIN_DEFAULT_PASSWORD), "admin"))


# ---- Convenience: tiny helpers some routes may import ------------------------

def get_user_by_username(username: str):
    with db_cursor() as cur:
        cur.execute(sqlp("SELECT id, username, password_hash, role FROM users WHERE username = ?"), (username,))
        return cur.fetchone()

def get_user_by_id(user_id: int):
    with db_cursor() as cur:
        cur.execute(sqlp("SELECT id, username, password_hash, role FROM users WHERE id = ?"), (user_id,))
        return cur.fetchone()

def is_admin_user(user_row) -> bool:
    # user_row = (id, username, password_hash, role)
    if not user_row:
        return False
    role = user_row[3] if len(user_row) > 3 else "user"
    return role == "admin"
