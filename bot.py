"""AKAGRI SPAM · Telegram control panel, Python 3.11+, standard library only.
Railway: BOT_TOKEN, OWNER_ID, Volume /data, BOT_DATA_DIR=/data.
Start: python bot.py. Never run the same token in two deployments.
"""
import os
import json
import time
import html
import signal
import secrets
import sqlite3
import threading
import logging
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit

TZ = timezone(timedelta(hours=-3))
MAX_MESSAGES = 100
MAX_GROUPS = 100

class APIError(Exception):
    def __init__(self, code=0, retry=0):
        self.code, self.retry = code, retry
        super().__init__('Telegram HTTP '+str(code))

class Telegram:
    def __init__(self, token): self.token = token
    def call(self, method, **data):
        req = urllib.request.Request('https://api.telegram.org/bot'+self.token+'/'+method,
            data=json.dumps(data).encode(), headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=35) as r: result=json.load(r)
        except urllib.error.HTTPError as e:
            try: result=json.loads(e.read())
            except Exception: raise APIError(e.code) from None
        except (OSError, ValueError): raise APIError() from None
        if not result.get('ok'):
            raise APIError(result.get('error_code',0),result.get('parameters',{}).get('retry_after',0))
        return result['result']

class Store:
    def __init__(self, path):
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS groups(id INTEGER PRIMARY KEY,title TEXT NOT NULL,available INTEGER NOT NULL DEFAULT 1,next_allowed REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,title TEXT NOT NULL,content TEXT,minutes INTEGER NOT NULL DEFAULT 60,first_at REAL,status TEXT NOT NULL DEFAULT 'draft',buttons TEXT NOT NULL DEFAULT '[]');
        CREATE TABLE IF NOT EXISTS targets(message_id TEXT REFERENCES messages(id) ON DELETE CASCADE,group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,due REAL NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'pending',PRIMARY KEY(message_id,group_id));
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT,created REAL NOT NULL,text TEXT NOT NULL);
        ''')
        self.db.commit()
    def run(self,sql,args=()):
        with self.lock,self.db:
            return [dict(r) for r in self.db.execute(sql,args).fetchall()]
    def get(self,key,default=None):
        rows=self.run('SELECT value FROM settings WHERE key=?',(key,))
        return json.loads(rows[0]['value']) if rows else default
    def put(self,key,value):self.run('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value)))
    def event(self,text):
        self.run('INSERT INTO history(created,text) VALUES(?,?)',(time.time(),text))
        self.run('DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 1000)')

def kb(rows):return {'inline_keyboard':[[{'text':label,'callback_data':value} for label,value in row] for row in rows]}
def esc(value):return html.escape(str(value))
def stamp(value):return datetime.fromtimestamp(value,TZ).strftime('%d/%m %H:%M') if value else 'Al activar'
def short(value,n=35):return str(value)[:n]
STATUS={'draft':'Borrador','active':'Activa','paused':'Pausada','completed':'Finalizada'}

class Bot:
    def __init__(self,api,store,owner):
        self.api,self.s,self.owner=api,store,int(owner)
        self.stop=threading.Event();self.lock=threading.RLock();self.bot_id=0;self.username='';self.panel_id=None
    def panel(self,text,rows):
        params={'chat_id':self.owner,'text':text,'parse_mode':'HTML','reply_markup':kb(rows)}
        if self.panel_id:
            try:
                self.api.call('editMessageText',message_id=self.panel_id,**params);return
            except APIError as e:
                if e.code not in (400,):raise
        result=self.api.call('sendMessage',**params);self.panel_id=result['message_id']
    def alert(self,text):self.api.call('sendMessage',chat_id=self.owner,text=text)
    def msg(self,mid):
        rows=self.s.run('SELECT * FROM messages WHERE id=?',(mid,))
        if not rows:raise ValueError('Esa publicación ya no existe.')
        return rows[0]
    def home(self,note=''):
        rows=self.s.run('SELECT status,COUNT(*) n FROM messages GROUP BY status');counts={r['status']:r['n'] for r in rows}
        groups=self.s.run('SELECT COUNT(*) n FROM groups WHERE available=1')[0]['n']
        nexts=self.s.run("SELECT MIN(t.due) due FROM targets t JOIN messages m ON m.id=t.message_id WHERE m.status='active' AND t.state='pending'")
        due=nexts[0]['due']
        paused=self.s.get('global_pause',False)
        self.panel('<b>AKAGRI SPAM</b>\n<i>Tu centro de publicaciones</i>\n\n'
            f"{'⏸ Pausa general' if paused else '🟢 Programador listo'}\n\n"
            f"▸ Publicaciones: <b>{sum(counts.values())}</b>\n▸ Activas: <b>{counts.get('active',0)}</b>\n▸ Grupos disponibles: <b>{groups}</b>\n"
            f"▸ Próximo envío: <b>{'Pausado' if paused else stamp(due) if due else 'Sin programaciones'}</b>\n"
            '\nHorarios de Argentina · UTC−3'+ ('\n\n'+esc(note) if note else ''),[
            [('＋ Nueva publicación','new'),('▤ Publicaciones','list:0')],
            [('♧ Grupos','groups:0'),('◷ Agenda','agenda')],
            [('▷ Reanudar todo' if paused else 'Ⅱ Pausar todo','global')],
            [('≡ Historial','history'),('⚙ Configuración','settings')]])
    def listing(self,page=0):
        rows=self.s.run('SELECT * FROM messages ORDER BY rowid DESC');page=max(0,min(page,max(0,(len(rows)-1)//8)))
        buttons=[[(('🟢 ' if m['status']=='active' else '▫️ ')+short(m['title']), 'view:'+m['id'])] for m in rows[page*8:page*8+8]]
        nav=[]
        if page:nav.append(('←','list:'+str(page-1)))
        if (page+1)*8<len(rows):nav.append(('→','list:'+str(page+1)))
        if nav:buttons.append(nav)
        buttons += [[('＋ Crear','new'),('⌂ Dashboard','home')]]
        self.panel(f'<b>PUBLICACIONES</b> · {len(rows)}\n\nElegí una publicación para editarla o programarla.' if rows else '<b>PUBLICACIONES</b>\n\nCreá tu primer mensaje para comenzar.',buttons)
    def detail(self,mid,note=''):
        m=self.msg(mid);content=json.loads(m['content']) if m['content'] else None
        targets=self.s.run('SELECT * FROM targets WHERE message_id=?',(mid,))
        trouble=sum(t['state'] in ('unknown','failed','delivering') for t in targets)
        snippet=(content.get('text') or 'Foto sin descripción') if content else 'Todavía sin contenido'
        self.panel(f"<b>{esc(m['title'])}</b>\n{STATUS[m['status']]} · {len(targets)} destinos\n\n"
            f"{esc(short(snippet,300))}\n\n"
            f"⏱ {'Cada '+str(m['minutes'])+' minutos' if m['minutes'] else 'Una sola vez'}\n"
            f"◷ Primer envío: {stamp(m['first_at'])}\n🔗 Botones: {len(json.loads(m['buttons']))}"
            +(f'\n⚠ {trouble} entregas requieren revisión.' if trouble else '')
            +('\n\n'+esc(note) if note else ''),[
            [('✎ Contenido','content:'+mid),('Aa Nombre','rename:'+mid)],
            [('♧ Destinos','targets:'+mid+':0'),('⏱ Frecuencia','frequency:'+mid)],
            [('◷ Fecha de inicio','date:'+mid),('🔗 Botones','buttons:'+mid)],
            [('👁 Vista previa','preview:'+mid)],
            [('Ⅱ Pausar' if m['status']=='active' else '▷ Activar','pause:'+mid if m['status']=='active' else 'activate:'+mid)],
            [('⧉ Duplicar','duplicate:'+mid),('× Eliminar','delete:'+mid)],
            [('← Publicaciones','list:0'),('⌂ Dashboard','home')]])
    def group_list(self,page=0,mid=None):
        groups=self.s.run('SELECT * FROM groups ORDER BY title');page=max(0,min(page,max(0,(len(groups)-1)//8)))
        selected={r['group_id'] for r in self.s.run('SELECT group_id FROM targets WHERE message_id=?',(mid,))} if mid else set()
        buttons=[]
        for g in groups[page*8:page*8+8]:
            label=('✅ ' if g['id'] in selected else '▫️ ') if mid else ('🟢 ' if g['available'] else '⚠ ')
            buttons.append([(label+short(g['title']),f"toggle:{mid}:{g['id']}:{page}" if mid else f"group:{g['id']}")])
        prefix='targets:'+mid+':' if mid else 'groups:';nav=[]
        if page:nav.append(('←',prefix+str(page-1)))
        if (page+1)*8<len(groups):nav.append(('→',prefix+str(page+1)))
        if nav:buttons.append(nav)
        buttons += [[('＋ Agregar por ID','addgroup')],[('← Volver','view:'+mid if mid else 'home')]]
        self.panel('<b>DESTINOS</b>\n\n'+('Tocá un grupo para seleccionarlo. Cambiar destinos deja la publicación en borrador.' if mid else 'Se detectan al agregar el bot o recibir eventos del grupo. Para grupos antiguos también podés ingresar el ID.')+('\n\nTodavía no hay grupos.' if not groups else ''),buttons)
    def pending(self,action,mid=None):
        self.s.put('pending',{'action':action,'id':mid})
    def clear(self):self.s.put('pending',None)
    def draft(self,mid):
        self.s.run("UPDATE messages SET status='draft' WHERE id=?",(mid,))
        self.s.run("UPDATE targets SET due=0,state='pending' WHERE message_id=?",(mid,))
    def send_publication(self,chat,m):
        c=json.loads(m['content']);params={'chat_id':chat};buttons=json.loads(m['buttons'])
        if buttons:params['reply_markup']={'inline_keyboard':[buttons[:1]]+([buttons[1:]] if len(buttons)>1 else [])}
        if c['type']=='photo':return self.api.call('sendPhoto',photo=c['file_id'],caption=c.get('text',''),caption_entities=c.get('entities',[]),**params)
        return self.api.call('sendMessage',text=c['text'],entities=c.get('entities',[]),**params)
    def activate(self,mid):
        m=self.msg(mid)
        if m['status']=='active':return self.detail(mid,'Ya está activa.')
        if not m['content']:raise ValueError('Primero agregá el contenido.')
        rows=self.s.run('SELECT t.*,g.available FROM targets t JOIN groups g ON g.id=t.group_id WHERE message_id=?',(mid,))
        if not rows:raise ValueError('Seleccioná al menos un destino.')
        if any(not r['available'] for r in rows):raise ValueError('Hay un grupo sin acceso. Revisá los destinos.')
        if any(r['state'] in ('unknown','failed','delivering') for r in rows):raise ValueError('Hay entregas sin confirmar. Revisá Telegram; después editá la publicación y su fecha antes de activarla de nuevo.')
        if m['status']=='completed':raise ValueError('La publicación terminó. Duplicala para crear otro envío.')
        if m['status']=='draft':
            due=m['first_at'] or time.time()+3
            if due<time.time()-60:raise ValueError('La fecha quedó en el pasado. Cambiá la fecha de inicio.')
            self.s.run("UPDATE targets SET due=?,state='pending' WHERE message_id=?",(due,mid))
        self.s.run("UPDATE messages SET status='active' WHERE id=?",(mid,));self.s.event('Activada: '+m['title'])
        self.detail(mid,'Programación activa.'+(' La pausa general está activada; reanudala desde el dashboard.' if self.s.get('global_pause') else ''))
    def action(self,data):
        bits=data.split(':');action=bits[0];mid=bits[1] if len(bits)>1 else None
        self.clear()
        if action=='home':return self.home()
        if action=='list':return self.listing(int(mid))
        if action=='view':return self.detail(mid)
        if action=='new':
            if len(self.s.run('SELECT id FROM messages'))>=MAX_MESSAGES:raise ValueError('Límite de 100 publicaciones.')
            self.pending('new');return self.panel('<b>NUEVA PUBLICACIÓN</b>\n\nEscribí un nombre interno de hasta 80 caracteres.\nEjemplo: Novedades de la semana.',[[('Cancelar','home')]])
        if action in ('content','rename','date','buttons'):
            self.msg(mid);self.pending(action,mid)
            prompts={'content':'Mandá un texto o una foto con descripción. Se conservará su formato. No se admiten álbumes.','rename':'Escribí el nuevo nombre (hasta 80 caracteres).','date':'Mandá la fecha en formato DD/MM/AAAA HH:MM.\nHorario de Argentina (UTC−3).\n\nEscribí <b>ahora</b> para comenzar al activar.','buttons':'Un botón por línea: <b>Texto | https://enlace</b>\nMáximo cuatro: uno principal y hasta tres debajo.\n\nEscribí <b>quitar</b> para desactivarlos.'}
            return self.panel('<b>EDITAR PUBLICACIÓN</b>\n\n'+prompts[action]+'\n\nGuardar cambios pausa esta publicación.',[[('Cancelar','view:'+mid)]])
        if action=='frequency':
            self.msg(mid);return self.panel('<b>FRECUENCIA</b>\n\nElegí cómo se repite esta publicación.',[[('Una sola vez','once:'+mid)],[('Cada 15 min','interval:'+mid+':15'),('Cada 60 min','interval:'+mid+':60')],[('Personalizar intervalo','custom:'+mid)],[('Volver','view:'+mid)]])
        if action=='custom':
            self.msg(mid);self.pending('interval',mid);return self.panel('<b>INTERVALO</b>\n\nMandá un número de minutos entre 1 y 43200.',[[('Cancelar','view:'+mid)]])
        if action in ('once','interval'):
            self.msg(mid);minutes=0 if action=='once' else int(bits[2]);self.s.run('UPDATE messages SET minutes=? WHERE id=?',(minutes,mid));self.draft(mid);return self.detail(mid)
        if action=='buttons_off':self.s.run("UPDATE messages SET buttons='[]' WHERE id=?",(mid,));self.draft(mid);return self.detail(mid)
        if action=='groups':return self.group_list(int(mid))
        if action=='targets':self.msg(mid);return self.group_list(int(bits[2]),mid)
        if action=='toggle':
            self.msg(mid);gid=int(bits[2]);g=self.s.run('SELECT * FROM groups WHERE id=?',(gid,))
            if not g or not g[0]['available']:raise ValueError('El grupo no está disponible.')
            if self.s.run('SELECT * FROM targets WHERE message_id=? AND group_id=?',(mid,gid)):self.s.run('DELETE FROM targets WHERE message_id=? AND group_id=?',(mid,gid))
            else:self.s.run('INSERT INTO targets(message_id,group_id) VALUES(?,?)',(mid,gid))
            self.draft(mid);return self.group_list(int(bits[3]),mid)
        if action=='addgroup':
            self.pending('addgroup');return self.panel('<b>AGREGAR GRUPO</b>\n\nMandá el ID numérico del grupo, por ejemplo -1001234567890. El bot debe pertenecer a él.',[[('Cancelar','groups:0')]])
        if action=='group':
            rows=self.s.run('SELECT * FROM groups WHERE id=?',(int(mid),))
            if not rows:raise ValueError('Grupo no encontrado.')
            g=rows[0];return self.panel(f"<b>{esc(g['title'])}</b>\n\nID: <code>{g['id']}</code>\n{'Disponible' if g['available'] else 'Sin acceso'}",[[('Verificar permisos','verify:'+mid)],[('Quitar destino','removegroup:'+mid)],[('Volver','groups:0')]])
        if action=='verify':
            self.verify_group(int(mid));return self.action('group:'+mid)
        if action=='removegroup':return self.panel('<b>¿Quitar este grupo?</b>\n\nLas publicaciones afectadas quedarán en borrador.',[[('Confirmar','confirmgroup:'+mid),('Cancelar','group:'+mid)]])
        if action=='confirmgroup':
            for t in self.s.run('SELECT message_id FROM targets WHERE group_id=?',(int(mid),)):self.draft(t['message_id'])
            self.s.run('DELETE FROM groups WHERE id=?',(int(mid),));self.s.put('ignored:'+mid,True);return self.group_list()
        if action=='preview':
            m=self.msg(mid)
            if not m['content']:raise ValueError('Falta el contenido.')
            self.send_publication(self.owner,m);self.panel_id=None;return self.detail(mid,'Vista previa enviada solo a tu chat privado.')
        if action=='activate':
            m=self.msg(mid);return self.panel(f"<b>¿Activar {esc(m['title'])}?</b>\n\nSe publicará en los destinos seleccionados. Si no hay fecha, comenzará en unos segundos.",[[('Confirmar activación','confirm:'+mid),('Cancelar','view:'+mid)]])
        if action=='confirm':return self.activate(mid)
        if action=='pause':self.msg(mid);self.s.run("UPDATE messages SET status='paused' WHERE id=? AND status='active'",(mid,));return self.detail(mid,'Envíos pausados.')
        if action=='duplicate':
            if len(self.s.run('SELECT id FROM messages'))>=MAX_MESSAGES:raise ValueError('Límite de 100 publicaciones.')
            m=self.msg(mid);new=secrets.token_hex(5)
            self.s.run('INSERT INTO messages(id,title,content,minutes,buttons) VALUES(?,?,?,?,?)',(new,m['title'][:70]+' (copia)',m['content'],m['minutes'],m['buttons']))
            for t in self.s.run('SELECT group_id FROM targets WHERE message_id=?',(mid,)):self.s.run('INSERT INTO targets(message_id,group_id) VALUES(?,?)',(new,t['group_id']))
            return self.detail(new,'Copia creada en borrador.')
        if action=='delete':self.msg(mid);return self.panel('<b>¿Eliminar publicación?</b>\n\nEsta acción también elimina su programación.',[[('Eliminar','confirmdelete:'+mid),('Cancelar','view:'+mid)]])
        if action=='confirmdelete':self.s.run('DELETE FROM messages WHERE id=?',(mid,));return self.listing()
        if action=='global':self.s.put('global_pause',not self.s.get('global_pause',False));return self.home()
        if action=='agenda':
            rows=self.s.run("SELECT m.title,t.due,g.title destination FROM targets t JOIN messages m ON m.id=t.message_id JOIN groups g ON g.id=t.group_id WHERE m.status='active' AND t.state='pending' ORDER BY t.due LIMIT 12")
            text='\n\n'.join(f"<b>{stamp(r['due'])}</b> · {esc(short(r['title']))}\n↳ {esc(short(r['destination']))}" for r in rows)
            return self.panel('<b>PRÓXIMOS ENVÍOS</b>\nArgentina · UTC−3\n\n'+(text or 'Sin envíos pendientes.')+('\n\n⏸ Pausa general activa.' if self.s.get('global_pause') else ''),[[('Actualizar','agenda'),('Volver','home')]])
        if action=='history':
            rows=self.s.run('SELECT * FROM history ORDER BY id DESC LIMIT 12')
            return self.panel('<b>HISTORIAL</b>\n\n'+('\n\n'.join(stamp(r['created'])+' · '+esc(short(r['text'],180)) for r in rows) or 'Todavía no hay envíos.'),[[('Actualizar','history'),('Volver','home')]])
        if action=='settings':return self.panel(f'<b>CONFIGURACIÓN</b>\n\nBot: @{esc(self.username)}\nAdministrador: <code>{self.owner}</code>\nHorarios: Argentina · UTC−3\nLímite: 100 publicaciones y 100 grupos\n\nLos datos se guardan en el volumen. El token se lee desde las variables del servicio.\n\n/start · Dashboard\n/pausar · Pausa general\n/reanudar · Reanudar\n/cancelar · Salir de una edición\n\nCada instalación administra un bot independiente.',[[('Volver','home')]])
        self.home()
    def register(self,chat,available=True):
        if chat.get('type') not in ('group','supergroup','channel'):return
        if not self.s.run('SELECT id FROM groups WHERE id=?',(chat['id'],)) and len(self.s.run('SELECT id FROM groups'))>=MAX_GROUPS:raise ValueError('Límite de 100 grupos.')
        self.s.run('INSERT INTO groups(id,title,available) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,available=excluded.available',(chat['id'],chat.get('title',str(chat['id'])),int(available)))
    def verify_group(self,gid):
        chat=self.api.call('getChat',chat_id=gid);member=self.api.call('getChatMember',chat_id=gid,user_id=self.bot_id)
        status=member['status'];ok=status in ('creator','administrator','member')
        if status=='restricted':ok=bool(member.get('is_member') and member.get('can_send_messages'))
        if chat.get('type')=='channel':ok=status=='creator' or (status=='administrator' and member.get('can_post_messages',False))
        if chat.get('type') not in ('group','supergroup','channel'):raise ValueError('Ese chat no es un grupo o canal.')
        self.register(chat,ok)
        if not ok:raise ValueError('El bot no tiene acceso para publicar en ese grupo.')
        self.s.put('ignored:'+str(gid),False)
    def input(self,msg):
        pending=self.s.get('pending');text=msg.get('text','').strip()
        if not pending:return self.home('Elegí una opción del panel.')
        action,mid=pending['action'],pending.get('id')
        if mid:self.msg(mid)
        if action in ('new','rename'):
            if not text or len(text)>80:raise ValueError('Escribí un nombre de 1 a 80 caracteres.')
            if action=='new':
                if len(self.s.run('SELECT id FROM messages'))>=MAX_MESSAGES:raise ValueError('Límite de publicaciones.')
                mid=secrets.token_hex(5);self.s.run('INSERT INTO messages(id,title) VALUES(?,?)',(mid,text));self.clear();return self.action('content:'+mid)
            self.s.run('UPDATE messages SET title=? WHERE id=?',(text,mid))
        elif action=='content':
            if msg.get('media_group_id'):raise ValueError('Mandá una sola foto, sin álbum.')
            if msg.get('photo'):content={'type':'photo','file_id':msg['photo'][-1]['file_id'],'text':msg.get('caption',''),'entities':msg.get('caption_entities',[])}
            elif text:content={'type':'text','text':msg['text'],'entities':msg.get('entities',[])}
            else:raise ValueError('Mandá un texto o una foto con descripción.')
            self.s.run('UPDATE messages SET content=? WHERE id=?',(json.dumps(content),mid));self.draft(mid)
        elif action=='interval':
            try:minutes=int(text)
            except ValueError:raise ValueError('Ingresá un número de minutos.')
            if not 1<=minutes<=43200:raise ValueError('Usá entre 1 y 43200 minutos.')
            self.s.run('UPDATE messages SET minutes=? WHERE id=?',(minutes,mid));self.draft(mid)
        elif action=='date':
            if text.lower()=='ahora':date=None
            else:
                try:date=datetime.strptime(text,'%d/%m/%Y %H:%M').replace(tzinfo=TZ).timestamp()
                except ValueError:raise ValueError('Usá DD/MM/AAAA HH:MM, en horario argentino.')
                if date<=time.time():raise ValueError('Elegí una fecha futura.')
            self.s.run('UPDATE messages SET first_at=? WHERE id=?',(date,mid));self.draft(mid)
        elif action=='buttons':
            buttons=[]
            if text.lower()!='quitar':
                for line in text.splitlines():
                    parts=line.split('|')
                    if len(parts)!=2:raise ValueError('Usá Texto | https://enlace, un botón por línea.')
                    label,url=(p.strip() for p in parts)
                    try:u=urlsplit(url);ok=u.scheme=='https' and bool(u.hostname) and not u.username and not u.password
                    except ValueError:ok=False
                    if not ok or not 1<=len(label)<=64 or len(url)>2000:raise ValueError('Revisá el texto y el enlace HTTPS del botón.')
                    buttons.append({'text':label,'url':url})
                if not 1<=len(buttons)<=4:raise ValueError('Podés agregar de uno a cuatro botones.')
            self.s.run('UPDATE messages SET buttons=? WHERE id=?',(json.dumps(buttons),mid));self.draft(mid)
        elif action=='addgroup':
            try:gid=int(text)
            except ValueError:raise ValueError('Mandá un ID numérico negativo, por ejemplo -1001234567890.')
            if gid>=0:raise ValueError('El ID de grupo debe ser negativo.')
            self.verify_group(gid);self.clear();return self.group_list()
        self.clear();self.detail(mid,'Cambios guardados.')
    def update(self,u):
        member=u.get('my_chat_member')
        if member:
            chat=member['chat'];status=member['new_chat_member']['status']
            if chat.get('type') in ('group','supergroup','channel'):
                n=member['new_chat_member'];available=status in ('member','administrator','creator')
                if status=='restricted':available=bool(n.get('is_member') and n.get('can_send_messages'))
                if chat['type']=='channel':available=status=='creator' or (status=='administrator' and n.get('can_post_messages',False))
                if status in ('member','administrator','creator'):self.s.put('ignored:'+str(chat['id']),False)
                if not self.s.get('ignored:'+str(chat['id']),False):self.register(chat,available)
            return
        query=u.get('callback_query')
        if query:
            allowed=query.get('from',{}).get('id')==self.owner and query.get('message',{}).get('chat',{}).get('type')=='private'
            self.api.call('answerCallbackQuery',callback_query_id=query['id'],text='' if allowed else 'Panel privado.')
            if allowed:
                self.panel_id=query['message']['message_id'];self.action(query.get('data','home'))
            return
        msg=u.get('message',{});chat=msg.get('chat',{})
        if chat.get('type') in ('group','supergroup'):
            gid=chat['id']
            if not self.s.get('ignored:'+str(gid)) and not self.s.run('SELECT id FROM groups WHERE id=?',(gid,)):self.verify_group(gid)
            if msg.get('migrate_to_chat_id'):
                self.s.run('UPDATE groups SET available=0 WHERE id=?',(gid,))
            return
        if chat.get('type')!='private' or msg.get('from',{}).get('id')!=self.owner:return
        self.panel_id=None;command=msg.get('text','').split()[0].split('@')[0].lower() if msg.get('text','').split() else ''
        if command in ('/start','/menu','/cancelar'):self.clear();return self.home()
        if command in ('/pausar','/pause'):self.s.put('global_pause',True);return self.home('Todos los envíos están pausados.')
        if command in ('/reanudar','/resume'):self.s.put('global_pause',False);return self.home('Programador reanudado.')
        if command=='/estado':return self.home()
        self.input(msg)
    def tick(self,now=None):
        now=now or time.time()
        if self.s.get('global_pause') or self.s.get('cooldown',0)>now:return
        rows=self.s.run("SELECT t.*,m.content,m.buttons,m.minutes,m.title FROM targets t JOIN messages m ON m.id=t.message_id JOIN groups g ON g.id=t.group_id WHERE t.state='pending' AND m.status='active' AND t.due<=? AND g.available=1 AND g.next_allowed<=? ORDER BY t.due LIMIT 1",(now,now))
        if not rows:return
        r=rows[0];keys=(r['message_id'],r['group_id'])
        self.s.run("UPDATE targets SET state='delivering' WHERE message_id=? AND group_id=?",keys)
        self.s.run('UPDATE groups SET next_allowed=? WHERE id=?',(now+3.2,r['group_id']))
        try:self.send_publication(r['group_id'],r)
        except APIError as e:
            if e.code==429:
                until=time.time()+max(e.retry,5)+1;self.s.put('cooldown',until)
                self.s.run("UPDATE targets SET state='pending',due=? WHERE message_id=? AND group_id=?",(until,)+keys)
                self.s.event('Telegram pidió esperar antes de reintentar.')
            elif e.code in (400,403):
                self.s.run("UPDATE targets SET state='failed' WHERE message_id=? AND group_id=?",keys)
                self.s.event('Error de contenido o permisos: '+r['title']+' → '+str(r['group_id']))
            else:
                self.s.run("UPDATE targets SET state='unknown' WHERE message_id=? AND group_id=?",keys)
                self.s.event('Entrega no confirmada: '+r['title']+'. Revisá Telegram antes de reactivar.')
                if e.code==401:self.s.put('global_pause',True)
            return
        self.s.event('Enviado: '+r['title']+' → '+str(r['group_id']))
        if r['minutes']:self.s.run("UPDATE targets SET state='pending',due=? WHERE message_id=? AND group_id=?",(time.time()+r['minutes']*60,)+keys)
        else:self.s.run("UPDATE targets SET state='done' WHERE message_id=? AND group_id=?",keys)
        if not self.s.run("SELECT * FROM targets WHERE message_id=? AND state!='done'",(r['message_id'],)):self.s.run("UPDATE messages SET status='completed' WHERE id=?",(r['message_id'],))
    def worker(self):
        while not self.stop.wait(1):
            try:
                with self.lock:self.tick()
            except Exception:logging.error('Error interno del programador; se conserva la reserva de entrega.')
    def run(self):
        me=self.api.call('getMe');self.bot_id=me['id'];self.username=me['username']
        bound=self.s.get('bot_id')
        if bound and bound!=self.bot_id:raise RuntimeError('Este volumen pertenece a otro bot. Usá un volumen separado.')
        self.s.put('bot_id',self.bot_id)
        if self.api.call('getWebhookInfo').get('url'):raise RuntimeError('El bot tiene webhook en otro servicio. Desconectalo allí antes de iniciar.')
        interrupted=self.s.run("SELECT * FROM targets WHERE state='delivering'")
        self.s.run("UPDATE targets SET state='unknown' WHERE state='delivering'")
        if interrupted:self.s.event('Reinicio con entregas sin confirmar. Revisá Telegram antes de reactivar.')
        self.api.call('setMyCommands',commands=[{'command':'start','description':'Abrir dashboard'},{'command':'pausar','description':'Pausar todas las publicaciones'},{'command':'reanudar','description':'Reanudar publicaciones'},{'command':'cancelar','description':'Cancelar edición'}])
        worker=threading.Thread(target=self.worker,daemon=True);worker.start()
        logging.info('AKAGRI SPAM conectado: @%s · administrador %s',self.username,self.owner)
        try:
            while not self.stop.is_set():
                try:
                    updates=self.api.call('getUpdates',offset=self.s.get('offset',0),timeout=20,allowed_updates=['message','callback_query','my_chat_member'])
                    for u in updates:
                        try:
                            with self.lock:self.update(u)
                        except ValueError as e:
                            if u.get('message',{}).get('from',{}).get('id')==self.owner or u.get('callback_query',{}).get('from',{}).get('id')==self.owner:
                                try:self.alert(str(e)+'\n/cancelar para volver al panel.')
                                except APIError:pass
                        except APIError as e:
                            logging.warning('Telegram rechazó una operación: HTTP %s',e.code)
                            if e.code==429:self.stop.wait(max(e.retry,5)+1)
                            try:self.alert('No se pudo completar la operación. Revisá permisos, contenido y conexión. /start para volver.')
                            except APIError:pass
                        except Exception:logging.error('Error interno al procesar una actualización.')
                        finally:self.s.put('offset',u['update_id']+1)
                except APIError as e:
                    if e.code in (401,409):raise RuntimeError('Token inválido o hay otra instancia ejecutando el mismo bot.') from None
                    self.stop.wait(max(e.retry,5)+1)
        finally:self.stop.set();worker.join(timeout=36)

def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    token=os.environ.get('BOT_TOKEN','').strip();owner=os.environ.get('OWNER_ID','').strip()
    if ':' not in token or not owner.isdigit() or int(owner)<=0:raise RuntimeError('Configurá BOT_TOKEN y OWNER_ID (tu ID numérico de Telegram).')
    mount=os.environ.get('RAILWAY_VOLUME_MOUNT_PATH','').strip()
    path=Path(os.environ.get('BOT_DATA_DIR') or mount or str(Path(__file__).resolve().parent/'datos')).resolve()
    if os.environ.get('RAILWAY_ENVIRONMENT_ID') and not mount:raise RuntimeError('Falta el volumen persistente de Railway. Montalo en /data.')
    if mount and (not Path(mount).is_dir() or not path.is_relative_to(Path(mount).resolve())):raise RuntimeError('BOT_DATA_DIR debe apuntar dentro del volumen montado.')
    path.mkdir(parents=True,exist_ok=True);lock=open(path/'instance.lock','a+b')
    try:
        if os.name=='nt':
            import msvcrt
            lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:raise RuntimeError('Ya existe una instancia usando este volumen.') from None
    bot=Bot(Telegram(token),Store(path/'akagri.sqlite3'),int(owner))
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:bot.stop.set())
    try:bot.run()
    finally:lock.close()

if __name__=='__main__':
    try:main()
    except (RuntimeError,APIError) as e:
        logging.error('%s',e)
        raise SystemExit(1)
