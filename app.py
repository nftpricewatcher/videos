"""
Flask API + Web Interface for Telegram Cloud Storage
Supports large files via browser-side chunking
"""
import os
import asyncio
import threading
import uuid
import hashlib
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string, Response
from werkzeug.utils import secure_filename
from tg_storage import TelegramStorage

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB per chunk max
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'

Path(app.config['UPLOAD_FOLDER']).mkdir(exist_ok=True)
Path('/tmp/downloads').mkdir(exist_ok=True)

# Track ongoing uploads: upload_id -> {filename, chunks: {index: path}, total_chunks}
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
            border-radius: 12px; margin: 20px 0; cursor: pointer;
            transition: all 0.3s;
        }
        .upload-zone:hover, .upload-zone.dragover { background: #0088cc22; border-color: #00aaff; }
        .upload-zone input { display: none; }
        .progress { height: 24px; background: #222; border-radius: 12px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar { height: 100%; background: linear-gradient(90deg, #0088cc, #00aaff); width: 0%; transition: width 0.3s; }
        .file-list { margin-top: 30px; }
        .file { 
            display: flex; justify-content: space-between; align-items: center;
            padding: 15px; background: #1a1a1a; border-radius: 8px; margin: 10px 0;
        }
        .file-info { flex: 1; }
        .file-name { font-weight: 600; color: #fff; }
        .file-meta { color: #888; font-size: 14px; margin-top: 4px; }
        .btn { 
            padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer;
            font-weight: 600; transition: all 0.2s;
        }
        .btn-download { background: #0088cc; color: #fff; margin-right: 8px; }
        .btn-download:hover { background: #00aaff; }
        .btn-delete { background: #ff4444; color: #fff; }
        .btn-delete:hover { background: #ff6666; }
        .status { padding: 15px; border-radius: 8px; margin: 10px 0; display: none; }
        .status.success { background: #00aa0022; border: 1px solid #00aa00; color: #00cc00; }
        .status.error { background: #ff000022; border: 1px solid #ff0000; color: #ff4444; }
        .status.info { background: #0088cc22; border: 1px solid #0088cc; color: #00aaff; }
        .stats { display: flex; gap: 20px; margin: 20px 0; }
        .stat { background: #1a1a1a; padding: 20px; border-radius: 8px; flex: 1; text-align: center; }
        .stat-value { font-size: 28px; font-weight: 700; color: #0088cc; }
        .stat-label { color: #888; margin-top: 5px; }
        .upload-status { font-size: 14px; color: #888; margin-top: 8px; }
    </style>
</head>
<body>
    <h1>📦 TG Cloud</h1>
    <p style="color:#888">Free unlimited storage powered by Telegram</p>
    
    <div class="stats">
        <div class="stat">
            <div class="stat-value" id="fileCount">-</div>
            <div class="stat-label">Files</div>
        </div>
        <div class="stat">
            <div class="stat-value" id="totalSize">-</div>
            <div class="stat-label">Total Size</div>
        </div>
    </div>
    
    <div class="upload-zone" id="dropZone">
        <input type="file" id="fileInput" multiple>
        <p>📁 Drop files here or click to upload</p>
        <p style="color:#666;font-size:14px">Supports files up to 20GB+ via automatic chunking</p>
    </div>
    
    <div class="progress" id="progressContainer">
        <div class="progress-bar" id="progressBar"></div>
    </div>
    <div id="progressText" style="text-align:center;color:#888"></div>
    <div id="uploadStatus" class="upload-status" style="text-align:center"></div>
    
    <div class="status" id="status"></div>
    
    <div class="file-list" id="fileList"></div>

<script>
const CHUNK_SIZE = 500 * 1024 * 1024; // 500MB chunks to browser

const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const progressContainer = document.getElementById('progressContainer');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
const uploadStatus = document.getElementById('uploadStatus');
const status = document.getElementById('status');
const fileList = document.getElementById('fileList');

dropZone.onclick = () => fileInput.click();
dropZone.ondragover = e => { e.preventDefault(); dropZone.classList.add('dragover'); };
dropZone.ondragleave = () => dropZone.classList.remove('dragover');
dropZone.ondrop = e => { e.preventDefault(); dropZone.classList.remove('dragover'); handleFiles(e.dataTransfer.files); };
fileInput.onchange = () => handleFiles(fileInput.files);

function formatSize(bytes) {
    if (bytes >= 1e12) return (bytes / 1e12).toFixed(2) + ' TB';
    if (bytes >= 1e9) return (bytes / 1e9).toFixed(2) + ' GB';
    if (bytes >= 1e6) return (bytes / 1e6).toFixed(2) + ' MB';
    return (bytes / 1e3).toFixed(2) + ' KB';
}

async function handleFiles(files) {
    for (const file of files) {
        await uploadFileChunked(file);
    }
    loadFiles();
}

async function uploadFileChunked(file) {
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
    const uploadId = crypto.randomUUID();
    
    progressContainer.style.display = 'block';
    progressBar.style.width = '0%';
    
    try {
        // Upload each chunk
        for (let i = 0; i < totalChunks; i++) {
            const start = i * CHUNK_SIZE;
            const end = Math.min(start + CHUNK_SIZE, file.size);
            const chunk = file.slice(start, end);
            
            const formData = new FormData();
            formData.append('chunk', chunk);
            formData.append('upload_id', uploadId);
            formData.append('chunk_index', i);
            formData.append('total_chunks', totalChunks);
            formData.append('filename', file.name);
            formData.append('total_size', file.size);
            
            uploadStatus.textContent = `Uploading chunk ${i + 1}/${totalChunks} to server...`;
            
            const response = await fetch('/api/upload/chunk', {
                method: 'POST',
                body: formData
            });
            
            if (!response.ok) {
                const err = await response.text();
                throw new Error(err);
            }
            
            const result = await response.json();
            
            // Update progress
            const overallProgress = ((i + 1) / totalChunks * 100).toFixed(1);
            progressBar.style.width = overallProgress + '%';
            progressText.textContent = `${file.name}: ${overallProgress}% (${formatSize(end)} / ${formatSize(file.size)})`;
            
            if (result.status === 'processing') {
                uploadStatus.textContent = `Processing: sending chunk ${result.chunks_sent || 0} to Telegram...`;
            }
        }
        
        // Finalize upload
        uploadStatus.textContent = 'Finalizing upload...';
        const finalResponse = await fetch('/api/upload/finalize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ upload_id: uploadId })
        });
        
        if (!finalResponse.ok) throw new Error(await finalResponse.text());
        
        showStatus(`✅ Uploaded ${file.name}`, 'success');
        uploadStatus.textContent = '';
        
    } catch (err) {
        showStatus(`❌ Failed: ${err.message}`, 'error');
        uploadStatus.textContent = '';
    }
    
    progressContainer.style.display = 'none';
}

function showStatus(msg, type) {
    status.textContent = msg;
    status.className = 'status ' + type;
    status.style.display = 'block';
    setTimeout(() => status.style.display = 'none', 5000);
}

async function loadFiles() {
    const res = await fetch('/api/files');
    const files = await res.json();
    
    let totalSize = files.reduce((sum, f) => sum + f.size, 0);
    document.getElementById('fileCount').textContent = files.length;
    document.getElementById('totalSize').textContent = formatSize(totalSize);
    
    fileList.innerHTML = files.map(f => `
        <div class="file">
            <div class="file-info">
                <div class="file-name">${f.filename}</div>
                <div class="file-meta">${formatSize(f.size)} • ${f.chunks} chunks • ${new Date(f.created_at).toLocaleDateString()}</div>
            </div>
            <div>
                <button class="btn btn-download" onclick="downloadFile(${f.id}, '${f.filename}', ${f.size})">⬇️ Download</button>
                <button class="btn btn-delete" onclick="deleteFile(${f.id})">🗑️ Delete</button>
            </div>
        </div>
    `).join('');
}

async function downloadFile(id, filename, size) {
    progressContainer.style.display = 'block';
    progressBar.style.width = '0%';
    progressText.textContent = `Preparing download for ${filename}...`;
    uploadStatus.textContent = 'Fetching from Telegram...';
    
    try {
        const response = await fetch(`/api/download/${id}`);
        if (!response.ok) throw new Error('Download failed');
        
        const reader = response.body.getReader();
        const chunks = [];
        let received = 0;
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value);
            received += value.length;
            const pct = (received / size * 100).toFixed(1);
            progressBar.style.width = pct + '%';
            progressText.textContent = `Downloading ${filename}: ${pct}% (${formatSize(received)} / ${formatSize(size)})`;
        }
        
        const blob = new Blob(chunks);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
        
        showStatus(`✅ Downloaded ${filename}`, 'success');
    } catch (err) {
        showStatus(`❌ Download failed: ${err.message}`, 'error');
    }
    
    progressContainer.style.display = 'none';
    uploadStatus.textContent = '';
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
    return jsonify([{
        'id': f[0], 'filename': f[1], 'size': f[2], 
        'created_at': str(f[3]), 'chunks': f[4]
    } for f in files])

@app.route('/api/upload/chunk', methods=['POST'])
def upload_chunk():
    """Receive a chunk from browser, immediately send to Telegram"""
    upload_id = request.form['upload_id']
    chunk_index = int(request.form['chunk_index'])
    total_chunks = int(request.form['total_chunks'])
    filename = secure_filename(request.form['filename'])
    total_size = int(request.form['total_size'])
    chunk = request.files['chunk']
    
    # Initialize upload tracking
    if upload_id not in uploads_in_progress:
        uploads_in_progress[upload_id] = {
            'filename': filename,
            'total_size': total_size,
            'total_chunks': total_chunks,
            'tg_chunks': [],  # List of telegram message IDs
            'file_id': None
        }
    
    upload = uploads_in_progress[upload_id]
    
    # Save chunk temporarily
    chunk_path = Path(app.config['UPLOAD_FOLDER']) / f"{upload_id}_{chunk_index}"
    chunk.save(chunk_path)
    
    # Send this chunk to Telegram immediately
    async def send_chunk_to_telegram():
        storage = get_storage()
        await storage.start()
        try:
            msg = await storage.client.send_file(
                storage.channel_id,
                chunk_path,
                caption=f"📦 {filename} | chunk {chunk_index}/{total_chunks} | upload:{upload_id}"
            )
            return msg.id
        finally:
            await storage.stop()
            chunk_path.unlink()
    
    msg_id = run_async(send_chunk_to_telegram())
    upload['tg_chunks'].append((chunk_index, msg_id, chunk_path.stat().st_size if chunk_path.exists() else 0))
    
    return jsonify({
        'status': 'processing' if chunk_index < total_chunks - 1 else 'complete',
        'chunks_sent': len(upload['tg_chunks'])
    })

@app.route('/api/upload/finalize', methods=['POST'])
def finalize_upload():
    """Create database entry after all chunks uploaded"""
    data = request.json
    upload_id = data['upload_id']
    
    if upload_id not in uploads_in_progress:
        return jsonify({'error': 'Upload not found'}), 404
    
    upload = uploads_in_progress[upload_id]
    
    # Sort chunks by index
    upload['tg_chunks'].sort(key=lambda x: x[0])
    
    # Create database entry
    storage = get_storage()
    
    # Insert file record
    file_id = storage._insert_id(
        "INSERT INTO files (filename, original_size, hash) VALUES (?, ?, ?)",
        (upload['filename'], upload['total_size'], upload_id)
    )
    
    # Insert chunk records
    for idx, (chunk_idx, msg_id, size) in enumerate(upload['tg_chunks']):
        storage._q(
            "INSERT INTO chunks (file_id, chunk_index, message_id, size) VALUES (?, ?, ?, ?)",
            (file_id, chunk_idx, msg_id, size)
        )
    
    del uploads_in_progress[upload_id]
    
    return jsonify({'file_id': file_id, 'filename': upload['filename']})

@app.route('/api/download/<int:file_id>')
def download(file_id):
    """Stream download - fetch chunks from Telegram and stream to browser"""
    storage = get_storage()
    
    file_info = storage._q("SELECT filename, original_size FROM files WHERE id = ?", (file_id,), fetch='one')
    if not file_info:
        return jsonify({'error': 'File not found'}), 404
    
    filename, original_size = file_info
    chunks = storage._q(
        "SELECT message_id, chunk_index FROM chunks WHERE file_id = ? ORDER BY chunk_index",
        (file_id,), fetch='all'
    )
    
    def generate():
        async def stream_chunks():
            s = get_storage()
            await s.start()
            try:
                for msg_id, idx in chunks:
                    msg = await s.client.get_messages(s.channel_id, ids=msg_id)
                    # Download to temp file
                    temp_path = f"/tmp/downloads/chunk_{file_id}_{idx}"
                    await s.client.download_media(msg, file=temp_path)
                    
                    # Read and yield
                    with open(temp_path, 'rb') as f:
                        while True:
                            data = f.read(8192)
                            if not data:
                                break
                            yield data
                    
                    Path(temp_path).unlink()
            finally:
                await s.stop()
        
        # Run async generator
        loop = asyncio.new_event_loop()
        gen = stream_chunks()
        try:
            while True:
                chunk = loop.run_until_complete(gen.__anext__())
                yield chunk
        except StopAsyncIteration:
            pass
        finally:
            loop.close()
    
    return Response(
        generate(),
        mimetype='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )

@app.route('/api/delete/<int:file_id>', methods=['DELETE'])
def delete(file_id):
    async def do_delete():
        storage = get_storage()
        await storage.start()
        try:
            await storage.delete(file_id)
        finally:
            await storage.stop()
    
    run_async(do_delete())
    return jsonify({'deleted': file_id})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
