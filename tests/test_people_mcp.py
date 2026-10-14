"""People contracts through OAuth/MCP, with optional real synthetic API integration."""
import os, json, logging, unittest
from unittest.mock import patch, AsyncMock
from uuid import uuid4
import test_mcp as oauth
import server
logging.disable(logging.CRITICAL)

class Helpers(unittest.TestCase):
    # Reuse OAuth helpers without inheriting/repeating the 19 regression tests.
    setUp = oauth.MCPTests.setUp
    tearDown = oauth.MCPTests.tearDown
    register = oauth.MCPTests.register
    begin = oauth.MCPTests.begin
    login = oauth.MCPTests.login
    rpc = oauth.MCPTests.rpc
    challenge = oauth.MCPTests.challenge
    def call(self, token, tool, arguments):
        return self.rpc(token, 'tools/call', {'name': tool, 'arguments': arguments}).json()['result']
    def data(self, result):
        self.assertFalse(result.get('isError'), result)
        return json.loads(result['content'][0]['text'])

class PersonToolTests(Helpers):
    def test_new_writes_require_oauth_write_before_any_api_call(self):
        _, tokens, _ = self.login(write=False, scopes=['pachimind:read'])
        examples = {
            'create_person_draft': {'nombre':'Demo'},
            'propose_person_update': {'person_id':'p','revision':'0'*64,'changes':{'organizacion':'Demo'},'evidence':[{'field':'organizacion','source_id':'s','quote':'Demo'}]},
            'apply_person_update': {'proposal_id':str(uuid4()),'revision':'0'*64,'authorized_fields':['organizacion']},
            'propose_note_links': {'source_id':'p','revision':'0'*64,'links':[{'target_id':'s','target_revision':'0'*64,'relation':'fuente','evidence':{'field':'relation','source_id':'s','quote':'Demo'}}]},
            'apply_note_links': {'proposal_id':str(uuid4()),'revision':'0'*64,'authorized_fields':['relations']},
            'create_knowledge_draft': {'title':'Demo','kind':'contexto','content':'Elaborado'},
        }
        with patch.object(server, 'api', new_callable=AsyncMock) as api:
            for name, args in examples.items():
                with self.subTest(tool=name):
                    response = self.rpc(tokens['access_token'], 'tools/call', {'name':name,'arguments':args})
                    self.challenge(response)
            api.assert_not_called()
    def test_new_reads_use_scoped_reader_pagination_and_no_fact_inference(self):
        _, tokens, _ = self.login(write=False)
        with patch.object(server, 'api', new_callable=AsyncMock, return_value={'results':[]}) as api:
            self.data(self.call(tokens['access_token'],'list_people',{'page':2,'per_page':200,'ambito':'Formación','view':'unconnected'}))
            self.assertIn('per_page=100',api.call_args.args[0]);self.assertIn('page=2',api.call_args.args[0]);self.assertEqual(api.call_args.kwargs,{'read':True})
            self.data(self.call(tokens['access_token'],'search_people',{'query':'nombre & alias'}))
            self.assertIn('nombre%20%26%20alias',api.call_args.args[0]);self.assertTrue(api.call_args.kwargs['read'])
            self.data(self.call(tokens['access_token'],'get_person',{'person_id':'p'}));self.assertEqual(api.call_args.args[0],'/people/p/profile')
            self.data(self.call(tokens['access_token'],'list_pending_changes',{'note_id':'p'}));self.assertTrue(api.call_args.kwargs['read'])
    def test_stable_creation_ids_and_knowledge_is_not_a_meeting(self):
        _, tokens, _ = self.login()
        with patch.object(server, 'api', new_callable=AsyncMock, return_value={'id':'demo'}) as api:
            for _ in range(2):self.data(self.call(tokens['access_token'],'create_person_draft',{'nombre':'Demo'}))
            self.assertEqual(api.call_args_list[0].args[2],api.call_args_list[1].args[2])
            self.data(self.call(tokens['access_token'],'create_knowledge_draft',{'title':'Sin fecha','kind':'lectura','content':'Resumen elaborado'}))
            self.assertEqual(api.call_args.args[0],'/notes/knowledge-drafts');self.assertNotIn('fecha',api.call_args.args[2]);self.assertNotIn('participantes',api.call_args.args[2])
    def test_apply_kind_and_authorized_fields_forwarded_exactly(self):
        _, tokens, _ = self.login()
        with patch.object(server, 'api', new_callable=AsyncMock, return_value={'state':'applied'}) as api:
            self.data(self.call(tokens['access_token'],'apply_person_update',{'proposal_id':str(uuid4()),'revision':'a'*64,'authorized_fields':['organizacion']}))
            body=api.call_args.args[2];self.assertEqual(body['expected_kind'],'person');self.assertEqual(body['authorized_fields'],['organizacion']);self.assertEqual(body['revision'],'a'*64)
            self.data(self.call(tokens['access_token'],'apply_note_links',{'proposal_id':str(uuid4()),'revision':'a'*64,'authorized_fields':['relations']}))
            self.assertEqual(api.call_args.args[2]['expected_kind'],'links')

@unittest.skipUnless(os.environ.get('PACHIMIND_TEST_API_URL'), 'Set a loopback synthetic API URL to run integration')
class PeopleAPIIntegrationTests(Helpers):
    def setUp(self):
        super().setUp()
        import httpx
        from urllib.parse import urlparse
        address=os.environ['PACHIMIND_TEST_API_URL']
        self.assertIn(urlparse(address).hostname, {'localhost','127.0.0.1'})
        marker=httpx.get(address+'/health/preview',trust_env=False).json();self.assertTrue(marker.get('synthetic'))
        self.previous_api=server.API;server.API=address
        self.client_id,self.tokens,_=self.login()
    def tearDown(self):
        server.API=self.previous_api
        super().tearDown()
    def make(self):
        existing=self.data(self.call(self.tokens['access_token'],'list_people',{'per_page':100}))['results']
        return self.data(self.call(self.tokens['access_token'],'create_person_draft',{'nombre':'Integración ficticia '+uuid4().hex[:10],
                          'distinct_from':[p['id'] for p in existing],'request_id':str(uuid4())}))
    def test_real_api_create_retry_read_and_oauth_read_only_rejection(self):
        existing=self.data(self.call(self.tokens['access_token'],'list_people',{'per_page':100}))['results']
        args={'nombre':'Ficha integración '+uuid4().hex[:10],'distinct_from':[p['id'] for p in existing],'request_id':str(uuid4())}
        first=self.data(self.call(self.tokens['access_token'],'create_person_draft',args));second=self.data(self.call(self.tokens['access_token'],'create_person_draft',args))
        self.assertEqual(first['id'],second['id']);self.assertFalse(second['created'])
        profile=self.data(self.call(self.tokens['access_token'],'get_person',{'person_id':first['id']}))
        self.assertFalse(profile['metadata']['revisado']);self.assertIsNone(profile['fields']['funcion'])
        _,read,_=self.login(write=False)
        denied=self.call(read['access_token'],'create_person_draft',{'nombre':'No autorizado'})
        self.assertTrue(denied['isError']);self.assertIn('mcp/www_authenticate',denied['_meta'])
        self.data(self.call(read['access_token'],'get_person',{'person_id':first['id']}))
    def test_real_api_pending_update_protection_and_verified_sources(self):
        created=self.make();profile=self.data(self.call(self.tokens['access_token'],'get_person',{'person_id':created['id']}))
        args={'person_id':created['id'],'revision':profile['revision'],'changes':{'organizacion':'Organización de ejemplo'},
              'evidence':[{'field':'organizacion','source_id':'06-reuniones-y-registros-fuente-demo','quote':'Documento sintético: Organización de ejemplo.'}], 'request_id':str(uuid4())}
        proposed=self.data(self.call(self.tokens['access_token'],'propose_person_update',args))
        still=self.data(self.call(self.tokens['access_token'],'get_person',{'person_id':created['id']}));self.assertIsNone(still['fields']['organizacion'])
        pending=self.data(self.call(self.tokens['access_token'],'list_pending_changes',{'note_id':created['id']}));self.assertEqual(pending['total'],1)
        applied=self.data(self.call(self.tokens['access_token'],'apply_person_update',{'proposal_id':proposed['id'],'revision':profile['revision'],'authorized_fields':['organizacion'],'request_id':str(uuid4())}))
        self.assertEqual(applied['state'],'applied')
        verified=self.data(self.call(self.tokens['access_token'],'get_person',{'person_id':created['id']}));self.assertEqual(verified['fields']['organizacion'],'Organización de ejemplo')
        protected=self.data(self.call(self.tokens['access_token'],'get_person',{'person_id':'04-entidades-personas-0-demo'}))
        args.update(person_id=protected['id'],revision=protected['revision'],request_id=str(uuid4()))
        proposed=self.data(self.call(self.tokens['access_token'],'propose_person_update',args))
        error=self.call(self.tokens['access_token'],'apply_person_update',{'proposal_id':proposed['id'],'revision':protected['revision'],'authorized_fields':['organizacion']})
        self.assertTrue(error['isError'])
    def test_real_api_links_and_private_data_exclusion(self):
        created=self.make()
        import httpx
        target=self.data(self.call(self.tokens['access_token'],'read_note',{'note_id':'06-reuniones-y-registros-fuente-demo'}))
        args={'source_id':created['id'],'revision':created['revision'],'links':[{'target_id':target['id'],'target_revision':target['revision'],'relation':'fuente',
                'evidence':{'field':'relation','source_id':target['id'],'quote':'Documento sintético: Organización de ejemplo.'}}], 'request_id':str(uuid4())}
        proposed=self.data(self.call(self.tokens['access_token'],'propose_note_links',args))
        applied=self.data(self.call(self.tokens['access_token'],'apply_note_links',{'proposal_id':proposed['id'],'revision':created['revision'],'authorized_fields':['relations']}))
        self.assertEqual(applied['state'],'applied')
        profile=self.data(self.call(self.tokens['access_token'],'get_person',{'person_id':created['id']}));self.assertEqual(profile['outgoing_count'],1)
        for _ in range(2):self.call(self.tokens['access_token'],'apply_note_links',{'proposal_id':proposed['id'],'revision':created['revision'],'authorized_fields':['relations']})
        self.assertEqual(self.data(self.call(self.tokens['access_token'],'get_person',{'person_id':created['id']}))['outgoing_count'],1)
        hidden=self.call(self.tokens['access_token'],'get_person',{'person_id':'04-entidades-personas-reservada-demo'});self.assertTrue(hidden['isError']);self.assertNotIn('RESERVADO NO DIVULGAR',str(hidden))
    def test_real_api_knowledge_without_meeting_date(self):
        args={'title':'Conocimiento sintético sin fecha','kind':'contexto','content':'Resumen elaborado de prueba, no transcripción.',
              'source_ids':['06-reuniones-y-registros-fuente-demo'],'request_id':str(uuid4())}
        first=self.data(self.call(self.tokens['access_token'],'create_knowledge_draft',args));second=self.data(self.call(self.tokens['access_token'],'create_knowledge_draft',args))
        self.assertEqual(first['id'],second['id']);self.assertFalse(second['created'])
        import httpx
        note=httpx.get(server.API+'/notes/'+first['id'],headers={'X-API-Key':'test-personal'},trust_env=False).json()
        self.assertIsNone(note['metadata']['fecha']);self.assertNotEqual(note['metadata']['tipo'],'reunion');self.assertEqual(note['content'],args['content'])

if __name__=='__main__':unittest.main()
