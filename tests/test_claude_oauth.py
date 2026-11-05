"""Claude web DCR uses one exact HTTPS callback; PKCE and consent still apply."""
from unittest.mock import patch,AsyncMock
from test_people_mcp import Helpers
from auth import CLAUDE_CALLBACK,SCOPES
import server

class ClaudeOAuthTests(Helpers):
    def test_claude_callback_full_pkce_flow_read_and_explicit_write(self):
        old=server.provider.development;server.provider.development=False
        try:
            client,read,_=self.login(write=False,scopes=['pachimind:read'],redirect_uri=CLAUDE_CALLBACK)
            self.assertEqual(read['scope'],'pachimind:read')
            with patch.object(server,'api',new_callable=AsyncMock) as api:
                response=self.rpc(read['access_token'],'tools/call',{'name':'create_note','arguments':{'title':'Not authorized','content':'Synthetic'}})
                self.challenge(response);api.assert_not_called()
            _,accepted,_=self.login(write=True,client=client,scopes=SCOPES,redirect_uri=CLAUDE_CALLBACK)
            self.assertEqual(accepted['scope'].split(),SCOPES)
        finally:server.provider.development=old

    def test_claude_callback_rejects_similar_domains_paths_queries_and_ports(self):
        old=server.provider.development;server.provider.development=False
        try:
            bad=['http://claude.ai/api/mcp/auth_callback','https://claude.ai.evil.example/api/mcp/auth_callback',
                 'https://evil.example/claude.ai/api/mcp/auth_callback','https://user@claude.ai/api/mcp/auth_callback',
                 'https://claude.ai:444/api/mcp/auth_callback','https://claude.ai/api/mcp/auth_callback/',
                 'https://claude.ai/api/mcp/auth_callback?redirect=evil','https://claude.ai/api/mcp/auth_callback#fragment',
                 'https://claude.ai/callback','https://sub.claude.ai/api/mcp/auth_callback']
            for uri in bad:
                with self.subTest(uri=uri):
                    response=self.c.post('/register',json={'redirect_uris':[uri],'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code']})
                    self.assertEqual(response.status_code,400)
                    self.assertEqual(response.json()['error'],'invalid_redirect_uri')
        finally:server.provider.development=old
