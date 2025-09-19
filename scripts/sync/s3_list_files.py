#!/usr/bin/env python3
"""
Simple S3 file lister for any bucket path.
Lists files with proper sorting without loading all files into memory.
"""

import sys
import argparse
import logging
from pathlib import Path
from typing import List, Dict
from datetime import datetime

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Import from project
from src.bomia.config_manager import ConfigManager

# Configure logging
logging.basicConfig(level=logging.WARNING)  # Reduce noise
logger = logging.getLogger(__name__)


def get_s3_client(config):
    """Get S3 client instance"""
    import boto3
    
    endpoint_url = f"https://{config.get('s3.endpoint')}"
    access_key = config.get('s3.access_key')
    secret_key = config.get('s3.secret_key')
    region = config.get('s3.region')
    
    return boto3.client(
        's3',
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region
    )


def list_files_head_tail(s3_client, bucket: str, prefix: str, limit: int, order: str, sort_by: str) -> List[Dict]:
    """
    List first/last N files efficiently 
    """
    print(f"⚠️  Warning: For large folders (200k+ files), this may take time when sorting by modified time or desc name order")
    
    files = []
    
    try:
        # Strategy: Always get full list for accurate sorting, but optimize where possible
        if sort_by == 'name' and order == 'asc':
            # This is the ONLY truly fast case - S3 returns lexicographically sorted
            response = s3_client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                MaxKeys=limit
            )
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    if not obj['Key'].endswith('/'):  # Skip directories
                        files.append({
                            'key': obj['Key'],
                            'filename': obj['Key'].split('/')[-1],
                            'size': obj['Size'],
                            'last_modified': obj['LastModified'],
                            'last_modified_str': obj['LastModified'].strftime('%Y-%m-%d %H:%M:%S UTC')
                        })
            return files
        
        else:
            # For all other cases, we need the full list to sort properly
            print("Scanning all files for accurate sorting...")
            paginator = s3_client.get_paginator('list_objects_v2')
            all_files = []
            
            page_count = 0
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                page_count += 1
                if page_count % 10 == 0:
                    print(f"  Scanned {page_count} pages, found {len(all_files)} files...")
                    
                if 'Contents' in page:
                    for obj in page['Contents']:
                        if not obj['Key'].endswith('/'):  # Skip directories
                            all_files.append({
                                'key': obj['Key'],
                                'filename': obj['Key'].split('/')[-1],
                                'size': obj['Size'],
                                'last_modified': obj['LastModified'],
                                'last_modified_str': obj['LastModified'].strftime('%Y-%m-%d %H:%M:%S UTC')
                            })
            
            print(f"Found {len(all_files)} total files, sorting and taking top {limit}...")
            
            # Sort based on criteria
            if sort_by == 'name':
                all_files.sort(key=lambda x: x['filename'], reverse=(order == 'desc'))
            else:  # sort_by == 'modified'
                all_files.sort(key=lambda x: x['last_modified'], reverse=(order == 'desc'))
            
            return all_files[:limit]
        
    except Exception as e:
        print(f"Error listing files: {e}")
        return []


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"


def main():
    parser = argparse.ArgumentParser(description="List files in any S3 path")
    parser.add_argument('path', help='S3 path (e.g., bomia-engine/data/carbonizacao-1/raw-frames/)')
    parser.add_argument('--limit', type=int, default=10, help='Number of files to show (default: 10)')
    parser.add_argument('--order', choices=['asc', 'desc'], default='desc', help='Sort order (default: desc)')
    parser.add_argument('--sort-by', choices=['name', 'modified'], default='name', help='Sort by filename or last modified (default: name)')
    
    args = parser.parse_args()
    
    # Clean up the path
    s3_path = args.path.strip('/')
    
    # Initialize config (use any project, we just need S3 credentials)
    config = ConfigManager("carbonizacao-1")  # Just for S3 config
    bucket = config.get('s3.bucket')
    
    # Get S3 client
    s3_client = get_s3_client(config)
    
    print(f"Listing files from s3://{bucket}/{s3_path}")
    print(f"Sort by: {args.sort_by}, Order: {args.order}, Limit: {args.limit}")
    print("-" * 100)
    
    # List files
    files = list_files_head_tail(s3_client, bucket, s3_path, args.limit, args.order, args.sort_by)
    
    if not files:
        print("No files found")
        return
    
    # Display results
    for i, file_info in enumerate(files, 1):
        size_str = format_file_size(file_info['size'])
        print(f"{i:2d}. {file_info['filename']:<50} {size_str:>10} {file_info['last_modified_str']}")
    
    print("-" * 100)
    print(f"Total: {len(files)} files")


if __name__ == '__main__':
    main()