"""
Telegram Cloud Storage Backend
Splits large files into <2GB chunks, uploads to Telegram, reassembles on download.
Supports SQLite (local) or Postgres (Railway/production).
"""
import os
import hashlib
import asyncio
from pathlib import Path
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeFilename

CHUNK_SIZE = 1900 * 1024 * 1024  # 1.9GB to stay under 2GB limit

class TelegramStorage:
    def __init__(self, api_id=None, api_hash=None, channel_id=None, session_name="tg_cloud", database_url=None):
        self.api_id = int(api_id or os.environ.get('TG_API_ID'))
        self.api_hash = api_hash or os.environ.get('TG_API_HASH')
        self.channel_id = int(channel_id or os.environ.get('TG_CHANNEL_ID'))
        self.database_url = database_url or os.environ.get('DATABASE_URL')
        
        # Use string session if provided (for Railway), otherwise file session
        session_string = os.environ.get('TG_SESSION')
        if session_string:
            self.client = TelegramClient(StringSession(session_string), self.api_id, self.api_hash)
        else:
            self.client = TelegramClient(session_name, self.api_id, self.api_hash)
        
        self._init_db()
    
    def _init_db(self):
        if self.database_url:
            import psycopg2
            self.db = psycopg2.connect(self.database_url)
            self.db.autocommit = True
            self._pg = True
            cur = self.db.cursor()
            cur.execute("""CREATE TABLE IF NOT EXISTS files (
                id SERIAL PRIMARY KEY, filename TEXT, original_size BIGINT,
                hash TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS chunks (
                id SERIAL PRIMARY KEY, file_id INTEGER REFERENCES files(id),
                chunk_index INTEGER, message_id BIGINT, size BIGINT)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS pending_chunks (
                id SERIAL PRIMARY KEY, upload_id TEXT, filename TEXT, total_size BIGINT,
                total_chunks INTEGER, chunk_index INTEGER, message_id BIGINT, chunk_size BIGINT)""")
        else:
            import sqlite3
            self.db = sqlite3.connect("files.db", check_same_thread=False)
            self._pg = False
            self.db.execute("""CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY, filename TEXT, original_size INTEGER,
                hash TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY, file_id INTEGER, chunk_index INTEGER,
                message_id INTEGER, size INTEGER, FOREIGN KEY (file_id) REFERENCES files(id))""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS pending_chunks (
                id INTEGER PRIMARY KEY, upload_id TEXT, filename TEXT, total_size INTEGER,
                total_chunks INTEGER, chunk_index INTEGER, message_id INTEGER, chunk_size INTEGER)""")
            self.db.commit()
    
    def _q(self, query, params=(), fetch=None):
        q = query.replace('?', '%s') if self._pg else query
        if self._pg:
            cur = self.db.cursor()
            cur.execute(q, params)
        else:
            cur = self.db.execute(q, params)
            if not fetch: self.db.commit()
        if fetch == 'one': return cur.fetchone()
        if fetch == 'all': return cur.fetchall()
        return cur
    
    def _insert_id(self, query, params=()):
        if self._pg:
            cur = self.db.cursor()
            cur.execute(query.replace('?', '%s') + ' RETURNING id', params)
            return cur.fetchone()[0]
        cur = self.db.execute(query, params)
        self.db.commit()
        return cur.lastrowid
    
    async def start(self):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise Exception("Telegram session invalid - regenerate TG_SESSION")
        print("Connected to Telegram")
    
    async def stop(self):
        await self.client.disconnect()
    
    def _file_hash(self, filepath):
        h = hashlib.md5()
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
    
    async def upload(self, filepath, progress_callback=None):
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"{filepath} not found")
        
        file_size = filepath.stat().st_size
        file_hash = self._file_hash(filepath)
        
        # Check if already uploaded
        existing = self._q("SELECT id FROM files WHERE hash = ?", (file_hash,), fetch='one')
        if existing:
            print(f"File already uploaded (id: {existing[0]})")
            return existing[0]
        
        # Create file record
        file_id = self._insert_id(
            "INSERT INTO files (filename, original_size, hash) VALUES (?, ?, ?)",
            (filepath.name, file_size, file_hash)
        )
        
        # Split and upload chunks
        chunk_index = 0
        uploaded = 0
        
        with open(filepath, 'rb') as f:
            while True:
                chunk_data = f.read(CHUNK_SIZE)
                if not chunk_data:
                    break
                
                # Write chunk to temp file
                chunk_name = f"{filepath.stem}_chunk{chunk_index}{filepath.suffix}"
                chunk_path = Path(f"/tmp/{chunk_name}")
                chunk_path.write_bytes(chunk_data)
                
                # Upload to Telegram
                msg = await self.client.send_file(
                    self.channel_id,
                    chunk_path,
                    caption=f"📦 {filepath.name} | chunk {chunk_index} | file_id:{file_id}",
                    attributes=[DocumentAttributeFilename(chunk_name)]
                )
                
                # Save chunk record
                self._q(
                    "INSERT INTO chunks (file_id, chunk_index, message_id, size) VALUES (?, ?, ?, ?)",
                    (file_id, chunk_index, msg.id, len(chunk_data))
                )
                
                chunk_path.unlink()  # Clean up temp file
                
                uploaded += len(chunk_data)
                if progress_callback:
                    progress_callback(uploaded, file_size)
                
                chunk_index += 1
                print(f"Uploaded chunk {chunk_index} ({uploaded / 1024 / 1024:.1f} MB / {file_size / 1024 / 1024:.1f} MB)")
        
        print(f"✅ Upload complete: {filepath.name} ({chunk_index} chunks)")
        return file_id
    
    async def download(self, file_id, output_dir=".", progress_callback=None):
        output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True)
        
        # Get file info
        file_info = self._q("SELECT filename, original_size FROM files WHERE id = ?", (file_id,), fetch='one')
        if not file_info:
            raise ValueError(f"File {file_id} not found")
        
        filename, original_size = file_info
        output_path = output_dir / filename
        
        # Get chunks
        chunks = self._q(
            "SELECT message_id, chunk_index, size FROM chunks WHERE file_id = ? ORDER BY chunk_index",
            (file_id,), fetch='all'
        )
        
        if not chunks:
            raise ValueError(f"No chunks found for file {file_id}")
        
        # Download and reassemble
        downloaded = 0
        with open(output_path, 'wb') as out:
            for msg_id, idx, size in chunks:
                msg = await self.client.get_messages(self.channel_id, ids=msg_id)
                chunk_path = await self.client.download_media(msg, file=f"/tmp/chunk_{idx}")
                
                with open(chunk_path, 'rb') as chunk_file:
                    out.write(chunk_file.read())
                
                Path(chunk_path).unlink()  # Clean up
                
                downloaded += size
                if progress_callback:
                    progress_callback(downloaded, original_size)
                print(f"Downloaded chunk {idx + 1}/{len(chunks)} ({downloaded / 1024 / 1024:.1f} MB)")
        
        print(f"✅ Download complete: {output_path}")
        return output_path
    
    def list_files(self):
        return self._q("""
            SELECT f.id, f.filename, f.original_size, f.created_at, COUNT(c.id) as chunks
            FROM files f LEFT JOIN chunks c ON f.id = c.file_id
            GROUP BY f.id, f.filename, f.original_size, f.created_at ORDER BY f.created_at DESC
        """, fetch='all')
    
    async def delete(self, file_id):
        chunks = self._q("SELECT message_id FROM chunks WHERE file_id = ?", (file_id,), fetch='all')
        
        for (msg_id,) in chunks:
            await self.client.delete_messages(self.channel_id, msg_id)
        
        self._q("DELETE FROM chunks WHERE file_id = ?", (file_id,))
        self._q("DELETE FROM files WHERE id = ?", (file_id,))
        print(f"Deleted file {file_id}")
