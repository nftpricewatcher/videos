"""
Telegram Cloud Storage Backend
Splits large files into <2GB chunks, uploads to Telegram, reassembles on download.
"""
import os
import sqlite3
import hashlib
import asyncio
from pathlib import Path
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeFilename

CHUNK_SIZE = 1900 * 1024 * 1024  # 1.9GB to stay under 2GB limit

class TelegramStorage:
    def __init__(self, api_id, api_hash, channel_id, session_name="tg_cloud"):
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel_id = int(channel_id)
        self.client = TelegramClient(session_name, api_id, api_hash)
        self.db = sqlite3.connect("files.db", check_same_thread=False)
        self._init_db()
    
    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY,
                filename TEXT,
                original_size INTEGER,
                hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                file_id INTEGER,
                chunk_index INTEGER,
                message_id INTEGER,
                size INTEGER,
                FOREIGN KEY (file_id) REFERENCES files(id)
            )
        """)
        self.db.commit()
    
    async def start(self):
        await self.client.start()
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
        existing = self.db.execute(
            "SELECT id FROM files WHERE hash = ?", (file_hash,)
        ).fetchone()
        if existing:
            print(f"File already uploaded (id: {existing[0]})")
            return existing[0]
        
        # Create file record
        cursor = self.db.execute(
            "INSERT INTO files (filename, original_size, hash) VALUES (?, ?, ?)",
            (filepath.name, file_size, file_hash)
        )
        file_id = cursor.lastrowid
        self.db.commit()
        
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
                self.db.execute(
                    "INSERT INTO chunks (file_id, chunk_index, message_id, size) VALUES (?, ?, ?, ?)",
                    (file_id, chunk_index, msg.id, len(chunk_data))
                )
                self.db.commit()
                
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
        file_info = self.db.execute(
            "SELECT filename, original_size FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        if not file_info:
            raise ValueError(f"File {file_id} not found")
        
        filename, original_size = file_info
        output_path = output_dir / filename
        
        # Get chunks
        chunks = self.db.execute(
            "SELECT message_id, chunk_index, size FROM chunks WHERE file_id = ? ORDER BY chunk_index",
            (file_id,)
        ).fetchall()
        
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
        return self.db.execute("""
            SELECT f.id, f.filename, f.original_size, f.created_at, COUNT(c.id) as chunks
            FROM files f LEFT JOIN chunks c ON f.id = c.file_id
            GROUP BY f.id ORDER BY f.created_at DESC
        """).fetchall()
    
    async def delete(self, file_id):
        chunks = self.db.execute(
            "SELECT message_id FROM chunks WHERE file_id = ?", (file_id,)
        ).fetchall()
        
        for (msg_id,) in chunks:
            await self.client.delete_messages(self.channel_id, msg_id)
        
        self.db.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
        self.db.execute("DELETE FROM files WHERE id = ?", (file_id,))
        self.db.commit()
        print(f"Deleted file {file_id}")
