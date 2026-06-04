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
    """建表 + 审计日志表"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS student (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            class_name TEXT
        );

        CREATE TABLE IF NOT EXISTS teacher (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            subject TEXT,
            department TEXT
        );

        CREATE TABLE IF NOT EXISTS course (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            teacher_id INTEGER,
            credit INTEGER,
            semester TEXT,
            FOREIGN KEY (teacher_id) REFERENCES teacher(id)
        );

        CREATE TABLE IF NOT EXISTS score (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            score_value REAL,
            exam_date TEXT,
            FOREIGN KEY (student_id) REFERENCES student(id),
            FOREIGN KEY (course_id) REFERENCES course(id)
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
