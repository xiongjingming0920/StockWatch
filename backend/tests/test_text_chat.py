from app.generic_chat import text_tool
from fastapi.testclient import TestClient
from app.main import app

def test_text_tools_later_match_and_pagination():
    data='前言\n'+('长'*5000)+'\n末尾包含关键事实'
    assert text_tool('text_profile',{},data)['line_count']==3
    assert text_tool('search_text',{'query':'关键事实'},data)['matches'][0]['line']==3
    part=text_tool('read_text_segment',{'start':4000,'length':2000},data)
    assert '关键事实' in part['text'] and part['truncated'] is False

def test_text_payload_validation_and_exclusivity(admin_client):
    client=admin_client
    assert client.post('/api/v1/chat',json={'message':'概况','dataset':{'name':'a.txt','text':'长'*70000}}).status_code==422
    assert client.post('/api/v1/chat',json={'message':'概况','dataset':{'name':'a','text':'text','csv':'a\nb'}}).status_code==422

def test_empty_text_and_invalid_encoding(admin_client):
    client=admin_client
    assert client.post('/api/v1/chat',json={'message':'概况','dataset':{'name':'empty.txt','text':''}}).status_code==422
    assert client.post('/api/v1/chat',content=b'\xff\xfe',headers={'content-type':'application/json'}).status_code==422
    assert client.post('/api/v1/chat',content=b'{"message":"x","dataset":{"name":"a","text":"\\ud800"}}',headers={'content-type':'application/json'}).status_code==422
