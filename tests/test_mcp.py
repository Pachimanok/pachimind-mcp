import os,tempfile,unittest,json,re,hashlib,base64,secrets,asyncio
from unittest.mock import patch,AsyncMock
from urllib.parse import urlparse,parse_qs,urlencode
from urllib.request import parse_http_list,parse_keqv_list
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
 def register(self,redirect_uri='http://127.0.0.1:9000/callback'):
  r=self.c.post('/register',json={'client_name':'Test client','redirect_uris':[redirect_uri],'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':' '.join(SCOPES)})
  self.assertEqual(r.status_code,201,r.text);return r.json()['client_id']
 def begin(self,client=None,scopes=SCOPES,redirect_uri='http://127.0.0.1:9000/callback'):
  client=client or self.register(redirect_uri);verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
  params={'client_id':client,'redirect_uri':redirect_uri,'response_type':'code','state':'state-123','code_challenge':challenge,'code_challenge_method':'S256','resource':server.ISSUER+'/mcp'}
  if scopes is not None:params['scope']=' '.join(scopes)
  r=self.c.get('/authorize',params=params,follow_redirects=False)
  self.assertIn(r.status_code,[302,303,307]);r=self.c.get(r.headers['location']);self.assertEqual(r.status_code,200)
  form={k:re.search('name="'+k+'" value="([^"]+)"',r.text)[1] for k in ['request','csrf']};form.update(password='test-password',write='yes')
  return client,verifier,form
 def login(self,write=True,client=None,scopes=SCOPES,redirect_uri='http://127.0.0.1:9000/callback'):
  client,verifier,form=self.begin(client,scopes,redirect_uri)
  if not write:form.pop('write')
  r=self.c.post('/mcp-login',data=form,follow_redirects=False);self.assertEqual(r.status_code,303,r.text)
  query=parse_qs(urlparse(r.headers['location']).query);self.assertEqual(query['state'],['state-123']);code=query['code'][0]
  data={'grant_type':'authorization_code','code':code,'client_id':client,'redirect_uri':redirect_uri,'code_verifier':verifier,'resource':server.ISSUER+'/mcp'}
  r=self.c.post('/token',data=data);self.assertEqual(r.status_code,200,r.text);return client,r.json(),data
 def rpc(self,token,method,params=None):
  h={'Accept':'application/json, text/event-stream','Authorization':'Bearer '+token}
  return self.c.post('/mcp',headers=h,json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})
 def capture(self,token):
  return self.rpc(token,'tools/call',{'name':'capture_meeting','arguments':{'project_id':'p','title':'Reunión ficticia','fecha':'2026-10-03','content':'Transcripción ficticia','source':'Prueba'}})
 def challenge(self,response):
  self.assertEqual(response.status_code,200)
  result=response.json()['result'];self.assertTrue(result['isError'])
  self.assertNotIn('structuredContent',result)
  values=result['_meta']['mcp/www_authenticate'];self.assertEqual(len(values),1)
  scheme,params=values[0].split(' ',1);self.assertEqual(scheme,'Bearer')
  parsed=parse_keqv_list(parse_http_list(params))
  self.assertEqual(parsed['error'],'insufficient_scope')
  self.assertEqual(parsed['scope'].split(),SCOPES)
  self.assertEqual(parsed['resource_metadata'],server.ISSUER+'/.well-known/oauth-protected-resource/mcp')
  return parsed
 def test_scope_discovery_and_tool_security_schemes(self):
  initial=self.c.post('/mcp');self.assertEqual(initial.status_code,401)
  challenge=parse_keqv_list(parse_http_list(initial.headers['www-authenticate'].split(' ',1)[1]))
  self.assertEqual(challenge['scope'],'pachimind:read')
  resource=self.c.get(challenge['resource_metadata']).json()
  self.assertEqual(resource['resource'],server.ISSUER+'/mcp')
  self.assertEqual(resource['authorization_servers'],[server.ISSUER+'/'])
  self.assertEqual(resource['scopes_supported'],SCOPES)
  self.assertEqual(self.c.get('/.well-known/oauth-authorization-server').json()['scopes_supported'],SCOPES)
  preflight=self.c.options('/.well-known/oauth-protected-resource/mcp',headers={'Origin':'https://chatgpt.com','Access-Control-Request-Method':'GET'})
  self.assertEqual(preflight.status_code,200);self.assertEqual(preflight.headers['access-control-allow-origin'],'*')
  _,tokens,_=self.login(write=False,scopes=['pachimind:read'])
  tools=self.rpc(tokens['access_token'],'tools/list').json()['result']['tools'];self.assertEqual(len(tools),21)
  writes={'capture_meeting','propose_actions','review_proposal','create_task','update_task','create_person_draft','propose_person_update','apply_person_update','propose_note_links','apply_note_links','create_knowledge_draft'}
  for item in tools:
   with self.subTest(tool=item['name']):
    expected=[{'type':'oauth2','scopes':SCOPES if item['name'] in writes else ['pachimind:read']}]
    self.assertEqual(item['_meta']['securitySchemes'],expected)
    self.assertEqual(item['securitySchemes'],expected)
 def test_read_scope_still_reads_permitted_notes(self):
  _,tokens,_=self.login(write=False,scopes=['pachimind:read'])
  note={'id':'p','title':'Proyecto ficticio','path':'05 Proyectos/p.md','metadata':{'ia_permiso':'allow','ia_indexar':True},'content':'Contenido ficticio'}
  with patch.object(server,'api',new_callable=AsyncMock,return_value=note) as api:
   r=self.rpc(tokens['access_token'],'tools/call',{'name':'read_note','arguments':{'note_id':'p'}})
   self.assertEqual(r.status_code,200);self.assertFalse(r.json()['result'].get('isError'))
   self.assertEqual(json.loads(r.json()['result']['content'][0]['text'])['content'],note['content'])
   api.assert_awaited_once_with('/notes/p')
 def test_all_writes_challenge_before_any_upstream_request(self):
  _,tokens,_=self.login(write=False,scopes=['pachimind:read'])
  calls={
   'capture_meeting':{'project_id':'p','title':'Prueba','fecha':'2026-10-03','content':'Ficticio','source':'Prueba'},
   'propose_actions':{'project_id':'p','meeting_id':'m','items':[{'tipo':'accion','title':'Prueba','detalle':'Ficticio','evidencia':'Ficticio'}]},
   'review_proposal':{'project_id':'p','meeting_id':'m','proposal_id':'a','action':'approve'},
   'create_task':{'title':'Prueba'},
   'update_task':{'task_id':'a','revision':'old','changes':{'estado':'completado'}},
  }
  with patch.object(server,'api',new_callable=AsyncMock) as api:
   for name,args in calls.items():
    with self.subTest(tool=name):self.challenge(self.rpc(tokens['access_token'],'tools/call',{'name':name,'arguments':args}))
   api.assert_not_called()
 def test_chatgpt_step_up_requires_explicit_consent(self):
  callback='https://chatgpt.com/connector/oauth/test'
  client,readonly,_=self.login(write=False,scopes=['pachimind:read'],redirect_uri=callback)
  with patch.object(server,'api',new_callable=AsyncMock) as api:
   scopes=self.challenge(self.capture(readonly['access_token']))['scope'].split();api.assert_not_called()
  _,_,form=self.begin(client,scopes,callback)
  page=self.c.get('/mcp-login',params={'request':form['request']}).text
  checkbox=re.search(r'<input type="checkbox" name="write"[^>]*>',page)[0]
  self.assertNotIn('checked',checkbox)
  _,denied,_=self.login(write=False,client=client,scopes=scopes,redirect_uri=callback)
  self.assertEqual(denied['scope'],'pachimind:read')
  with patch.object(server,'api',new_callable=AsyncMock) as api:
   self.challenge(self.capture(denied['access_token']));api.assert_not_called()
  _,accepted,_=self.login(write=True,client=client,scopes=scopes,redirect_uri=callback)
  self.assertEqual(accepted['scope'].split(),SCOPES)
  async def fake(path,method='GET',body=None,read=False):
   if method=='GET':return {'id':'p','path':'05 Proyectos/p.md','metadata':{'ia_permiso':'allow','ia_indexar':True}}
   return {'id':'meeting-test',**body}
  with patch.object(server,'api',side_effect=fake) as api:
   result=self.capture(accepted['access_token']).json()['result'];self.assertFalse(result.get('isError'))
   self.assertEqual(json.loads(result['content'][0]['text'])['id'],'meeting-test')
   self.assertEqual(api.await_count,2);self.assertEqual(api.call_args.args[:2],('/projects/p/meetings','POST'))
   self.challenge(self.capture(readonly['access_token']))
   self.assertEqual(api.await_count,2) # Old token is not silently upgraded.
 def test_no_scope_or_forged_checkbox_does_not_grant_write(self):
  for scopes in (None,['pachimind:read']):
   with self.subTest(scopes=scopes):
    _,_,form=self.begin(scopes=scopes)
    page=self.c.get('/mcp-login',params={'request':form['request']}).text
    self.assertNotIn('type="checkbox"',page)
    # Even a forged write=yes cannot add a scope that was not requested.
    _,tokens,_=self.login(write=True,scopes=scopes)
    self.assertEqual(tokens['scope'],'pachimind:read')
    with patch.object(server,'api',new_callable=AsyncMock) as api:
     self.challenge(self.capture(tokens['access_token']));api.assert_not_called()
 def test_refresh_cannot_upgrade_read_scope(self):
  client,tokens,_=self.login(write=False,scopes=['pachimind:read'])
  refresh={'grant_type':'refresh_token','refresh_token':tokens['refresh_token'],'client_id':client,'resource':server.ISSUER+'/mcp','scope':' '.join(SCOPES)}
  r=self.c.post('/token',data=refresh);self.assertEqual(r.status_code,400);self.assertEqual(r.json()['error'],'invalid_scope')
  refresh.pop('scope');r=self.c.post('/token',data=refresh);self.assertEqual(r.status_code,200)
  self.assertEqual(r.json()['scope'],'pachimind:read')
  with patch.object(server,'api',new_callable=AsyncMock) as api:
   self.challenge(self.capture(r.json()['access_token']));api.assert_not_called()
 def test_restricted_client_needs_new_registration_for_step_up(self):
  r=self.c.post('/register',json={'redirect_uris':['http://127.0.0.1:9000/callback'],'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':'pachimind:read'})
  self.assertEqual(r.status_code,201);client=r.json()['client_id']
  params={'client_id':client,'redirect_uri':'http://127.0.0.1:9000/callback','response_type':'code','scope':' '.join(SCOPES),'state':'test','code_challenge':'test','code_challenge_method':'S256','resource':server.ISSUER+'/mcp'}
  r=self.c.get('/authorize',params=params,follow_redirects=False)
  self.assertEqual(r.status_code,302);self.assertEqual(parse_qs(urlparse(r.headers['location']).query)['error'],['invalid_scope'])
  self.assertEqual(asyncio.run(server.provider.get_client(client)).scope,'pachimind:read')
  # Re-register with advertised capabilities and ask for consent; do not edit
  # an existing client's registration or grant write during refresh.
  _,tokens,_=self.login(write=True);self.assertEqual(tokens['scope'].split(),SCOPES)
 def test_write_only_token_cannot_bypass_read_requirement(self):
  _,tokens,_=self.login(scopes=['pachimind:write'])
  self.assertEqual(tokens['scope'],'pachimind:write')
  with patch.object(server,'api',new_callable=AsyncMock) as api:
   r=self.capture(tokens['access_token']);self.assertEqual(r.status_code,403)
   challenge=parse_keqv_list(parse_http_list(r.headers['www-authenticate'].split(' ',1)[1]))
   self.assertEqual(challenge['error'],'insufficient_scope');self.assertEqual(challenge['scope'],'pachimind:read')
   api.assert_not_called()
 def test_authorized_capture_preserves_note_restrictions(self):
  _,tokens,_=self.login()
  base={'id':'p','path':'05 Proyectos/p.md','metadata':{'ia_permiso':'allow','ia_indexar':True},'content':'DO NOT LEAK'}
  notes=[dict(base,path=path) for path in ['10 Sensible/p.md','99 Adjuntos/p.md','00 Sistema/p.md','.oculto/p.md','_privado_personal/p.md']]
  notes += [dict(base,metadata=dict(base['metadata'],**changes)) for changes in [{'ia_permiso':'deny'},{'ia_indexar':False},{'sensibilidad':'privado'},{'sensibilidad':'sensible'},{'sensibilidad':'secreto'}]]
  for note in notes:
   with self.subTest(note=note['path'],metadata=note['metadata']),patch.object(server,'api',new_callable=AsyncMock,return_value=note) as api:
    r=self.capture(tokens['access_token']);self.assertTrue(r.json()['result']['isError'])
    self.assertNotIn('mcp/www_authenticate',r.text);self.assertNotIn('DO NOT LEAK',r.text)
    api.assert_awaited_once_with('/notes/p') # GET only: no meeting POST.
 def test_invalid_expired_revoked_or_wrong_resource_cannot_write(self):
  client,tokens,_=self.login()
  with patch.object(server,'api',new_callable=AsyncMock) as api:
   self.assertEqual(self.capture('invalid-test-token').status_code,401)
   with server.provider.db() as db:db.execute("UPDATE records SET expires=0 WHERE kind='access'")
   self.assertEqual(self.capture(tokens['access_token']).status_code,401)
   _,revoked,_=self.login(client=client)
   self.assertEqual(self.c.post('/revoke',data={'client_id':client,'token':revoked['refresh_token']}).status_code,200)
   self.assertEqual(self.capture(revoked['access_token']).status_code,401)
   _,wrong,_=self.login(client=client)
   record=server.provider.get('access',server.hashed(wrong['access_token']));record['resource']='https://other.example/mcp'
   server.provider.save('access',server.hashed(wrong['access_token']),record,record['expires_at'])
   self.assertEqual(self.capture(wrong['access_token']).status_code,401)
   api.assert_not_called()
 def test_discovery_oauth_replay_refresh_revoke(self):
  r=self.c.post('/mcp');self.assertEqual(r.status_code,401);self.assertIn('oauth-protected-resource',r.headers['www-authenticate'])
  self.assertEqual(self.c.get('/.well-known/oauth-protected-resource/mcp').json()['resource'],server.ISSUER+'/mcp')
  self.assertIn('S256',self.c.get('/.well-known/oauth-authorization-server').json()['code_challenge_methods_supported'])
  client,tokens,data=self.login();self.assertEqual(self.c.post('/token',data=data).status_code,400)
  result=self.rpc(tokens['access_token'],'tools/list');self.assertEqual(result.status_code,200,result.text);tools=result.json()['result']['tools'];self.assertEqual(len(tools),21)
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
