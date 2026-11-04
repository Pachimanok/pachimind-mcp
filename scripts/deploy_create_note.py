"""Stage and optionally install only the create_note MCP update. Never writes vault/OAuth."""
import argparse, fcntl, hashlib, json, os, pwd, signal, socket, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.request import Request, urlopen
COMMIT = '0a985ed3f24cce30fcb660a76d60dd70308fcb92'
FILES = {'server.py': 'e4a14e7c5c21a977bdd0f5a7898ba8d281f372b9078966799a776456de22158e', 'auth.py': '9602cf3e51a4f705da9733320e1d92b2b7f4927cd05046c60516daef3ccab148', 'people_types.py': '333f066d06b7328df3e8d585ae61cc6e20d4479e864f976adc45656efe039bea', 'requirements.txt': '559dc198bf9693c8de00f287f800379b22abd587056d6420ef655f1863e9290a', 'tests/test_mcp.py': '5f6368b0dbe6819577d599d3461fbd4d3c4217f7d82cf8c8fac256adddd8c481', 'tests/test_people_mcp.py': '115ce40e9103f38105ab7a4524df5eca026a8ede1466597d8cf6dbb414002c9c', 'tests/test_create_note.py': '4b8203ffd321455360d0151e2e279b8e261dd099607e814a950fbb0c543eb111'}
BASE = Path('/srv/pachimind')
MCP = BASE/'mcp'
PREVIOUS_SERVER = '585750bf9882326f1fdabb71c66d7f5250c55a6a4e328143025f335225897fab'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run(args):return subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def active():return subprocess.run(['systemctl','is-active','--quiet','pachimind-mcp']).returncode==0

def fetch_json(url):
    with urlopen(url,timeout=15) as response:return json.load(response)

def install(source,dest):
    account=pwd.getpwnam('pachimind')
    fd,tmp=tempfile.mkstemp(prefix='.create-note-',dir=dest.parent)
    try:
        with os.fdopen(fd,'wb') as out:
            out.write(source.read_bytes());out.flush();os.fsync(out.fileno())
        os.chown(tmp,account.pw_uid,account.pw_gid);os.chmod(tmp,0o640)
        os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def health(new=True):
    for attempt in range(20):
        try:
            result=fetch_json('http://127.0.0.1:8001/mcp-health')
            if result.get('status')=='ok' and (not new or 'create_note' in result.get('capabilities',[])) and active():return
        except (OSError,ValueError):pass
        time.sleep(1)
    raise RuntimeError('El MCP no superó la comprobación de salud/capacidad.')

def main():
    args=argparse.ArgumentParser(description=__doc__)
    args.add_argument('--apply',action='store_true',help='Instalar sólo server.py después de las pruebas')
    opts=args.parse_args()
    if os.geteuid()!=0 or socket.gethostname()!='srv920347':raise RuntimeError('Ejecutar como root en srv920347.')
    os.umask(0o077)
    lock=(BASE/'.create-note-deploy.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (MCP/'server.py').is_symlink():raise RuntimeError('Destino inesperado; no se modifica.')
    if not active():raise RuntimeError('El MCP debe estar activo antes de actualizar.')
    for name in ['auth.py','people_types.py','requirements.txt']:
        if not (MCP/name).is_file() or sha(MCP/name)!=FILES[name]:
            raise RuntimeError('La base de Personas no coincide: '+name+'. No se modifica producción.')
    if sha(MCP/'server.py')==FILES['server.py']:
        health();print('YA ACTUALIZADO: create_note disponible; actualizar la conexión del cliente.');return
    if sha(MCP/'server.py')!=PREVIOUS_SERVER:
        raise RuntimeError('server.py difiere de la versión de Personas conocida. No se reemplaza.')
    schema=fetch_json('http://127.0.0.1:8000/openapi.json')
    if 'post' not in schema.get('paths',{}).get('/notes/knowledge-drafts',{}):
        raise RuntimeError('La API no tiene el endpoint de borradores requerido.')
    stage=Path(tempfile.mkdtemp(prefix='create-note-stage-',dir=BASE))
    print('STAGE:',stage,flush=True)
    for name,expected in FILES.items():
        url='https://raw.githubusercontent.com/Pachimanok/pachimind-mcp/'+COMMIT+'/'+name
        with urlopen(Request(url,headers={'User-Agent':'PachiMind-create-note-deploy'}),timeout=45) as r:data=r.read()
        if hashlib.sha256(data).hexdigest()!=expected:raise RuntimeError('Hash incorrecto: '+name)
        target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    env.pop('PACHIMIND_TEST_API_URL',None)
    # Tests bind only fake credentials, temporary OAuth state and mock API calls.
    with (stage/'tests.log').open('w') as output:
        result=subprocess.run([str(MCP/'.venv/bin/python'),'-m','unittest','discover','-s','tests','-v'],cwd=stage,env=env,stdout=output,stderr=subprocess.STDOUT)
    for line in (stage/'tests.log').read_text(errors='replace').splitlines():
        if line.startswith('Ran ') or line=='OK' or line.startswith('OK (') or line.startswith('FAILED '):print(line,flush=True)
    if result.returncode:raise RuntimeError('Pruebas fallidas; log privado en staging. Producción sin cambios.')
    if not opts.apply:
        print('VERIFICADO. Producción sin cambios; --apply instala sólo server.py.');return
    backup=Path(tempfile.mkdtemp(prefix='mcp-note-backup-',dir=BASE))
    old=(MCP/'server.py').read_bytes()
    if hashlib.sha256(old).hexdigest()!=PREVIOUS_SERVER:raise RuntimeError('El código cambió durante staging; no se instala.')
    (backup/'server.py.anterior').write_bytes(old)
    if sha(backup/'server.py.anterior')!=PREVIOUS_SERVER:raise RuntimeError('Respaldo inválido; no se instala.')
    print('BACKUP:',backup,flush=True)
    try:
        run(['systemctl','stop','pachimind-mcp'])
        install(stage/'server.py',MCP/'server.py')
        run(['systemctl','start','pachimind-mcp'])
        health()
        print('ACTUALIZADO: create_note disponible. API/web, .env, OAuth y vault conservados.',flush=True)
    except BaseException:
        print('Fallo: restaurando server.py anterior.',flush=True)
        try:
            run(['systemctl','stop','pachimind-mcp'])
            install(backup/'server.py.anterior',MCP/'server.py')
            run(['systemctl','start','pachimind-mcp']);health(new=False)
            print('ROLLBACK OK; código anterior restaurado.',flush=True)
        except BaseException:
            print('ROLLBACK FALLÓ. Conservar BACKUP y revisar servicio.',flush=True)
        raise

if __name__=='__main__':
    def interrupted(signum,frame):raise RuntimeError('Proceso interrumpido.')
    signal.signal(signal.SIGTERM,interrupted)
    try:main()
    except BaseException as exc:
        print('STOP:',str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__+'; detalles omitidos para proteger credenciales',file=sys.stderr)
        sys.exit(1)
