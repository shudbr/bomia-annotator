#!/usr/bin/env python3
"""
Multithreaded S3 file uploader for Bomia Engine.
Uploads local files to S3 with parallel processing.
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
        logging.FileHandler('logs/s3_upload.log'),
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
        self.uploaded = 0
        self.failed = 0
        self.skipped = 0
        self.lock = threading.Lock()
        self.last_update_time = time.time()
        self.start_time = time.time()
    
    def update(self, status: str):
        with self.lock:
            if status == 'uploaded':
                self.uploaded += 1
            elif status == 'failed':
                self.failed += 1
            elif status == 'skipped':
                self.skipped += 1
            
            current_time = time.time()
            if current_time - self.last_update_time >= 1.0:  # Update display every second
                self.display_progress()
                self.last_update_time = current_time
    
    def display_progress(self):
        processed = self.uploaded + self.failed + self.skipped
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
              f"Uploaded: {self.uploaded}, Failed: {self.failed}, Skipped: {self.skipped} - "
              f"Speed: {files_per_second:.1f} files/sec - ETA: {eta}", end="")
        sys.stdout.flush()
    
    def get_summary(self) -> Dict:
        elapsed = time.time() - self.start_time
        speed = (self.uploaded + self.skipped) / elapsed if elapsed > 0 else 0
        
        return {
            'uploaded': self.uploaded,
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


def upload_file(args: Tuple[str, str, str, object, bool, object]) -> Dict:
    """Upload a single file to S3"""
    local_file, bucket, s3_key, config, skip_existing, progress = args
    
    try:
        # Get thread-local S3 client
        s3_client = get_s3_client(config)
        
        # Check if file already exists in S3
        if skip_existing:
            try:
                s3_client.head_object(Bucket=bucket, Key=s3_key)
                # File exists, skip upload
                progress.update('skipped')
                return {'status': 'skipped', 'file': local_file}
            except Exception:
                # File doesn't exist, continue with upload
                pass
        
        # Upload file
        s3_client.upload_file(
            local_file,
            bucket,
            s3_key
        )
        
        progress.update('uploaded')
        return {'status': 'uploaded', 'file': local_file}
    
    except Exception as e:
        logger.error(f"Error uploading {local_file}: {str(e)}")
        progress.update('failed')
        return {'status': 'failed', 'file': local_file, 'error': str(e)}


def build_s3_key(local_path: str, local_base_dir: str, remote_prefix: str) -> str:
    """Build the S3 key for a local file"""
    # Get the relative path from the base dir
    rel_path = os.path.relpath(local_path, local_base_dir)
    
    # Join with remote prefix
    return os.path.join(remote_prefix, rel_path).replace('\\', '/')


def scan_local_directory(directory: str, file_extension: str = None) -> List[str]:
    """Scan local directory for files to upload"""
    files = []
    
    for root, _, filenames in os.walk(directory):
        for filename in filenames:
            if file_extension and not filename.lower().endswith(file_extension.lower()):
                continue
            
            file_path = os.path.join(root, filename)
            files.append(file_path)
    
    return files


def upload_files_to_s3(config, local_dir: str, remote_prefix: str = None, 
                       workers: int = 20, limit: int = None, 
                       skip_existing: bool = True, file_extension: str = None,
                       dry_run: bool = False) -> Dict:
    """
    Upload files from local directory to S3 using multiple threads
    
    Args:
        config: ConfigManager instance
        local_dir: Local directory to upload from
        remote_prefix: Remote prefix (bomia-engine/data/project/...)
        workers: Number of parallel upload workers
        limit: Limit the number of files to upload (for testing)
        skip_existing: Skip files that already exist in S3
        file_extension: Only upload files with this extension
        dry_run: Don't actually upload, just show what would be uploaded
        
    Returns:
        Dict with upload statistics
    """
    # Get bucket name
    bucket = config.get('s3.bucket')
    
    # If no remote prefix is provided, build from project name
    if not remote_prefix:
        project_name = config.get('project.name')
        remote_prefix = f"bomia-engine/data/{project_name}/raw-frames"

        # Check if we're uploading from the standard project directory
        if local_dir == f"data/{project_name}/raw-frames":
            logger.info(f"Using standard project directory structure: {local_dir} -> {remote_prefix}")
    
    # Ensure remote_prefix doesn't start or end with /
    remote_prefix = remote_prefix.strip('/')
    
    logger.info(f"Scanning local directory: {local_dir}")
    local_files = scan_local_directory(local_dir, file_extension)
    
    # Limit number of files if requested
    if limit and limit > 0 and limit < len(local_files):
        logger.info(f"Limiting to first {limit} files (out of {len(local_files)} total)")
        local_files = local_files[:limit]
    
    logger.info(f"Found {len(local_files)} files to upload")
    
    if dry_run:
        logger.info("DRY RUN - No files will be uploaded")
        for i, local_file in enumerate(local_files[:10]):
            s3_key = build_s3_key(local_file, local_dir, remote_prefix)
            logger.info(f"Would upload: {local_file} -> s3://{bucket}/{s3_key}")
        
        if len(local_files) > 10:
            logger.info(f"... and {len(local_files) - 10} more files")
        
        return {'total_files': len(local_files), 'dry_run': True}
    
    # Initialize progress tracker
    progress = ProgressTracker(len(local_files))
    
    # Prepare upload tasks
    upload_tasks = []
    for local_file in local_files:
        s3_key = build_s3_key(local_file, local_dir, remote_prefix)
        upload_tasks.append((local_file, bucket, s3_key, config, skip_existing, progress))
    
    # Start upload with ThreadPoolExecutor
    start_time = time.time()
    logger.info(f"Starting upload with {workers} workers")
    
    # Track results
    results = {
        'uploaded': 0,
        'skipped': 0,
        'failed': 0,
        'failed_files': []
    }
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(upload_file, task) for task in upload_tasks]
        
        # Process completed uploads
        for future in as_completed(futures):
            try:
                result = future.result()
                status = result.get('status')
                
                if status == 'uploaded':
                    results['uploaded'] += 1
                elif status == 'skipped':
                    results['skipped'] += 1
                elif status == 'failed':
                    results['failed'] += 1
                    results['failed_files'].append(result.get('file'))
            except Exception as e:
                logger.error(f"Unexpected error in file upload: {str(e)}")
                results['failed'] += 1
    
    # Final progress display
    progress.display_progress()
    print()  # New line after progress
    
    # Upload summary
    elapsed_time = time.time() - start_time
    logger.info(f"\nUpload completed in {elapsed_time:.2f} seconds")
    logger.info(f"Total files: {len(local_files)}")
    logger.info(f"Uploaded: {results['uploaded']}")
    logger.info(f"Skipped: {results['skipped']}")
    logger.info(f"Failed: {results['failed']}")
    
    if results['uploaded'] > 0:
        logger.info(f"Upload speed: {results['uploaded']/elapsed_time:.2f} files/second")
    
    # Save list of failed files if any
    if results['failed'] > 0:
        failed_log = 'logs/upload_failures.log'
        with open(failed_log, 'w') as f:
            for file_path in results['failed_files']:
                f.write(f"{file_path}\n")
        logger.info(f"List of failed uploads saved to: {failed_log}")
    
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
    parser = argparse.ArgumentParser(description="Upload files to S3 with multiple threads")
    parser.add_argument('local_dir', help='Local directory containing files to upload (project name will be extracted from path)')
    parser.add_argument('--remote-prefix', help='Remote S3 prefix (default: bomia-engine/data/project/raw-frames)')
    parser.add_argument('--workers', type=int, default=20, help='Number of parallel upload workers (default: 20)')
    parser.add_argument('--limit', type=int, help='Limit number of files to upload (for testing)')
    parser.add_argument('--no-skip-existing', action='store_true', help='Do not skip files that already exist in S3')
    parser.add_argument('--ext', help='Only upload files with this extension (e.g., .jpg)')
    parser.add_argument('--dry-run', action='store_true', help='Don\'t actually upload, just preview')
    
    args = parser.parse_args()
    
    # Check local directory exists
    if not os.path.isdir(args.local_dir):
        logger.error(f"Local directory does not exist: {args.local_dir}")
        sys.exit(1)
    
    # Extract project name from local directory path
    project_name = extract_project_from_path(args.local_dir)
    
    # Initialize config
    config = ConfigManager(project_name)
    
    # Build file extension with dot if needed
    file_extension = None
    if args.ext:
        file_extension = args.ext if args.ext.startswith('.') else f".{args.ext}"
    
    # Run upload
    upload_files_to_s3(
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