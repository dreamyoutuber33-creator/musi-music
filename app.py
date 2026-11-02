
import os
import requests
from flask import Flask, jsonify, request, Response, abort

app = Flask(__name__)

TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
DB_URL = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/songs"
DB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
WEBHOOK_PATH = os.environ["WEBHOOK_PATH"].strip("/")

TG = f"https://api.telegram.org/bot{TOKEN}"

def headers():
    return {
        "apikey": DB_KEY,
        "Authorization": f"Bearer {DB_KEY}",
        "Content-Type": "application/json"
    }

@app.get("/")
def home():
    return """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Music Hub</title>
<style>
body{background:#100f18;color:white;font-family:Arial;
max-width:700px;margin:35px auto;padding:15px}
input{width:95%;padding:13px;border-radius:12px}
.song{background:#252132;padding:15px;margin:12px 0;border-radius:12px}
audio{width:100%;margin-top:12px}
</style>
</head>
<body>
<h1>🎵 Music Hub</h1>
<p>Music uploaded through Telegram</p>
<input id="q" placeholder="Search music...">
<div id="list">Loading...</div>
<script>
let songs=[];
async function load(){
 try{
  let r=await fetch('/api/songs');
  if(!r.ok)throw Error();
  songs=await r.json();render();
 }catch(e){document.getElementById('list').textContent='Unable to load music.'}
}
function render(){
 let q=document.getElementById('q').value.toLowerCase();
 let list=document.getElementById('list');
 list.replaceChildren();
 let found=songs.filter(s=>s.title.toLowerCase().includes(q));
 if(!found.length){list.textContent='No songs yet.';return}
 found.forEach(s=>{
  let card=document.createElement('div');card.className='song';
  let title=document.createElement('b');title.textContent=s.title;
  let player=document.createElement('audio');
  player.controls=true;player.preload='none';
  player.src='/stream/'+s.id;
  card.append(title,player);list.append(card);
 });
}
document.getElementById('q').addEventListener('input',render);
load();
</script>
</body>
</html>
"""

@app.get("/api/songs")
def songs():
    r = requests.get(DB_URL, headers=headers(),
        params={"select":"id,title,created_at",
                "order":"created_at.desc"}, timeout=15)
    r.raise_for_status()
    return jsonify(r.json())

@app.get("/stream/<int:song_id>")
def stream(song_id):
    r = requests.get(DB_URL, headers=headers(),
        params={"select":"id,file_id","id":f"eq.{song_id}",
                "limit":"1"}, timeout=15)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        abort(404)

    r = requests.get(TG + "/getFile",
        params={"file_id":rows[0]["file_id"]}, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        abort(502)

    path = data["result"]["file_path"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{path}"
    upstream = requests.get(url, stream=True, timeout=30)
    if upstream.status_code != 200:
        upstream.close()
        abort(502)

    def generate():
        try:
            for chunk in upstream.iter_content(65536):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return Response(generate(),
        content_type=upstream.headers.get("Content-Type","audio/mpeg"),
        headers={"Cache-Control":"no-store"})

@app.post("/webhook/" + WEBHOOK_PATH)
def webhook():
    update = request.get_json(silent=True) or {}
    msg = update.get("message") or {}
    if not msg:
        return jsonify(ok=True)

    sender = msg.get("from",{})
    chat_id = msg.get("chat",{}).get("id")
    if sender.get("id") != OWNER_ID or chat_id != OWNER_ID:
        return jsonify(ok=True)

    if msg.get("text") == "/start":
        requests.post(TG + "/sendMessage", json={
            "chat_id":chat_id,
            "text":"Send an audio file to publish it on Music Hub."
        }, timeout=15)
        return jsonify(ok=True)

    audio = msg.get("audio")
    doc = msg.get("document") or {}
    media = audio or (
        doc if doc.get("mime_type","").startswith("audio/") else None
    )
    if not media:
        return jsonify(ok=True)

    if media.get("file_size",0) > 20*1024*1024:
        requests.post(TG + "/sendMessage", json={
            "chat_id":chat_id,"text":"Maximum file size is 20 MB."
        }, timeout=15)
        return jsonify(ok=True)

    title = (audio or {}).get("title") or doc.get("file_name") or "Untitled"
    r = requests.post(DB_URL, headers={
        **headers(),"Prefer":"return=minimal"
    }, json={"title":title[:200],"file_id":media["file_id"]},
       timeout=20)
    r.raise_for_status()

    requests.post(TG + "/sendMessage", json={
        "chat_id":chat_id,"text":"Published: "+title[:200]
    }, timeout=15)
    return jsonify(ok=True)

@app.get("/health")
def health():
    return jsonify(status="ok")
