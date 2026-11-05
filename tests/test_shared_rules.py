"""Shared preferences bootstrap uses the existing protected read_note contract."""
import json
from unittest.mock import patch,AsyncMock
from test_people_mcp import Helpers
import server

class SharedRulesTests(Helpers):
    def test_initialize_points_read_only_clients_to_rules_without_new_tool(self):
        _,tokens,_=self.login(write=False)
        result=self.rpc(tokens['access_token'],'initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'rules-test','version':'1'}})
        self.assertEqual(result.status_code,200,result.text)
        instructions=result.json()['result']['instructions']
        self.assertIn(server.RULES_NOTE_ID,instructions)
        self.assertIn('limit=20000',instructions)
        self.assertIn('subordinadas a instrucciones superiores',instructions)
        self.assertIn('sin autorización explícita',instructions)
        tools=self.rpc(tokens['access_token'],'tools/list').json()['result']['tools']
        self.assertEqual(len(tools),22)

    def test_existing_read_note_fetches_full_shared_rules_with_read_scope(self):
        _,tokens,_=self.login(write=False)
        note={'id':server.RULES_NOTE_ID,'title':'PachiMind reglas vigentes','path':'07 Conocimiento/Contexto/pachimind-reglas-vigentes.md',
              'metadata':{'ia_permiso':'allow','ia_indexar':True,'revisado':True,'ia_editar':False,'fuente_inmutable':True,'sensibilidad':'interno'},
              'content':'A'*12205,'revision':'a'*64}
        with patch.object(server,'api',new_callable=AsyncMock,return_value=note) as api:
            result=self.data(self.call(tokens['access_token'],'read_note',{'note_id':server.RULES_NOTE_ID,'limit':20000}))
            self.assertEqual(result['content'],note['content']);self.assertIsNone(result['next_offset'])
            api.assert_awaited_once_with('/notes/'+server.RULES_NOTE_ID)

    def test_rules_reference_does_not_override_note_privacy(self):
        _,tokens,_=self.login(write=False)
        note={'id':server.RULES_NOTE_ID,'path':'07 Conocimiento/Contexto/pachimind-reglas-vigentes.md','metadata':{'ia_permiso':'deny','ia_indexar':False},'content':'not disclosed'}
        with patch.object(server,'api',new_callable=AsyncMock,return_value=note):
            result=self.call(tokens['access_token'],'read_note',{'note_id':server.RULES_NOTE_ID,'limit':20000})
            self.assertTrue(result['isError']);self.assertNotIn('not disclosed',str(result))
