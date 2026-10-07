import os,tempfile,unittest,json,re,hashlib,base64,secrets,asyncio
from unittest.mock import patch,AsyncMock
from urllib.parse import urlparse,parse_qs,urlencode
from pathlib import Path
os.environ.update(MCP_PUBLIC_URL='http://127.0.0.1:8001',MCP_DEVELOPMENT='1',MCP_DB_PATH=tempfile.mktemp(),PM_API_KEY='test-personal',API_KEYS='{"reader":"ai_context"}',FRONTEND_PASSWORD='test-password')
from starlette.testclient import TestClient
import server
from auth import Provider,SCOPES

class MCPTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=server.provider;server.provider=Provider(Path(self.tmp.name)/'oauth.db',server.ISSUER,True)
  # SDK stores the original provider object; retain one identity while replacing the DB.
  self.oldpath=self.old.path;self.old.path=server.provider.path;server.provider=self.old
  server.server._session_manager=None
  self.c=TestClient(server.create_app(),base_url=server.ISSUER);self.c.__enter__()
 def tearDown(self):
  self.c.__exit__(None,None,None);self.old.path=self.oldpath;self.tmp.cleanup()
 def register(self):
  r=self.c.post('/register',json={'client_name':'Test client','redirect_uris':['http://127.0.0.1:9000/callback'],'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':' '.join(SCOPES)})
  self.assertEqual(r.status_code,201,r.text);return r.json()['client_id']
 def begin(self,client=None):
  client=client or self.register();verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
  r=self.c.get('/authorize',params={'client_id':client,'redirect_uri':'http://127.0.0.1:9000/callback','response_type':'code','scope':' '.join(SCOPES),'state':'state-123','code_challenge':challenge,'code_challenge_method':'S256','resource':server.ISSUER+'/mcp'},follow_redirects=False)
  self.assertIn(r.status_code,[302,303,307]);r=self.c.get(r.headers['location']);self.assertEqual(r.status_code,200)
  form={k:re.search('name="'+k+'" value="([^"]+)"',r.text)[1] for k in ['request','csrf']};form.update(password='test-password',write='yes')
  return client,verifier,form
 def login(self,write=True):
  client,verifier,form=self.begin()
  if not write:form.pop('write')
  r=self.c.post('/mcp-login',data=form,follow_redirects=False);self.assertEqual(r.status_code,303,r.text)
  query=parse_qs(urlparse(r.headers['location']).query);self.assertEqual(query['state'],['state-123']);code=query['code'][0]
  data={'grant_type':'authorization_code','code':code,'client_id':client,'redirect_uri':'http://127.0.0.1:9000/callback','code_verifier':verifier,'resource':server.ISSUER+'/mcp'}
  r=self.c.post('/token',data=data);self.assertEqual(r.status_code,200,r.text);return client,r.json(),data
 def rpc(self,token,method,params=None):
  h={'Accept':'application/json, text/event-stream','Authorization':'Bearer '+token}
  return self.c.post('/mcp',headers=h,json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})
 def test_discovery_oauth_replay_refresh_revoke(self):
  r=self.c.post('/mcp');self.assertEqual(r.status_code,401);self.assertIn('oauth-protected-resource',r.headers['www-authenticate'])
  self.assertEqual(self.c.get('/.well-known/oauth-protected-resource/mcp').json()['resource'],server.ISSUER+'/mcp')
  self.assertIn('S256',self.c.get('/.well-known/oauth-authorization-server').json()['code_challenge_methods_supported'])
  client,tokens,data=self.login();self.assertEqual(self.c.post('/token',data=data).status_code,400)
  result=self.rpc(tokens['access_token'],'tools/list');self.assertEqual(result.status_code,200,result.text);tools=result.json()['result']['tools'];self.assertEqual(len(tools),11)
  readonly=next(t for t in tools if t['name']=='read_note');self.assertTrue(readonly['annotations']['readOnlyHint'])
  refresh={'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'client_id':client,'resource':server.ISSUER+'/mcp'}
  r=self.c.post('/token',data=refresh);self.assertEqual(r.status_code,200,r.text);new=r.json();self.assertEqual(self.rpc(tokens['access_token'],'tools/list').status_code,401)
  self.assertEqual(self.c.post('/token',data=refresh).status_code,400)
  self.assertEqual(self.c.post('/revoke',data={'client_id':client,'token':new['refresh_token']}).status_code,200)
  self.assertEqual(self.rpc(new['access_token'],'tools/list').status_code,401)
 def test_login_origin_and_referrer_policy(self):
  client,verifier,form=self.begin()
  self.assertEqual(server.HEADERS['Referrer-Policy'],'same-origin')
  for origin in ['null','https://evil.example','http://localhost:8765']:
   r=self.c.post('/mcp-login',data=form,headers={'Origin':origin},follow_redirects=False)
   self.assertEqual(r.status_code,403)
  r=self.c.post('/mcp-login',data=form,headers={'Origin':server.ISSUER},follow_redirects=False)
  self.assertEqual(r.status_code,303,r.text)
 def test_parallel_login_and_reload(self):
  _,_,first=self.begin()
  _,_,second=self.begin()
  r=self.c.get('/mcp-login',params={'request':first['request']})
  self.assertIn('value="'+first['csrf']+'"',r.text)
  for form in [first,second]:
   r=self.c.post('/mcp-login',data=form,headers={'Origin':server.ISSUER},follow_redirects=False)
   self.assertEqual(r.status_code,303,r.text)
  self.assertEqual(self.c.post('/mcp-login',data=first).status_code,400)
 def test_missing_cookie_and_expiry(self):
  _,_,form=self.begin()
  self.c.cookies.clear()
  r=self.c.post('/mcp-login',data=form)
  self.assertEqual(r.status_code,400);self.assertIn('cookie',r.text)
  with server.provider.db() as db:
   db.execute("UPDATE records SET expires=0 WHERE kind='pending'")
  r=self.c.post('/mcp-login',data=form)
  self.assertEqual(r.status_code,400);self.assertIn('venció',r.text)
 def test_login_callback_policy_and_feedback(self):
  _,_,form=self.begin()
  r=self.c.get('/mcp-login',params={'request':form['request']})
  policy=r.headers['content-security-policy']
  self.assertIn("form-action 'self' http://127.0.0.1:9000;",policy)
  nonce=re.search(r'<script nonce="([^"]+)"',r.text)[1]
  self.assertIn("script-src 'nonce-"+nonce+"'",policy)
  self.assertIn('button.disabled=true',r.text)
  self.assertIn('event.preventDefault()',r.text)
  self.assertIn('Autorizando…',r.text)
 def test_production_callbacks(self):
  previous=server.provider.development
  server.provider.development=False
  try:
   allowed=['http://localhost:8765/callback','https://chatgpt.com/connector/oauth/test','https://chat.openai.com/callback']
   rejected=['http://localhost:8787/callback','http://localhost:8788/callback','http://127.0.0.1:8765/callback','http://localhost:8765/other','http://localhost:8765/callback/','http://localhost:8765/callback?next=other','http://localhost:8765/callback#fragment','https://evil.example/callback']
   for uri in allowed+rejected:
    with self.subTest(uri=uri):
     r=self.c.post('/register',json={'redirect_uris':[uri],'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code']})
     self.assertEqual(r.status_code,201 if uri in allowed else 400,r.text)
  finally:
   server.provider.development=previous
 def test_login_password_csrf_redirect_and_pkce(self):
  self.assertEqual(self.c.post('/register',json={'redirect_uris':['https://evil.example/callback'],'grant_types':['authorization_code','refresh_token'],'response_types':['code']}).status_code,400)
  client,verifier,form=self.begin();bad=dict(form,password='wrong');self.assertEqual(self.c.post('/mcp-login',data=bad).status_code,403)
  self.assertEqual(self.c.post('/mcp-login',data=dict(form,csrf='wrong')).status_code,400)
  r=self.c.post('/mcp-login',data=form,follow_redirects=False);code=parse_qs(urlparse(r.headers['location']).query)['code'][0]
  r=self.c.post('/token',data={'client_id':client,'grant_type':'authorization_code','code':code,'code_verifier':'wrong','redirect_uri':'http://127.0.0.1:9000/callback'});self.assertEqual(r.status_code,400)
 def test_scopes_privacy_and_no_upstream_on_readonly_write(self):
  _,tokens,_=self.login(write=False)
  with patch.object(server,'api',new_callable=AsyncMock) as api:
   r=self.rpc(tokens['access_token'],'tools/call',{'name':'create_task','arguments':{'title':'No autorizado'}});self.assertTrue(r.json()['result']['isError']);api.assert_not_called()
   api.return_value={'id':'secret','path':'10 Sensible/secret.md','metadata':{'ia_permiso':'allow','ia_indexar':True,'sensibilidad':'normal'},'content':'DO NOT LEAK'}
   r=self.rpc(tokens['access_token'],'tools/call',{'name':'read_note','arguments':{'note_id':'secret'}});self.assertTrue(r.json()['result']['isError']);self.assertNotIn('DO NOT LEAK',r.text)
   api.return_value={'id':'denied','path':'06 Reuniones/denied.md','metadata':{'ia_permiso':'deny','ia_indexar':True},'content':'DO NOT LEAK'}
   r=self.rpc(tokens['access_token'],'tools/call',{'name':'read_note','arguments':{'note_id':'denied'}});self.assertTrue(r.json()['result']['isError']);self.assertNotIn('DO NOT LEAK',r.text)
 def test_capture_is_idempotent_and_updates_keep_omissions(self):
  _,tokens,_=self.login()
  async def fake(path,method='GET',body=None,read=False):
   if path.startswith('/notes/'):return {'id':'p','path':'05 Proyectos/p.md','metadata':{'ia_permiso':'allow','ia_indexar':True},'content':'ok'}
   return body
  with patch.object(server,'api',side_effect=fake) as api:
   args={'project_id':'p','title':'Reunión','fecha':'2026-10-03','content':'Transcripción exacta\r\n','source':'Notas del usuario'}
   a=self.rpc(tokens['access_token'],'tools/call',{'name':'capture_meeting','arguments':args}).json()['result'];b=self.rpc(tokens['access_token'],'tools/call',{'name':'capture_meeting','arguments':args}).json()['result'];self.assertEqual(a,b)
   self.assertEqual(api.call_args.kwargs.get('body',api.call_args.args[-1])['content'],args['content'])
   r=self.rpc(tokens['access_token'],'tools/call',{'name':'update_task','arguments':{'task_id':'a','revision':'old','changes':{'estado':'completado'}}});self.assertFalse(r.json()['result'].get('isError'));self.assertEqual(api.call_args.args[-1],{'revision':'old','estado':'completado'})

if __name__=='__main__':unittest.main()
