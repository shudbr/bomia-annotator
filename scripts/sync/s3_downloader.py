#!/usr/bin/env python3
"""
Multithreaded S3 file downloader for Bomia Engine.
Downloads files from S3 to local filesystem with parallel processing.
"""

import os
import sys
import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import threading

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent.parent))

# Import from project
from src.bomia.config_manager import ConfigManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/s3_download.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Thread-local storage for S3 client instances
thread_local = threading.local()

# Progress tracking
class ProgressTracker:
    def __init__(self, total_files: int):
        self.total_files = total_files
        self.downloaded = 0
        self.failed = 0
        self.skipped = 0
        self.lock = threading.Lock()
        self.last_update_time = time.time()
        self.start_time = time.time()
    
    def update(self, status: str):
        with self.lock:
            if status == 'downloaded':
                self.downloaded += 1
            elif status == 'failed':
                self.failed += 1
            elif status == 'skipped':
                self.skipped += 1
            
            current_time = time.time()
            if current_time - self.last_update_time >= 1.0:  # Update display every second
                self.display_progress()
                self.last_update_time = current_time
    
    def display_progress(self):
        processed = self.downloaded + self.failed + self.skipped
        if processed == 0:
            return
            
        elapsed = time.time() - self.start_time
        files_per_second = processed / elapsed if elapsed > 0 else 0
        
        percent = (processed / self.total_files) * 100 if self.total_files > 0 else 0
        
        # Calculate ETA
        if files_per_second > 0:
            remaining_files = self.total_files - processed
            eta_seconds = remaining_files / files_per_second
            eta_min = int(eta_seconds // 60)
            eta_sec = int(eta_seconds % 60)
            eta = f"{eta_min:02d}:{eta_sec:02d}"
        else:
            eta = "Unknown"
        
        print(f"\rProgress: {processed}/{self.total_files} ({percent:.1f}%) - "
              f"Downloaded: {self.downloaded}, Failed: {self.failed}, Skipped: {self.skipped} - "
              f"Speed: {files_per_second:.1f} files/sec - ETA: {eta}", end="")
        sys.stdout.flush()
    
    def get_summary(self) -> Dict:
        elapsed = time.time() - self.start_time
        speed = (self.downloaded + self.skipped) / elapsed if elapsed > 0 else 0
        
        return {
            'downloaded': self.downloaded,
            'failed': self.failed,
            'skipped': self.skipped,
            'total': self.total_files,
            'elapsed_seconds': elapsed,
            'files_per_second': speed
        }


def get_s3_client(config):
    """Get or create an S3 client instance for the current thread"""
    if not hasattr(thread_local, 's3_client'):
        # Import boto3 here to avoid errors if not installed
        import boto3
        
        # Get S3 config
        endpoint_url = f"https://{config.get('s3.endpoint')}"
        access_key = config.get('s3.access_key')
        secret_key = config.get('s3.secret_key')
        region = config.get('s3.region')
        
        # Create thread-specific client
        thread_local.s3_client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region
        )
    
    return thread_local.s3_client


def download_file_simple(args: Tuple[str, str, str, object]) -> Dict:
    """Download a single file from S3 without progress tracking"""
    bucket, s3_key, local_file, config = args
    
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(local_file), exist_ok=True)
        
        # Get thread-local S3 client
        s3_client = get_s3_client(config)
        
        # Download file
        s3_client.download_file(
            bucket,
            s3_key,
            local_file
        )
        
        return {'status': 'downloaded', 'file': local_file}
    
    except Exception as e:
        logger.error(f"Error downloading {s3_key}: {str(e)}")
        return {'status': 'failed', 'file': local_file, 'key': s3_key, 'error': str(e)}


def download_file(args: Tuple[str, str, str, object, bool, object]) -> Dict:
    """Download a single file from S3"""
    bucket, s3_key, local_file, config, skip_existing, progress = args
    
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(local_file), exist_ok=True)
        
        # Skip if local file exists and skip_existing is True
        if skip_existing and os.path.exists(local_file):
            # Check if local file and S3 object have the same size
            try:
                s3_client = get_s3_client(config)
                s3_obj = s3_client.head_object(Bucket=bucket, Key=s3_key)
                s3_size = s3_obj.get('ContentLength', 0)
                local_size = os.path.getsize(local_file)
                
                if local_size == s3_size:
                    progress.update('skipped')
                    return {'status': 'skipped', 'file': local_file}
            except Exception:
                # If we can't check, assume we should download
                pass
        
        # Get thread-local S3 client
        s3_client = get_s3_client(config)
        
        # Download file
        s3_client.download_file(
            bucket,
            s3_key,
            local_file
        )
        
        progress.update('downloaded')
        return {'status': 'downloaded', 'file': local_file}
    
    except Exception as e:
        logger.error(f"Error downloading {s3_key}: {str(e)}")
        progress.update('failed')
        return {'status': 'failed', 'file': local_file, 'key': s3_key, 'error': str(e)}


def get_local_path(s3_key: str, remote_prefix: str, local_dir: str) -> str:
    """Convert S3 key to local path"""
    # Remove remote prefix
    rel_path = s3_key[len(remote_prefix):].lstrip('/')
    
    # Build local path
    return os.path.join(local_dir, rel_path)


def list_s3_objects(s3_client, bucket: str, prefix: str, extension: str = None) -> List[str]:
    """List objects in S3 bucket with given prefix using optimized pagination"""
    objects = []
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        # Use larger page size for faster scanning like s3_cleaner
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix, PaginationConfig={'PageSize': 1000})
        
        for page_num, page in enumerate(pages):
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    if extension and not key.lower().endswith(extension.lower()):
                        continue
                    objects.append(key)
            
            # Show progress every 10 pages like s3_cleaner
            if page_num % 10 == 0 and page_num > 0:
                logger.info(f"Scanned {page_num} pages, found {len(objects)} objects so far...")
        
        return objects
    except Exception as e:
        logger.error(f"Error listing objects: {str(e)}")
        return []


def download_files_from_s3(config, local_dir: str, remote_prefix: str = None,
                          workers: int = 20, limit: int = None,
                          skip_existing: bool = True, file_extension: str = None,
                          dry_run: bool = False) -> Dict:
    """
    Download files from S3 to local directory using multiple threads
    
    Args:
        config: ConfigManager instance
        local_dir: Local directory to download to
        remote_prefix: Remote prefix (bomia-engine/data/project/...)
        workers: Number of parallel download workers
        limit: Limit the number of files to download (for testing)
        skip_existing: Skip files that already exist locally
        file_extension: Only download files with this extension
        dry_run: Don't actually download, just show what would be downloaded
        
    Returns:
        Dict with download statistics
    """
    # Get bucket name
    bucket = config.get('s3.bucket')
    
    # If no remote prefix is provided, build from project name
    if not remote_prefix:
        project_name = config.get('project.name')
        remote_prefix = f"bomia-engine/data/{project_name}/raw-frames"

        # If local directory is not specified, use the standard project directory
        if local_dir == f"data/{project_name}/raw-frames":
            logger.info(f"Using standard project directory structure: {remote_prefix} -> {local_dir}")
    
    # Ensure remote_prefix doesn't end with /
    remote_prefix = remote_prefix.rstrip('/')
    
    # Create S3 client for listing
    s3_client = get_s3_client(config)
    
    # Create local directory if it doesn't exist
    os.makedirs(local_dir, exist_ok=True)
    
    # Get local files for quick comparison
    local_files = set()
    if os.path.exists(local_dir):
        logger.info(f"Scanning local files in {local_dir}...")
        local_files = {f for f in os.listdir(local_dir) if f.endswith('.jpg')}
        logger.info(f"Found {len(local_files)} local files")
    
    if dry_run:
        logger.info("DRY RUN - Streaming S3 to show what would be downloaded")
        count = 0
        s3_objects = list_s3_objects(s3_client, bucket, remote_prefix, file_extension)
        for s3_key in s3_objects[:10]:
            filename = s3_key.split('/')[-1]
            if filename not in local_files:
                local_file = get_local_path(s3_key, remote_prefix, local_dir)
                logger.info(f"Would download: s3://{bucket}/{s3_key} -> {local_file}")
                count += 1
        return {'total_files': count, 'dry_run': True}
    
    # Stream S3 and download missing files immediately
    logger.info(f"Streaming S3 objects from s3://{bucket}/{remote_prefix} and downloading missing files...")
    start_time = time.time()
    logger.info(f"Starting streaming download with {workers} workers")
    
    # Track results
    results = {
        'downloaded': 0,
        'skipped': 0,
        'failed': 0,
        'failed_files': []
    }
    
    download_futures = []
    processed_files = 0
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        try:
            # Stream through S3 pages and download missing files immediately
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket, Prefix=remote_prefix, PaginationConfig={'PageSize': 1000})
            
            for page_num, page in enumerate(pages):
                if 'Contents' not in page:
                    continue
                
                # Process files in this page
                for obj in page['Contents']:
                    key = obj['Key']
                    if file_extension and not key.lower().endswith(file_extension.lower()):
                        continue
                    
                    processed_files += 1
                    filename = key.split('/')[-1]
                    
                    # Check if missing locally
                    if filename not in local_files:
                        local_file = get_local_path(key, remote_prefix, local_dir)
                        # Submit download immediately (no progress tracker needed for streaming)
                        future = executor.submit(download_file_simple, (bucket, key, local_file, config))
                        download_futures.append(future)
                    else:
                        results['skipped'] += 1
                    
                    # Check limit
                    if limit and processed_files >= limit:
                        logger.info(f"Reached limit of {limit} files")
                        break
                
                # Process some completed downloads
                completed_futures = []
                for future in download_futures:
                    if future.done():
                        completed_futures.append(future)
                        try:
                            result = future.result()
                            if result['status'] == 'downloaded':
                                results['downloaded'] += 1
                            else:
                                results['failed'] += 1
                                results['failed_files'].append(result.get('file'))
                        except Exception as e:
                            logger.error(f"Download error: {str(e)}")
                            results['failed'] += 1
                
                # Remove completed futures
                for future in completed_futures:
                    download_futures.remove(future)
                
                # Show progress every 10 pages
                if page_num % 10 == 0 and page_num > 0:
                    elapsed = time.time() - start_time
                    total_processed = results['downloaded'] + results['failed'] + results['skipped']
                    speed = total_processed / elapsed if elapsed > 0 else 0
                    logger.info(f"Page {page_num}: Processed {processed_files} S3 files - Downloaded: {results['downloaded']}, "
                               f"Skipped: {results['skipped']}, Failed: {results['failed']} - Speed: {speed:.1f} files/sec")
                
                if limit and processed_files >= limit:
                    break
            
            # Wait for remaining downloads
            logger.info("Waiting for remaining downloads to complete...")
            for future in download_futures:
                try:
                    result = future.result()
                    if result['status'] == 'downloaded':
                        results['downloaded'] += 1
                    else:
                        results['failed'] += 1
                        results['failed_files'].append(result.get('file'))
                except Exception as e:
                    logger.error(f"Final download error: {str(e)}")
                    results['failed'] += 1
                    
        except Exception as e:
            logger.error(f"Error during streaming download: {str(e)}")
            return results
    
    # Download summary
    elapsed_time = time.time() - start_time
    logger.info(f"\nDownload completed in {elapsed_time:.2f} seconds")
    logger.info(f"Total S3 files processed: {processed_files}")
    logger.info(f"Downloaded: {results['downloaded']}")
    logger.info(f"Skipped: {results['skipped']}")
    logger.info(f"Failed: {results['failed']}")
    
    if results['downloaded'] > 0:
        logger.info(f"Download speed: {results['downloaded']/elapsed_time:.2f} files/second")
    
    # Save list of failed files if any
    if results['failed'] > 0:
        failed_log = 'logs/download_failures.log'
        with open(failed_log, 'w') as f:
            for file_path in results['failed_files']:
                f.write(f"{file_path}\n")
        logger.info(f"List of failed downloads saved to: {failed_log}")
    
    return results


def extract_project_from_path(local_dir: str) -> str:
    """Extract project name from local directory path"""
    # Normalize path and split into parts
    path_parts = Path(local_dir).parts
    
    # Look for pattern: data/{project}/raw-frames or similar
    if 'data' in path_parts:
        data_index = path_parts.index('data')
        if data_index + 1 < len(path_parts):
            project_name = path_parts[data_index + 1]
            logger.info(f"Extracted project name '{project_name}' from path: {local_dir}")
            return project_name
    
    # Fallback: use the parent directory name if path ends with raw-frames
    if local_dir.endswith('raw-frames'):
        project_name = Path(local_dir).parent.name
        logger.info(f"Extracted project name '{project_name}' from parent directory")
        return project_name
    
    # Last fallback: use the directory name itself
    project_name = Path(local_dir).name
    logger.info(f"Using directory name '{project_name}' as project name")
    return project_name


def main():
    parser = argparse.ArgumentParser(description="Download files from S3 with multiple threads")
    parser.add_argument('local_dir', help='Local directory to download files to (project name will be extracted from path)')
    parser.add_argument('--remote-prefix', help='Remote S3 prefix (default: bomia-engine/data/project/raw-frames)')
    parser.add_argument('--workers', type=int, default=20, help='Number of parallel download workers (default: 20)')
    parser.add_argument('--limit', type=int, help='Limit number of files to download (for testing)')
    parser.add_argument('--no-skip-existing', action='store_true', help='Do not skip files that already exist locally')
    parser.add_argument('--ext', help='Only download files with this extension (e.g., .jpg)')
    parser.add_argument('--dry-run', action='store_true', help='Don\'t actually download, just preview')
    
    args = parser.parse_args()
    
    # Extract project name from local directory path
    project_name = extract_project_from_path(args.local_dir)
    
    # Initialize config
    config = ConfigManager(project_name)
    
    # Build file extension with dot if needed
    file_extension = None
    if args.ext:
        file_extension = args.ext if args.ext.startswith('.') else f".{args.ext}"
    
    # Run download
    download_files_from_s3(
        config=config,
        local_dir=args.local_dir,
        remote_prefix=args.remote_prefix,
        workers=args.workers,
        limit=args.limit,
        skip_existing=not args.no_skip_existing,
        file_extension=file_extension,
        dry_run=args.dry_run
    )


if __name__ == '__main__':
    main()