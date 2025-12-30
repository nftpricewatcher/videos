"""
Flask API + Web Interface for Telegram Cloud Storage
"""
import os
import asyncio
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string
from werkzeug.utils import secure_filename
from tg_storage import TelegramStorage

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 * 1024  # 50GB max
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'

Path(app.config['UPLOAD_FOLDER']).mkdir(exist_ok=True)

# Initialize storage (set these in environment)
storage = TelegramStorage(
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
        .progress { height: 20px; background: #222; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
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
        .stats { display: flex; gap: 20px; margin: 20px 0; }
        .stat { background: #1a1a1a; padding: 20px; border-radius: 8px; flex: 1; text-align: center; }
        .stat-value { font-size: 28px; font-weight: 700; color: #0088cc; }
        .stat-label { color: #888; margin-top: 5px; }
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
        <p style="color:#666;font-size:14px">No size limit - files are automatically chunked</p>
    </div>
    
    <div class="progress" id="progressContainer">
        <div class="progress-bar" id="progressBar"></div>
    </div>
    <div id="progressText" style="text-align:center;color:#888"></div>
    
    <div class="status" id="status"></div>
    
    <div class="file-list" id="fileList"></div>

<script>
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const progressContainer = document.getElementById('progressContainer');
const progressBar = document.getElementById('progressBar');
const progressText = document.getElementById('progressText');
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
        await uploadFile(file);
    }
    loadFiles();
}

async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    
    progressContainer.style.display = 'block';
    progressBar.style.width = '0%';
    progressText.textContent = `Uploading ${file.name}...`;
    
    try {
        const xhr = new XMLHttpRequest();
        xhr.upload.onprogress = e => {
            if (e.lengthComputable) {
                const pct = (e.loaded / e.total * 100).toFixed(1);
                progressBar.style.width = pct + '%';
                progressText.textContent = `Uploading ${file.name}: ${pct}% (${formatSize(e.loaded)} / ${formatSize(e.total)})`;
            }
        };
        
        await new Promise((resolve, reject) => {
            xhr.onload = () => xhr.status === 200 ? resolve(JSON.parse(xhr.response)) : reject(xhr.response);
            xhr.onerror = reject;
            xhr.open('POST', '/api/upload');
            xhr.send(formData);
        });
        
        showStatus(`✅ Uploaded ${file.name}`, 'success');
    } catch (err) {
        showStatus(`❌ Failed to upload ${file.name}: ${err}`, 'error');
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
                <button class="btn btn-download" onclick="downloadFile(${f.id}, '${f.filename}')">⬇️ Download</button>
                <button class="btn btn-delete" onclick="deleteFile(${f.id})">🗑️ Delete</button>
            </div>
        </div>
    `).join('');
}

async function downloadFile(id, filename) {
    showStatus(`⏳ Preparing download for ${filename}...`, 'success');
    window.location.href = `/api/download/${id}`;
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
    files = storage.list_files()
    return jsonify([{
        'id': f[0], 'filename': f[1], 'size': f[2], 
        'created_at': f[3], 'chunks': f[4]
    } for f in files])

@app.route('/api/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file'}), 400
    
    file = request.files['file']
    filename = secure_filename(file.filename)
    filepath = Path(app.config['UPLOAD_FOLDER']) / filename
    file.save(filepath)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(storage.start())
        file_id = loop.run_until_complete(storage.upload(filepath))
    finally:
        loop.run_until_complete(storage.stop())
        filepath.unlink()  # Clean up
    
    return jsonify({'id': file_id, 'filename': filename})

@app.route('/api/download/<int:file_id>')
def download(file_id):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(storage.start())
        output_path = loop.run_until_complete(storage.download(file_id, '/tmp/downloads'))
    finally:
        loop.run_until_complete(storage.stop())
    
    return send_file(output_path, as_attachment=True)

@app.route('/api/delete/<int:file_id>', methods=['DELETE'])
def delete(file_id):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(storage.start())
        loop.run_until_complete(storage.delete(file_id))
    finally:
        loop.run_until_complete(storage.stop())
    
    return jsonify({'deleted': file_id})

if __name__ == '__main__':
    Path('/tmp/downloads').mkdir(exist_ok=True)
    app.run(host='0.0.0.0', port=5000, debug=True)
