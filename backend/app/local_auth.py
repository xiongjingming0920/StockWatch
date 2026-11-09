from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

COOKIE = 'stockwatch_session'
MAX_AGE = 7 * 24 * 60 * 60
router = APIRouter(prefix='/api/v1/auth')


def db_path():
    return Path(os.environ.get('STOCKWATCH_AUTH_DB') or Path(__file__).resolve().parent.parent / 'data' / 'local-auth.sqlite3')


def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, salt BLOB NOT NULL, password_hash BLOB NOT NULL, role TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires INTEGER NOT NULL)')
    db.commit()
    return db


def loopback_request(request: Request) -> bool:
    try:
        client = ipaddress.ip_address(request.client.host)
        hostname = request.url.hostname
        _ = request.url.port  # Reject malformed Host ports.
        host_allowed = hostname == 'localhost' or ipaddress.ip_address(hostname).is_loopback
        return client.is_loopback and host_allowed
    except (ValueError, AttributeError):
        return False


def valid_origin(request: Request) -> bool:
    origin = request.headers.get('origin', '')
    # Browsers send Origin on cross-origin reads too. Reject forged/foreign Origin.
    try:
        parts = urlsplit(origin)
        return (parts.scheme in ('http', 'https') and not parts.username and not parts.password
                and not parts.path and not parts.query and not parts.fragment
                and origin == f'{request.url.scheme}://{request.url.netloc}')
    except ValueError:
        return False


def user_dict(row):
    return {'id': row[0], 'email': row[1], 'roles': [row[2]]}


def current_user(request: Request):
    token = request.cookies.get(COOKIE, '')
    if not token or len(token) > 256:
        return None
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    with connect() as db:
        row = db.execute('SELECT users.id, users.email, users.role FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.token_hash=? AND sessions.expires>?', (token_hash, int(time.time()))).fetchone()
    return user_dict(row) if row else None


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)


def normalized_credentials(payload: Credentials):
    email = payload.email.strip().lower()
    try:
        password = payload.password.encode('utf-8')
    except UnicodeEncodeError:
        raise HTTPException(422, '邮箱或密码格式无效。')
    if len(email) > 254 or email.count('@') != 1 or any(c.isspace() for c in email) or not all(email.split('@')) or len(password) > 1024:
        raise HTTPException(422, '邮箱或密码格式无效。')
    return email, password


def derive(password: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(password, salt=salt, n=16384, r=8, p=1, dklen=32)


@router.post('/register')
def register(payload: Credentials):
    email, password = normalized_credentials(payload)
    salt = os.urandom(16)
    digest = derive(password, salt)
    uid = str(uuid.uuid4())
    with connect() as db:
        try:
            db.execute('BEGIN IMMEDIATE')
            first = db.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
            role = 'super_admin' if first else 'user'
            db.execute('INSERT INTO users VALUES (?, ?, ?, ?, ?)', (uid, email, salt, digest, role))
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            raise HTTPException(409, '此邮箱已注册。')
    return {'user': user_dict((uid, email, role))}


@router.post('/login')
def login(payload: Credentials, response: Response):
    email, password = normalized_credentials(payload)
    with connect() as db:
        row = db.execute('SELECT id, email, role, salt, password_hash FROM users WHERE email=?', (email,)).fetchone()
        salt = row[3] if row else b'\0' * 16
        expected = row[4] if row else b'\0' * 32
        if not hmac.compare_digest(derive(password, salt), expected) or not row:
            raise HTTPException(401, '邮箱或密码错误。')
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
        db.execute('INSERT INTO sessions VALUES (?, ?, ?)', (hashlib.sha256(token.encode()).hexdigest(), row[0], int(time.time()) + MAX_AGE))
        db.commit()
    response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite='strict', path='/')
    return {'user': user_dict(row)}


@router.post('/logout')
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE, '')
    if token and len(token) <= 256:
        with connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
            db.commit()
    response.delete_cookie(COOKIE, path='/', httponly=True, samesite='strict')
    return {'ok': True}
