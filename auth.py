"""Single-owner OAuth store. Protocol validation and PKCE are handled by the MCP SDK."""
import hashlib, json, secrets, sqlite3, time
from pathlib import Path
from urllib.parse import urlparse
from mcp.server.auth.provider import AuthorizationCode, AccessToken, RefreshToken, AuthorizationParams, RegistrationError, AuthorizeError, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

READ_SCOPES=['pachimind:read']
SCOPES=[*READ_SCOPES,'pachimind:write']
def hashed(value):return hashlib.sha256(value.encode()).hexdigest()

class Provider:
    def __init__(self,path,issuer,development=False):
        self.path=str(path);self.issuer=issuer.rstrip('/');self.resource=self.issuer+'/mcp';self.development=development
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records(kind TEXT,key TEXT,value TEXT,expires REAL,family TEXT,PRIMARY KEY(kind,key))')
        Path(path).chmod(0o600)
    def db(self):return sqlite3.connect(self.path,timeout=10)
    def save(self,kind,key,value,expires=None,family=None,db=None):
        if db is not None:db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)',(kind,key,json.dumps(value),expires,family));return
        with self.db() as db:self.save(kind,key,value,expires,family,db)
    def get(self,kind,key,db=None):
        if db is None:
            with self.db() as db:return self.get(kind,key,db)
        r=db.execute('SELECT value,expires FROM records WHERE kind=? AND key=?',(kind,key)).fetchone()
        return json.loads(r[0]) if r and (r[1] is None or r[1]>time.time()) else None
    def pop(self,kind,key,db):
        value=self.get(kind,key,db);db.execute('DELETE FROM records WHERE kind=? AND key=?',(kind,key));return value
    async def get_client(self,client_id):
        value=self.get('client',client_id)
        return OAuthClientInformationFull.model_validate(value) if value else None
    async def register_client(self,client_info):
        if not self.limit("register",60,3600):raise RegistrationError("invalid_client_metadata","Demasiados registros; reintentar más tarde.")
        for redirect in client_info.redirect_uris:
            u=urlparse(str(redirect));valid=u.scheme=='https' and u.hostname in {'chatgpt.com','chat.openai.com'} and not u.username and not u.fragment and u.port in (None,443)
            valid=valid or str(redirect)=='http://localhost:8765/callback'
            valid=valid or (self.development and u.scheme=='http' and u.hostname in {'127.0.0.1','localhost'})
            if not valid:raise RegistrationError('invalid_redirect_uri','Callback no permitido; usar ChatGPT HTTPS o http://localhost:8765/callback para Claude.')
        self.save('client',client_info.client_id,client_info.model_dump(mode='json'))
    async def authorize(self,client,params):
        if params.resource not in (None,self.resource):raise AuthorizeError('invalid_request','Recurso incorrecto')
        # Registered capabilities are not grants. An omitted scope requests
        # read only; write still needs a requested scope and explicit consent.
        scopes=params.scopes if params.scopes is not None else READ_SCOPES
        if not set(scopes)<=set(SCOPES):raise AuthorizeError('invalid_scope')
        params=params.model_copy(update={'scopes':list(scopes)})
        pending=secrets.token_urlsafe(32)
        self.save('pending',hashed(pending),{'client_id':client.client_id,'params':params.model_dump(mode='json')},time.time()+600)
        return self.issuer+'/mcp-login?request='+pending
    def approve(self,pending,csrf,cookie,allow_write=False):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            record=self.get('pending',hashed(pending),db)
            if not record:raise ValueError('La autorización venció o ya fue utilizada. Volvé a conectar desde tu asistente.')
            if not cookie:raise ValueError('No se recibió la cookie de autorización. Abrí nuevamente el enlace en el mismo navegador, con cookies habilitadas.')
            if not csrf or not secrets.compare_digest(record.get('csrf',''),hashed(csrf)) or not secrets.compare_digest(csrf,cookie):raise ValueError('El formulario ya no coincide con esta sesión. Recargá la página de autorización e intentá nuevamente.')
            self.pop('pending',hashed(pending),db)
            p=AuthorizationParams.model_validate(record['params']);scopes=p.scopes if p.scopes is not None else READ_SCOPES
            if not allow_write:scopes=[s for s in scopes if s!='pachimind:write']
            code=secrets.token_urlsafe(32)
            obj=AuthorizationCode(code=code,client_id=record['client_id'],scopes=scopes,expires_at=time.time()+120,code_challenge=p.code_challenge,redirect_uri=p.redirect_uri,redirect_uri_provided_explicitly=p.redirect_uri_provided_explicitly,resource=self.resource,subject='pablo')
            value=obj.model_dump(mode='json');value.pop('code');self.save('code',hashed(code),value,obj.expires_at,db=db)
            return code,p
    async def load_authorization_code(self,client,authorization_code):
        value=self.get('code',hashed(authorization_code))
        return AuthorizationCode(code=authorization_code,**value) if value and value['client_id']==client.client_id else None
    def issue(self,client_id,scopes,db,family=None):
        family=family or secrets.token_urlsafe(24);access=secrets.token_urlsafe(40);refresh=secrets.token_urlsafe(40);now=int(time.time())
        fields={'client_id':client_id,'scopes':scopes,'resource':self.resource,'subject':'pablo'}
        self.save('access',hashed(access),dict(fields,expires_at=now+3600),now+3600,family,db)
        self.save('refresh',hashed(refresh),dict(fields,expires_at=now+2592000),now+2592000,family,db)
        return OAuthToken(access_token=access,refresh_token=refresh,token_type='Bearer',expires_in=3600,scope=' '.join(scopes))
    async def exchange_authorization_code(self,client,authorization_code):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');value=self.pop('code',hashed(authorization_code.code),db)
            if not value or value['client_id']!=client.client_id:raise TokenError('invalid_grant','Código consumido o vencido')
            return self.issue(client.client_id,value['scopes'],db)
    async def load_refresh_token(self,client,refresh_token):
        value=self.get('refresh',hashed(refresh_token))
        return RefreshToken(token=refresh_token,**value) if value and value['client_id']==client.client_id else None
    async def exchange_refresh_token(self,client,refresh_token,scopes):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');key=hashed(refresh_token.token);value=self.get('refresh',key,db)
            if not value or value['client_id']!=client.client_id:raise TokenError('invalid_grant')
            if not set(scopes)<=set(value['scopes']):raise TokenError('invalid_scope')
            family=db.execute('SELECT family FROM records WHERE kind="refresh" AND key=?',(key,)).fetchone()[0]
            db.execute('DELETE FROM records WHERE family=?',(family,))
            return self.issue(client.client_id,scopes,db,family)
    async def load_access_token(self,token):
        value=self.get('access',hashed(token))
        return AccessToken(token=token,**value) if value else None
    async def revoke_token(self,token):
        with self.db() as db:
            row=db.execute('SELECT family FROM records WHERE key=?',(hashed(token.token),)).fetchone()
            if row:db.execute('DELETE FROM records WHERE family=?',(row[0],))
    def limit(self,key,maximum,window):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');name=hashed(key);value=self.get('rate',name,db) or {'count':0,'until':time.time()+window};value['count']+=1
            self.save('rate',name,value,value['until'],db=db)
            return value['count']<=maximum
