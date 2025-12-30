"""
TG Cloud - Optimized for speed
- 1.9GB chunks (Telegram max)
- Real progress with speed/ETA
- Streaming downloads
"""
import os
import asyncio
import threading
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, Response
from werkzeug.utils import secure_filename
from tg_storage import TelegramStorage

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'

Path(app.config['UPLOAD_FOLDER']).mkdir(exist_ok=True)
Path('/tmp/downloads').mkdir(exist_ok=True)

uploads_in_progress = {}

_loop = None
_loop_thread = None

def get_loop():
    global _loop, _loop_thread
    if _loop is None:
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
        _loop_thread.start()
    return _loop

def run_async(coro):
    return asyncio.run_coroutine_threadsafe(coro, get_loop()).result()

def get_storage():
    return TelegramStorage(
        api_id=os.environ.get('TG_API_ID'),
        api_hash=os.environ.get('TG_API_HASH'),
        channel_id=os.environ.get('TG_CHANNEL_ID')
    )

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>TG Cloud</title>
    <style>
        * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        body { max-width: 900px; margin: 0 auto; padding: 20px; background: #0f0f0f; color: #fff; }
        h1 { color: #0088cc; }
        .upload-zone { 
            border: 2px dashed #0088cc; padding: 60px; text-align: center; 
            border-radius: 12px; margin: 20px 0; cursor: pointer; transition: all 0.3s;
        }
        .upload-zone:hover, .upload-zone.dragover { background: #0088cc22; border-color: #00aaff; }
        .upload-zone input { display: none; }
        .progress { height: 30px; background: #222; border-radius: 15px; overflow: hidden; margin: 10px 0; display: none; position: relative; }
        .progress-bar { height: 100%; background: linear-gradient(90deg, #0088cc, #00aaff); width: 0%; transition: width 0.2s; }
        .progress-text { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); font-size: 13px; font-weight: 600; text-shadow: 0 1px 2px rgba(0,0,0,0.5); }
        .file-list { margin-top: 30px; }
        .file { display: flex; justify-content: space-between; align-items: center; padding: 15px; background: #1a1a1a; border-radius: 8px; margin: 10px 0; }
        .file-info { flex: 1; }
        .file-name { font-weight: 600; color: #fff; }
        .file-meta { color: #888; font-size: 14px; margin-top: 4px; }
        .btn { padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; transition: all 0.2s; }
        .btn-download { background: #0088cc; color: #fff; margin-right: 8px; }
        .btn-download:hover { background: #00aaff; }
        .btn-delete { background: #ff4444; color: #fff; }
        .btn-delete:hover { background: #ff6666; }
        .status { padding: 15px; border-radius: 8px; margin: 10px 0; display: none; }
        .status.success { background: #00aa0022; border: 1px solid #00aa00; color: #00cc00; }
        .status.error { background: #ff000022; border: 1px solid #ff0000; color: #ff4444; }
        .stats { display: flex; gap: 20px; margin: 20px 0; }
        .stat { background: #1a1a1a; padding: 20px; border-radius: 8px; flex: 1; text-align: center; }
        .stat-value { font-size: 28px; font-weight: 700; color: #0088cc; }
        .stat-label { color: #888; margin-top: 5px; }
        #statusText { text-align: center; color: #aaa; margin-top: 12px; min-height: 24px; font-size: 14px; }
        #statusText.telegram { color: #00aaff; animation: pulse 1s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
    </style>
</head>
<body>
    <h1>📦 TG Cloud</h1>
    <p style="color:#888">Free unlimited storage powered by Telegram</p>
    
    <div class="stats">
        <div class="stat"><div class="stat-value" id="fileCount">-</div><div class="stat-label">Files</div></div>
        <div class="stat"><div class="stat-value" id="totalSize">-</div><div class="stat-label">Total Size</div></div>
    </div>
    
    <div class="upload-zone" id="dropZone">
        <input type="file" id="fileInput" multiple>
        <p>📁 Drop files here or click to upload</p>
        <p style="color:#666;font-size:14px">Files over 1.9GB are automatically split</p>
    </div>
    
    <div class="progress" id="progressContainer">
        <div class="progress-bar" id="progressBar"></div>
        <div class="progress-text" id="progressPercent">0%</div>
    </div>
    <div id="statusText"></div>
    <div class="status" id="status"></div>
    <div class="file-list" id="fileList"></div>

<script>
const CHUNK_SIZE = 1900 * 1024 * 1024;
const $ = id => document.getElementById(id);

$('dropZone').onclick = () => $('fileInput').click();
$('dropZone').ondragover = e => { e.preventDefault(); $('dropZone').classList.add('dragover'); };
$('dropZone').ondragleave = () => $('dropZone').classList.remove('dragover');
$('dropZone').ondrop = e => { e.preventDefault(); $('dropZone').classList.remove('dragover'); handleFiles(e.dataTransfer.files); };
$('fileInput').onchange = () => handleFiles($('fileInput').files);

const formatSize = bytes => {
    if (bytes >= 1e12) return (bytes / 1e12).toFixed(2) + ' TB';
    if (bytes >= 1e9) return (bytes / 1e9).toFixed(2) + ' GB';
    if (bytes >= 1e6) return (bytes / 1e6).toFixed(2) + ' MB';
    return (bytes / 1e3).toFixed(2) + ' KB';
};

const formatTime = sec => {
    if (sec < 60) return Math.round(sec) + 's';
    if (sec < 3600) return Math.floor(sec / 60) + 'm ' + Math.round(sec % 60) + 's';
    return Math.floor(sec / 3600) + 'h ' + Math.round((sec % 3600) / 60) + 'm';
};

async function handleFiles(files) {
    for (const file of files) await uploadFile(file);
    loadFiles();
}

async function uploadFile(file) {
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
    const uploadId = crypto.randomUUID();
    let startTime = Date.now();
    
    $('progressContainer').style.display = 'block';
    $('progressBar').style.width = '0%';
    $('progressPercent').textContent = '0%';
    
    try {
        for (let i = 0; i < totalChunks; i++) {
            const start = i * CHUNK_SIZE;
            const end = Math.min(start + CHUNK_SIZE, file.size);
            const chunk = file.slice(start, end);
            
            // Phase 1: Upload to Railway
            await new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                const formData = new FormData();
                formData.append('chunk', chunk);
                formData.append('upload_id', uploadId);
                formData.append('chunk_index', i);
                formData.append('total_chunks', totalChunks);
                formData.append('filename', file.name);
                formData.append('total_size', file.size);
                
                let tgInterval = null;
                let fakeProgress = 0;
                
                xhr.upload.onprogress = e => {
                    if (e.lengthComputable) {
                        $('statusText').className = '';
                        const chunkProgress = e.loaded / e.total;
                        const overallProgress = (i + chunkProgress * 0.5) / totalChunks;
                        const pct = (overallProgress * 100).toFixed(1);
                        $('progressBar').style.width = pct + '%';
                        $('progressPercent').textContent = pct + '%';
                        
                        const elapsed = (Date.now() - startTime) / 1000;
                        const speed = (i * CHUNK_SIZE + e.loaded) / elapsed;
                        const remaining = (file.size - (i * CHUNK_SIZE + e.loaded)) / speed * 2;
                        $('statusText').textContent = `⬆️ Chunk ${i + 1}/${totalChunks} → Server: ${formatSize(speed)}/s • ~${formatTime(remaining)} left`;
                    }
                };
                
                // When browser→Railway upload completes, start fake progress animation
                xhr.upload.onload = () => {
                    const baseProgress = (i + 0.5) / totalChunks * 100;
                    const targetProgress = (i + 0.95) / totalChunks * 100;
                    fakeProgress = baseProgress;
                    
                    $('statusText').className = 'telegram';
                    $('statusText').textContent = `📤 Sending chunk ${i + 1}/${totalChunks} to Telegram...`;
                    
                    tgInterval = setInterval(() => {
                        if (fakeProgress < targetProgress) {
                            fakeProgress += 0.2;
                            $('progressBar').style.width = fakeProgress.toFixed(1) + '%';
                            $('progressPercent').textContent = fakeProgress.toFixed(1) + '%';
                        }
                    }, 300);
                };
                
                xhr.onload = () => {
                    if (tgInterval) clearInterval(tgInterval);
                    if (xhr.status === 200) {
                        resolve(JSON.parse(xhr.response));
                    } else {
                        let errMsg = 'Upload failed';
                        try {
                            const errJson = JSON.parse(xhr.responseText);
                            errMsg = errJson.error || errMsg;
                        } catch(e) {
                            errMsg = xhr.responseText || errMsg;
                        }
                        reject(new Error(errMsg));
                    }
                };
                xhr.onerror = () => {
                    if (tgInterval) clearInterval(tgInterval);
                    reject(new Error('Network error'));
                };
                xhr.open('POST', '/api/upload/chunk');
                xhr.send(formData);
            });
            
            // Update after TG upload complete
            $('statusText').className = '';
            const overallProgress = (i + 1) / totalChunks;
            $('progressBar').style.width = (overallProgress * 100).toFixed(1) + '%';
            $('progressPercent').textContent = (overallProgress * 100).toFixed(1) + '%';
        }
        
        $('statusText').textContent = 'Finalizing...';
        const res = await fetch('/api/upload/finalize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ upload_id: uploadId })
        });
        if (!res.ok) throw new Error(await res.text());
        
        $('progressBar').style.width = '100%';
        $('progressPercent').textContent = '100%';
        showStatus(`✅ Uploaded ${file.name}`, 'success');
    } catch (err) {
        showStatus(`❌ Failed: ${err.message}`, 'error');
    }
    
    $('statusText').textContent = '';
    $('statusText').className = '';
    $('progressContainer').style.display = 'none';
}

function showStatus(msg, type) {
    $('status').textContent = msg;
    $('status').className = 'status ' + type;
    $('status').style.display = 'block';
    setTimeout(() => $('status').style.display = 'none', 5000);
}

async function loadFiles() {
    const files = await (await fetch('/api/files')).json();
    $('fileCount').textContent = files.length;
    $('totalSize').textContent = formatSize(files.reduce((s, f) => s + f.size, 0));
    
    $('fileList').innerHTML = files.map(f => `
        <div class="file">
            <div class="file-info">
                <div class="file-name">${f.filename}</div>
                <div class="file-meta">${formatSize(f.size)} • ${f.chunks} chunk${f.chunks > 1 ? 's' : ''}</div>
            </div>
            <div>
                <button class="btn btn-download" onclick="downloadFile(${f.id}, '${f.filename}', ${f.size}, ${f.chunks})">⬇️ Download</button>
                <button class="btn btn-delete" onclick="deleteFile(${f.id})">🗑️</button>
            </div>
        </div>
    `).join('');
}

async function downloadFile(id, filename, size, numChunks) {
    $('progressContainer').style.display = 'block';
    $('progressBar').style.width = '0%';
    $('progressPercent').textContent = '0%';
    $('statusText').textContent = `⬇️ Fetching ${numChunks} chunk${numChunks > 1 ? 's' : ''} from Telegram...`;
    
    try {
        const res = await fetch(`/api/download/${id}`);
        if (!res.ok) throw new Error('Download failed');
        
        const reader = res.body.getReader();
        const chunks = [];
        let received = 0;
        let startTime = Date.now();
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value);
            received += value.length;
            
            const pct = (received / size * 100).toFixed(1);
            $('progressBar').style.width = pct + '%';
            $('progressPercent').textContent = pct + '%';
            
            const elapsed = (Date.now() - startTime) / 1000;
            const speed = received / elapsed;
            const remaining = (size - received) / speed;
            $('statusText').textContent = `⬇️ ${formatSize(received)} / ${formatSize(size)} • ${formatSize(speed)}/s • ${formatTime(remaining)} left`;
        }
        
        const blob = new Blob(chunks);
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        URL.revokeObjectURL(a.href);
        
        showStatus(`✅ Downloaded ${filename}`, 'success');
    } catch (err) {
        showStatus(`❌ Download failed: ${err.message}`, 'error');
    }
    
    $('statusText').textContent = '';
    $('progressContainer').style.display = 'none';
}

async function deleteFile(id) {
    if (!confirm('Delete this file?')) return;
    await fetch(`/api/delete/${id}`, { method: 'DELETE' });
    loadFiles();
}

loadFiles();
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/files')
def list_files():
    storage = get_storage()
    files = storage.list_files()
    return jsonify([{'id': f[0], 'filename': f[1], 'size': f[2], 'created_at': str(f[3]), 'chunks': f[4]} for f in files])

@app.route('/api/upload/chunk', methods=['POST'])
def upload_chunk():
    upload_id = request.form['upload_id']
    chunk_index = int(request.form['chunk_index'])
    total_chunks = int(request.form['total_chunks'])
    filename = secure_filename(request.form['filename'])
    total_size = int(request.form['total_size'])
    chunk = request.files['chunk']
    
    if upload_id not in uploads_in_progress:
        uploads_in_progress[upload_id] = {'filename': filename, 'total_size': total_size, 'total_chunks': total_chunks, 'tg_chunks': []}
    
    upload = uploads_in_progress[upload_id]
    chunk_path = Path(app.config['UPLOAD_FOLDER']) / f"{upload_id}_{chunk_index}"
    chunk.save(chunk_path)
    chunk_size = chunk_path.stat().st_size
    
    async def send_to_tg():
        storage = get_storage()
        await storage.start()
        try:
            print(f"Uploading chunk {chunk_index + 1}/{total_chunks} to Telegram...")
            msg = await storage.client.send_file(storage.channel_id, chunk_path, caption=f"📦 {filename} | {chunk_index + 1}/{total_chunks} | {upload_id}")
            print(f"Chunk {chunk_index + 1} uploaded successfully, msg_id: {msg.id}")
            return msg.id
        except Exception as e:
            print(f"ERROR uploading to Telegram: {e}")
            raise
        finally:
            await storage.stop()
            if chunk_path.exists(): chunk_path.unlink()
    
    try:
        msg_id = run_async(send_to_tg())
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    upload['tg_chunks'].append((chunk_index, msg_id, chunk_size))
    return jsonify({'status': 'ok', 'chunk': chunk_index + 1, 'total': total_chunks})

@app.route('/api/upload/finalize', methods=['POST'])
def finalize_upload():
    upload_id = request.json['upload_id']
    if upload_id not in uploads_in_progress:
        return jsonify({'error': 'Upload not found'}), 404
    
    upload = uploads_in_progress[upload_id]
    upload['tg_chunks'].sort(key=lambda x: x[0])
    
    storage = get_storage()
    file_id = storage._insert_id("INSERT INTO files (filename, original_size, hash) VALUES (?, ?, ?)", (upload['filename'], upload['total_size'], upload_id))
    for idx, msg_id, size in upload['tg_chunks']:
        storage._q("INSERT INTO chunks (file_id, chunk_index, message_id, size) VALUES (?, ?, ?, ?)", (file_id, idx, msg_id, size))
    
    del uploads_in_progress[upload_id]
    return jsonify({'file_id': file_id})

@app.route('/api/download/<int:file_id>')
def download(file_id):
    storage = get_storage()
    file_info = storage._q("SELECT filename, original_size FROM files WHERE id = ?", (file_id,), fetch='one')
    if not file_info:
        return jsonify({'error': 'File not found'}), 404
    
    filename, original_size = file_info
    chunks = storage._q("SELECT message_id, chunk_index FROM chunks WHERE file_id = ? ORDER BY chunk_index", (file_id,), fetch='all')
    
    def generate():
        loop = asyncio.new_event_loop()
        async def dl():
            s = get_storage()
            await s.start()
            try:
                for msg_id, idx in chunks:
                    msg = await s.client.get_messages(s.channel_id, ids=msg_id)
                    temp = Path(f"/tmp/downloads/dl_{file_id}_{idx}")
                    await s.client.download_media(msg, file=str(temp))
                    with open(temp, 'rb') as f:
                        while data := f.read(1024 * 1024):
                            yield data
                    temp.unlink()
            finally:
                await s.stop()
        
        gen = dl()
        try:
            while True:
                yield loop.run_until_complete(gen.__anext__())
        except StopAsyncIteration:
            pass
        finally:
            loop.close()
    
    return Response(generate(), mimetype='application/octet-stream', headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Content-Length': str(original_size)})

@app.route('/api/delete/<int:file_id>', methods=['DELETE'])
def delete(file_id):
    async def do_del():
        s = get_storage()
        await s.start()
        try:
            await s.delete(file_id)
        finally:
            await s.stop()
    run_async(do_del())
    return jsonify({'deleted': file_id})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
