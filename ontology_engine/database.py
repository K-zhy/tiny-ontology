"""数据库初始化和连接管理"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "demo.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """仅确保表存在，不删除已有数据。"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS student (
            id INTEGER UNIQUE,
            Sno TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            class_name TEXT,
            Sbirthday TEXT
        );

        CREATE TABLE IF NOT EXISTS teacher (
            id INTEGER UNIQUE,
            Tno TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            subject TEXT,
            department TEXT,
            Tsex TEXT,
            Prof TEXT,
            Tyear INTEGER
        );

        CREATE TABLE IF NOT EXISTS course (
            id INTEGER UNIQUE,
            Cno TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            credit INTEGER
        );

        CREATE TABLE IF NOT EXISTS tc (
            id INTEGER UNIQUE,
            Cno TEXT NOT NULL,
            Tno TEXT NOT NULL,
            semester TEXT,
            PRIMARY KEY (Cno, Tno),
            FOREIGN KEY (Cno) REFERENCES course(Cno),
            FOREIGN KEY (Tno) REFERENCES teacher(Tno)
        );

        CREATE TABLE IF NOT EXISTS score (
            id INTEGER UNIQUE,
            Sno TEXT NOT NULL,
            Cno TEXT NOT NULL,
            score_value REAL,
            exam_date TEXT,
            PRIMARY KEY (Sno, Cno),
            FOREIGN KEY (Sno) REFERENCES student(Sno),
            FOREIGN KEY (Cno) REFERENCES course(Cno)
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            action_name TEXT NOT NULL,
            operator TEXT DEFAULT 'system',
            params TEXT,
            result TEXT
        );
    """)
    conn.commit()
    conn.close()


def reset_db():
    """重建所有表，用于 seed 或显式重置环境。"""
    conn = get_connection()
    conn.executescript("""
        DROP TABLE IF EXISTS tc;
        DROP TABLE IF EXISTS score;
        DROP TABLE IF EXISTS course;
        DROP TABLE IF EXISTS teacher;
        DROP TABLE IF EXISTS student;
        DROP TABLE IF EXISTS audit_log;
    """)
    conn.commit()
    conn.close()
    init_db()
