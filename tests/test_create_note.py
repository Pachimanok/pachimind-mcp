"""Ordinary notes use the existing pending-draft API, never meeting/task routes."""
import json
from unittest.mock import patch, AsyncMock
from uuid import uuid4
from test_people_mcp import Helpers
import server
import unittest, os

class CreateNoteTests(Helpers):
    result = {'id':'synthetic-note','path':'07 Conocimiento/Contexto/synthetic.md','created':True,'state':'pending'}

    def test_discovery_default_kind_and_write_scope(self):
        self.assertIn('create_note',self.c.get('/mcp-health').json()['capabilities'])
        _, tokens, _ = self.login(write=False)
        tools = self.rpc(tokens['access_token'], 'tools/list').json()['result']['tools']
        note = next(t for t in tools if t['name'] == 'create_note')
        self.assertEqual(note['inputSchema']['required'], ['title','content'])
        self.assertEqual(note['inputSchema']['properties']['kind']['default'], 'contexto')
        self.assertNotIn('fecha', note['inputSchema']['properties'])
        self.assertNotIn('path', note['inputSchema']['properties'])
        self.assertEqual(note['_meta']['securitySchemes'], [{'type':'oauth2','scopes':['pachimind:read','pachimind:write']}])
        self.assertEqual(note['securitySchemes'], note['_meta']['securitySchemes'])
        self.assertFalse(note['annotations']['readOnlyHint'])
        with patch.object(server,'api',new_callable=AsyncMock) as api:
            r = self.rpc(tokens['access_token'],'tools/call',{'name':'create_note','arguments':{'title':'DOT','content':'Texto sintético'}})
            self.challenge(r)
            api.assert_not_called()

    def test_shared_request_id_across_aliases_preserves_processed_content(self):
        _, tokens, _ = self.login()
        content = '## Texto recibido\nTexto sintético.\n\n## Nota procesada\nResumen separado.\n\n## Pendientes\nPropuestas no aprobadas.\n'
        args = {'title':'Nota de DOT','content':content,'request_id':str(uuid4())}
        with patch.object(server,'api',new_callable=AsyncMock,return_value=self.result) as api:
            self.assertEqual(self.data(self.call(tokens['access_token'],'create_note',args)), self.result)
            self.data(self.call(tokens['access_token'],'create_knowledge_draft',{**args,'kind':'contexto'}))
            self.assertEqual(api.call_args_list[0], api.call_args_list[1])
            body = api.call_args.args[2]
            self.assertEqual(body['content'], content)
            self.assertEqual(body['kind'], 'contexto')
            self.assertEqual(body['request_id'], args['request_id'])
            self.assertNotIn('fecha', body)
            self.assertEqual(api.call_args.args[:2], ('/notes/knowledge-drafts','POST'))

    def test_implicit_retry_key_is_shared_and_explicit_new_uuid_is_distinct(self):
        _, tokens, _ = self.login()
        args = {'title':'Prueba','content':'Mismo texto'}
        with patch.object(server,'api',new_callable=AsyncMock,return_value=self.result) as api:
            self.data(self.call(tokens['access_token'],'create_note',args))
            self.data(self.call(tokens['access_token'],'create_knowledge_draft',{**args,'kind':'contexto'}))
            self.assertEqual(api.call_args_list[0],api.call_args_list[1])
            key = api.call_args.args[2]['request_id']
            self.data(self.call(tokens['access_token'],'create_note',{**args,'request_id':str(uuid4())}))
            self.assertNotEqual(api.call_args.args[2]['request_id'],key)

    def test_invalid_notes_do_not_call_backend(self):
        _, tokens, _ = self.login()
        with patch.object(server,'api',new_callable=AsyncMock) as api:
            for fields in [{'title':' ','content':'Texto'},{'title':'Nota','content':'\n '},{'title':'x'*201,'content':'Texto'},
                           {'title':'Nota','content':'x'*50001},{'title':'Nota','content':'Texto','kind':'reunion'},
                           {'title':'Nota','content':'Texto','request_id':'invalid'}]:
                self.assertTrue(self.call(tokens['access_token'],'create_note',fields)['isError'])
            api.assert_not_called()

    def test_backend_failure_or_incomplete_receipt_is_not_success(self):
        _, tokens, _ = self.login()
        with patch.object(server,'api',new_callable=AsyncMock) as api:
            api.side_effect = ValueError('La API no pudo completar la operación.')
            self.assertTrue(self.call(tokens['access_token'],'create_note',{'title':'Nota','content':'Texto'})['isError'])
            api.side_effect = None
            for result in [{}, {'id':'p'}, {'id':'p','path':'p.md','state':'applied'}]:
                api.return_value = result
                self.assertTrue(self.call(tokens['access_token'],'create_note',{'title':'Nota','content':'Texto'})['isError'])

@unittest.skipUnless(os.environ.get('PACHIMIND_TEST_API_URL'),'Set loopback synthetic API URL for real integration')
class CreateNoteIntegrationTests(Helpers):
    def setUp(self):
        super().setUp()
        import httpx
        from urllib.parse import urlparse
        address=os.environ['PACHIMIND_TEST_API_URL']
        self.assertIn(urlparse(address).hostname, {'localhost','127.0.0.1'})
        self.assertTrue(httpx.get(address+'/health/preview',trust_env=False).json().get('synthetic'))
        self.previous_api=server.API
        server.API=address

    def tearDown(self):
        server.API=self.previous_api
        super().tearDown()

    def notes(self):
        import httpx
        response = httpx.get(server.API+'/notes?per_page=100',headers={'X-API-Key':'test-personal'},trust_env=False)
        response.raise_for_status()
        return response.json()

    def test_persisted_free_note_alias_retry_and_human_verification(self):
        import httpx
        _, tokens, _ = self.login()
        _, reader, _ = self.login(write=False)
        args = {'title':'Nota libre de DOT '+uuid4().hex[:8], 'content':'## Recibido\nNota ficticia.\n\n## Procesado\nTexto revisable, sin inventar decisiones.',
                'source_ids':['06-reuniones-y-registros-fuente-demo'],'request_id':str(uuid4())}
        before = self.notes()['total']
        denied = self.rpc(reader['access_token'],'tools/call',{'name':'create_note','arguments':args})
        self.challenge(denied)
        self.assertEqual(self.notes()['total'],before)
        first = self.data(self.call(tokens['access_token'],'create_note',args))
        second = self.data(self.call(tokens['access_token'],'create_knowledge_draft',{**args,'kind':'contexto'}))
        self.assertEqual(first['id'],second['id']); self.assertFalse(second['created'])
        self.assertEqual(self.notes()['total'],before+1)
        response = httpx.get(server.API+'/notes/'+first['id'],headers={'X-API-Key':'test-personal'},trust_env=False)
        response.raise_for_status();note=response.json()
        self.assertEqual(note['content'],args['content'])
        self.assertEqual(note['metadata']['tipo'],'nota');self.assertIsNone(note['metadata']['fecha'])
        self.assertFalse(note['metadata']['revisado']);self.assertFalse(note['metadata']['ia_indexar'])
        self.assertEqual(first['state'],'pending')
        # Same UUID with changed content is a conflict, not an overwrite.
        conflict = self.call(tokens['access_token'],'create_note',{**args,'content':'Cambio que no debe sobrescribir'})
        self.assertTrue(conflict['isError']);self.assertEqual(self.notes()['total'],before+1)
        note2=httpx.get(server.API+'/notes/'+first['id'],headers={'X-API-Key':'test-personal'},trust_env=False).json()
        self.assertEqual(note2['content'],args['content'])

    def test_reserved_source_and_credential_like_content_do_not_create_notes(self):
        _, tokens, _ = self.login()
        before = self.notes()['total']
        for fields in [{'content':'Texto normal','source_ids':['04-entidades-personas-reservada-demo']},
                       {'content':'api_key=THIS_IS_A_FAKE_SECRET_DO_NOT_STORE'}]:
            result=self.call(tokens['access_token'],'create_note',{'title':'No guardar '+uuid4().hex[:8],**fields,'request_id':str(uuid4())})
            self.assertTrue(result['isError']);self.assertNotIn('RESERVADO NO DIVULGAR',str(result))
        self.assertEqual(self.notes()['total'],before)
