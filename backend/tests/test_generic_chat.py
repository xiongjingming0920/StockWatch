import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.generic_chat import parse_csv, tool

def test_csv_quotes_missing_and_aggregates():
    columns, rows = parse_csv('\ufeff分组,数值\n"甲,乙",1\n丙,\n"甲,乙",3\n')
    assert columns == ['分组', '数值']
    assert tool('profile_dataset', {}, columns, rows)['columns'][1]['missing'] == 1
    assert tool('column_summary', {'column': '数值'}, columns, rows)['mean'] == 2
    group = tool('group_summary', {'group_by': '分组', 'operation': 'sum', 'value_column': '数值'}, columns, rows)
    assert group['groups'][0]['group'] == '甲,乙' and group['groups'][0]['value'] == 4

@pytest.mark.parametrize('value', ['a,a\n1,2', 'a,b\n1', 'a,b\n"bad,2', 'a\n'+('x'*205000), 'a,b\n'])
def test_reject_bad_csv(value):
    with pytest.raises(ValueError): parse_csv(value)

def test_reject_unknown_tool_or_fields():
    cols, rows=parse_csv('a,b\nx,1')
    for name,args in [('exec',{}),('column_summary',{'column':'b','code':'bad'}),('group_summary',{'group_by':'not found','operation':'count'})]:
        with pytest.raises(ValueError): tool(name,args,cols,rows)

def test_chat_no_model_and_validation(monkeypatch, admin_client):
    monkeypatch.delenv('STOCKWATCH_LLM_API_KEY', raising=False)
    with admin_client as client:
        response=client.post('/api/v1/chat',json={'message':'你好','history':[]})
        assert response.status_code==200 and response.json()['answer']
        response=client.post('/api/v1/chat',json={'message':'概况','dataset':{'name':'test.csv','csv':'name,v\na,2'}})
        assert response.status_code==200 and response.json()['evidence']['profile_dataset']['row_count']==1
        assert client.post('/api/v1/chat',json={'message':'问','dataset':{'name':'x','csv':'a,a\n1,2'}}).status_code==422

def test_all_empty_fields_and_missing_group_separate():
    cols, rows=parse_csv('组,值\n,\n（缺失）,3\n\n')
    assert len(rows)==2
    assert tool('column_summary', {'column':'值'}, cols, rows)['missing']==1
    groups=tool('group_summary', {'group_by':'组','operation':'count'},cols,rows)['groups']
    assert len(groups)==2 and sorted(x['is_missing'] for x in groups)==[False,True]

def test_mock_model_tools(monkeypatch, admin_client):
    monkeypatch.setenv('STOCKWATCH_LLM_API_KEY','not-a-real-secret')
    monkeypatch.setenv('STOCKWATCH_LLM_BASE_URL','https://example.invalid')
    monkeypatch.setenv('STOCKWATCH_LLM_MODEL','mock-model')
    class Response:
        def __init__(self,msg): self.msg=msg
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'message':self.msg}]}
    class Client:
        def __init__(self,**kwargs): self.calls=[]
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def post(self,url,headers,json):
            self.calls.append(json)
            if len(self.calls)==1:
                return Response({'content':None,'tool_calls':[{'id':'call1','type':'function','function':{'name':'column_summary','arguments':'{"column":"v"}'}}]})
            assert json['messages'][-1]['role']=='tool'
            return Response({'content':'总和是 3。'})
    monkeypatch.setattr('app.generic_chat.httpx.AsyncClient',Client)
    with admin_client as client:
        res=client.post('/api/v1/chat',json={'message':'求和','dataset':{'name':'x.csv','csv':'v\n1\n2'}})
    assert res.status_code==200
    result=res.json()
    assert result['answer']=='总和是 3。' and result['evidence']['column_summary']['sum']==3
