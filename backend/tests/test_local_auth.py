import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from app.main import app

ORIGIN = 'http://127.0.0.1:8765'

def client():
    return TestClient(app, base_url=ORIGIN, client=('127.0.0.1', 50000), headers={'origin': ORIGIN})

def credentials(email):
    return {'email': email, 'password': 'safe-local-test-password'}

def test_registration_sessions_roles_and_persistence(tmp_path, monkeypatch):
    db_path = tmp_path / 'auth.sqlite'
    monkeypatch.setenv('STOCKWATCH_AUTH_DB', str(db_path))
    admin, user = client(), client()
    assert admin.get('/api/v1/dataset').status_code == 401
    assert admin.post('/api/v1/auth/register', json=credentials('a@example.test')).json()['user']['roles'] == ['super_admin']
    assert user.post('/api/v1/auth/register', json=credentials('b@example.test')).json()['user']['roles'] == ['user']
    assert admin.post('/api/v1/auth/register', json=credentials('a@example.test')).status_code == 409
    assert admin.post('/api/v1/auth/login', json={'email':'a@example.test', 'password':'incorrect-password'}).status_code == 401
    login = admin.post('/api/v1/auth/login', json=credentials('a@example.test'))
    assert login.status_code == 200
    cookie = login.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie
    assert admin.get('/api/v1/session').json()['user']['roles'] == ['super_admin']
    assert admin.get('/api/v1/dataset').status_code == 200
    assert user.post('/api/v1/auth/login', json=credentials('b@example.test')).status_code == 200
    assert user.get('/api/v1/session').status_code == 200
    assert user.get('/api/v1/dataset').status_code == 403
    assert user.post('/api/v1/chat', json={'message':'hello'}).status_code == 403
    token = admin.cookies.get('stockwatch_session')
    with sqlite3.connect(db_path) as db:
        row = db.execute('select token_hash from sessions where token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        assert row and token not in str(db.execute('select * from sessions').fetchall())
        hashes = db.execute('select salt,password_hash from users').fetchall()
        assert hashes[0][0] != hashes[1][0] and hashes[0][1] != hashes[1][1]
    restarted = client()
    restarted.cookies.set('stockwatch_session', token)
    assert restarted.get('/api/v1/session').status_code == 200
    assert admin.post('/api/v1/auth/logout').status_code == 200
    assert restarted.get('/api/v1/session').status_code == 401


def test_origin_host_and_loopback_guards(tmp_path, monkeypatch):
    monkeypatch.setenv('STOCKWATCH_AUTH_DB', str(tmp_path / 'auth.sqlite'))
    c = client()
    assert c.post('/api/v1/auth/register', headers={'origin':'https://attacker.example'}, json=credentials('a@example.test')).status_code == 403
    no_origin = TestClient(app, base_url=ORIGIN, client=('127.0.0.1', 50000))
    assert no_origin.post('/api/v1/auth/register', json=credentials('a@example.test')).status_code == 403
    assert c.post('/api/v1/auth/register', headers={'host':'attacker.example'}, json=credentials('a@example.test')).status_code == 403
    foreign = TestClient(app, base_url=ORIGIN, client=('192.0.2.5', 50000), headers={'origin':ORIGIN})
    assert foreign.get('/api/v1/health').status_code == 403
    assert c.post('/api/v1/auth/register', json=credentials('a@example.test')).json()['user']['roles'] == ['super_admin']


def test_concurrent_first_registration_has_one_admin(tmp_path, monkeypatch):
    monkeypatch.setenv('STOCKWATCH_AUTH_DB', str(tmp_path / 'auth.sqlite'))
    # Create schema before racing to focus on administrator bootstrap.
    assert client().get('/api/v1/session').status_code == 401
    def signup(i):
        return client().post('/api/v1/auth/register', json=credentials(f'{i}@example.test')).json()['user']['roles'][0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        roles = list(pool.map(signup, range(4)))
    assert roles.count('super_admin') == 1
