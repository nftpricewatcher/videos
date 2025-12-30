#!/usr/bin/env python3
"""
TG Cloud CLI - Bulk upload/download for video libraries
"""
import os
import sys
import asyncio
import argparse
from pathlib import Path
from tg_storage import TelegramStorage

async def main():
    parser = argparse.ArgumentParser(description='TG Cloud - Telegram Storage CLI')
    parser.add_argument('command', choices=['upload', 'download', 'list', 'delete', 'bulk-upload'])
    parser.add_argument('--file', '-f', help='File path for upload/download')
    parser.add_argument('--id', type=int, help='File ID for download/delete')
    parser.add_argument('--dir', '-d', help='Directory for bulk upload')
    parser.add_argument('--output', '-o', default='.', help='Output directory for download')
    parser.add_argument('--extensions', '-e', default='.mp4,.mov,.avi,.mkv,.wmv,.m4v', 
                       help='File extensions for bulk upload (comma-separated)')
    args = parser.parse_args()
    
    storage = TelegramStorage(
        api_id=os.environ.get('TG_API_ID'),
        api_hash=os.environ.get('TG_API_HASH'),
        channel_id=os.environ.get('TG_CHANNEL_ID')
    )
    
    await storage.start()
    
    try:
        if args.command == 'list':
            files = storage.list_files()
            if not files:
                print("No files stored yet")
                return
            print(f"\n{'ID':<6} {'Filename':<40} {'Size':<12} {'Chunks':<8} {'Date'}")
            print("-" * 90)
            for f in files:
                size_gb = f[2] / (1024**3)
                print(f"{f[0]:<6} {f[1][:38]:<40} {size_gb:.2f} GB    {f[4]:<8} {f[3][:10]}")
            total = sum(f[2] for f in files) / (1024**3)
            print(f"\nTotal: {len(files)} files, {total:.2f} GB")
        
        elif args.command == 'upload':
            if not args.file:
                print("Error: --file required")
                return
            await storage.upload(args.file)
        
        elif args.command == 'download':
            if not args.id:
                print("Error: --id required")
                return
            await storage.download(args.id, args.output)
        
        elif args.command == 'delete':
            if not args.id:
                print("Error: --id required")
                return
            await storage.delete(args.id)
        
        elif args.command == 'bulk-upload':
            if not args.dir:
                print("Error: --dir required")
                return
            
            extensions = tuple(args.extensions.split(','))
            dir_path = Path(args.dir)
            
            # Find all video files
            videos = []
            for ext in extensions:
                videos.extend(dir_path.rglob(f'*{ext}'))
                videos.extend(dir_path.rglob(f'*{ext.upper()}'))
            
            videos = sorted(set(videos))
            total_size = sum(v.stat().st_size for v in videos)
            
            print(f"\n📁 Found {len(videos)} videos ({total_size / (1024**3):.2f} GB)")
            print("-" * 50)
            
            for i, video in enumerate(videos, 1):
                size = video.stat().st_size / (1024**3)
                print(f"\n[{i}/{len(videos)}] {video.name} ({size:.2f} GB)")
                try:
                    await storage.upload(str(video))
                except Exception as e:
                    print(f"❌ Error: {e}")
                    continue
            
            print(f"\n✅ Bulk upload complete!")
    
    finally:
        await storage.stop()

if __name__ == '__main__':
    asyncio.run(main())
