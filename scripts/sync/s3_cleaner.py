#!/usr/bin/env python3
"""
Multithreaded S3 file cleaner for Bomia Engine.
Deletes all files from S3 bucket that are inside bomia-engine/* prefix with parallel processing.
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
        logging.FileHandler('logs/s3_cleanup.log'),
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
        self.deleted = 0
        self.failed = 0
        self.lock = threading.Lock()
        self.last_update_time = time.time()
        self.start_time = time.time()
    
    def update(self, status: str):
        with self.lock:
            if status == 'deleted':
                self.deleted += 1
            elif status == 'failed':
                self.failed += 1
            
            current_time = time.time()
            if current_time - self.last_update_time >= 1.0:  # Update display every second
                self.display_progress()
                self.last_update_time = current_time
    
    def display_progress(self):
        processed = self.deleted + self.failed
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
              f"Deleted: {self.deleted}, Failed: {self.failed} - "
              f"Speed: {files_per_second:.1f} files/sec - ETA: {eta}", end="")
        sys.stdout.flush()
    
    def get_summary(self) -> Dict:
        elapsed = time.time() - self.start_time
        speed = self.deleted / elapsed if elapsed > 0 else 0
        
        return {
            'deleted': self.deleted,
            'failed': self.failed,
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


def delete_batch(args: Tuple[str, List[str], object]) -> Dict:
    """Delete a batch of files from S3 using batch delete API"""
    bucket, s3_keys, config = args
    
    try:
        # Get thread-local S3 client
        s3_client = get_s3_client(config)
        
        # Prepare delete request (max 1000 objects per batch)
        delete_objects = [{'Key': key} for key in s3_keys]
        
        # Batch delete
        response = s3_client.delete_objects(
            Bucket=bucket,
            Delete={
                'Objects': delete_objects,
                'Quiet': True  # Don't return info about successfully deleted objects
            }
        )
        
        # Check for errors
        errors = response.get('Errors', [])
        deleted_count = len(s3_keys) - len(errors)
        
        return {
            'status': 'completed',
            'deleted': deleted_count,
            'failed': len(errors),
            'errors': errors,
            'total': len(s3_keys)
        }
    
    except Exception as e:
        logger.error(f"Error batch deleting {len(s3_keys)} files: {str(e)}")
        return {
            'status': 'failed',
            'deleted': 0,
            'failed': len(s3_keys),
            'error': str(e),
            'total': len(s3_keys)
        }


def list_s3_objects(s3_client, bucket: str, prefix: str, extension: str = None) -> List[str]:
    """List objects in S3 bucket with given prefix"""
    objects = []
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    if extension and not key.lower().endswith(extension.lower()):
                        continue
                    objects.append(key)
        
        return objects
    except Exception as e:
        logger.error(f"Error listing objects: {str(e)}")
        return []


def delete_files_from_s3(config, remote_prefix: str = "bomia-engine", 
                        workers: int = 20, limit: int = None, 
                        file_extension: str = None, dry_run: bool = False, 
                        skip_confirmation: bool = False) -> Dict:
    """
    Delete files from S3 bucket using streaming pagination
    
    Args:
        config: ConfigManager instance
        remote_prefix: Remote prefix to delete from (default: bomia-engine)
        workers: Number of parallel delete workers
        limit: Limit the number of files to delete (for testing)
        file_extension: Only delete files with this extension
        dry_run: Don't actually delete, just show what would be deleted
        
    Returns:
        Dict with deletion statistics
    """
    # Get bucket name
    bucket = config.get('s3.bucket')
    
    # Ensure remote_prefix doesn't end with /
    remote_prefix = remote_prefix.rstrip('/')
    
    # Create S3 client for listing
    s3_client = get_s3_client(config)
    
    logger.info(f"Starting streaming deletion from s3://{bucket}/{remote_prefix}")
    
    if dry_run:
        logger.info("DRY RUN - Counting files and showing preview...")
        # For dry run, still do a quick count
        objects_count = 0
        preview_objects = []
        
        try:
            paginator = s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket, Prefix=remote_prefix)
            
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        key = obj['Key']
                        if file_extension and not key.lower().endswith(file_extension.lower()):
                            continue
                        objects_count += 1
                        if len(preview_objects) < 10:
                            preview_objects.append(key)
        except Exception as e:
            logger.error(f"Error counting objects: {str(e)}")
            return {}
        
        logger.info("DRY RUN - No files will be deleted")
        logger.info(f"Found {objects_count} objects to delete")
        
        for s3_key in preview_objects:
            logger.info(f"Would delete: s3://{bucket}/{s3_key}")
        
        if objects_count > 10:
            logger.info(f"... and {objects_count - 10} more files")
        
        return {'total_files': objects_count, 'dry_run': True}
    
    # Show warning and ask for confirmation
    if not skip_confirmation:
        print(f"\n🚨 WARNING: You are about to delete ALL files from s3://{bucket}/{remote_prefix}")
        print("This will start deleting immediately in batches of 1000!")
        print("This action cannot be undone!")
        
        confirmation = input("\nType 'DELETE' (in capital letters) to confirm: ")
        if confirmation != 'DELETE':
            logger.info("Operation cancelled by user.")
            return {'cancelled': True}
    else:
        logger.info(f"Skipping confirmation, deleting files from s3://{bucket}/{remote_prefix}")
    
    # Track results
    results = {
        'deleted': 0,
        'failed': 0,
        'failed_files': [],
        'total_processed': 0
    }
    
    start_time = time.time()
    logger.info(f"Starting streaming deletion with {workers} workers")
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket, Prefix=remote_prefix, PaginationConfig={'PageSize': 1000})
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            
            for page_num, page in enumerate(pages):
                if 'Contents' not in page:
                    continue
                    
                # Collect objects from this page
                page_objects = []
                for obj in page['Contents']:
                    key = obj['Key']
                    if file_extension and not key.lower().endswith(file_extension.lower()):
                        continue
                    page_objects.append(key)
                    
                    # Check limit
                    if limit and results['total_processed'] + len(page_objects) >= limit:
                        page_objects = page_objects[:limit - results['total_processed']]
                        break
                
                if not page_objects:
                    continue
                
                results['total_processed'] += len(page_objects)
                
                # Submit batch deletion task for this page (1 API call for up to 1000 files)
                future = executor.submit(delete_batch, (bucket, page_objects, config))
                futures.append(future)
                
                logger.info(f"Page {page_num + 1}: Queued {len(page_objects)} files for batch deletion (Total processed: {results['total_processed']})")
                
                # Process completed batch deletions periodically
                completed_futures = []
                for future in futures:
                    if future.done():
                        completed_futures.append(future)
                        try:
                            result = future.result()
                            results['deleted'] += result.get('deleted', 0)
                            results['failed'] += result.get('failed', 0)
                            
                            # Log any errors from the batch
                            if result.get('errors'):
                                for error in result.get('errors', []):
                                    results['failed_files'].append(error.get('Key', 'unknown'))
                                    logger.error(f"Error deleting {error.get('Key', 'unknown')}: {error.get('Message', 'unknown error')}")
                                    
                        except Exception as e:
                            logger.error(f"Error processing batch result: {str(e)}")
                            # Estimate failed files if we can't get exact count
                            estimated_files = 1000  # rough estimate for failed batch
                            results['failed'] += estimated_files
                
                # Remove completed futures
                for future in completed_futures:
                    futures.remove(future)
                
                # Show progress
                elapsed = time.time() - start_time
                if results['deleted'] > 0:
                    speed = results['deleted'] / elapsed
                    logger.info(f"Progress: {results['deleted']} deleted, {results['failed']} failed - Speed: {speed:.1f} files/sec")
                
                # Check limit
                if limit and results['total_processed'] >= limit:
                    logger.info(f"Reached limit of {limit} files")
                    break
            
            # Wait for remaining futures
            logger.info("Waiting for remaining batch deletions to complete...")
            for future in futures:
                try:
                    result = future.result()
                    results['deleted'] += result.get('deleted', 0)
                    results['failed'] += result.get('failed', 0)
                    
                    # Log any errors from the batch
                    if result.get('errors'):
                        for error in result.get('errors', []):
                            results['failed_files'].append(error.get('Key', 'unknown'))
                            logger.error(f"Error deleting {error.get('Key', 'unknown')}: {error.get('Message', 'unknown error')}")
                            
                except Exception as e:
                    logger.error(f"Error processing final batch result: {str(e)}")
                    results['failed'] += 1000  # rough estimate
                    
    except Exception as e:
        logger.error(f"Error during streaming deletion: {str(e)}")
        return results
    
    # Deletion summary
    elapsed_time = time.time() - start_time
    logger.info(f"\nStreaming deletion completed in {elapsed_time:.2f} seconds")
    logger.info(f"Total processed: {results['total_processed']}")
    logger.info(f"Deleted: {results['deleted']}")
    logger.info(f"Failed: {results['failed']}")
    
    if results['deleted'] > 0:
        logger.info(f"Deletion speed: {results['deleted']/elapsed_time:.2f} files/second")
    
    # Save list of failed files if any
    if results['failed'] > 0:
        failed_log = 'logs/deletion_failures.log'
        with open(failed_log, 'w') as f:
            for file_key in results['failed_files']:
                f.write(f"{file_key}\n")
        logger.info(f"List of failed deletions saved to: {failed_log}")
    
    return results


def extract_project_from_path(path: str) -> str:
    """Extract project name from local or remote path"""
    # Normalize path and split into parts
    path_parts = Path(path).parts
    
    # Look for pattern: data/{project}/raw-frames or similar
    if 'data' in path_parts:
        data_index = path_parts.index('data')
        if data_index + 1 < len(path_parts):
            project_name = path_parts[data_index + 1]
            logger.info(f"Extracted project name '{project_name}' from path: {path}")
            return project_name
    
    # Fallback: use the parent directory name if path ends with raw-frames
    if path.endswith('raw-frames'):
        project_name = Path(path).parent.name
        logger.info(f"Extracted project name '{project_name}' from parent directory")
        return project_name
    
    # Last fallback: use the directory name itself
    project_name = Path(path).name
    logger.info(f"Using directory name '{project_name}' as project name")
    return project_name


def main():
    parser = argparse.ArgumentParser(description="Delete files from S3 with multiple threads")
    parser.add_argument('path', nargs='?', help='Local directory path to derive project name and S3 prefix (e.g., data/sinterizacao-1/raw-frames)')
    parser.add_argument('--remote-prefix', help='Remote S3 prefix to delete from (overrides path-based derivation)')
    parser.add_argument('--workers', type=int, default=20, 
                       help='Number of parallel delete workers (default: 20)')
    parser.add_argument('--limit', type=int, 
                       help='Limit number of files to delete (for testing)')
    parser.add_argument('--ext', help='Only delete files with this extension (e.g., .jpg)')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Don\'t actually delete, just preview')
    parser.add_argument('--yes', action='store_true', 
                       help='Skip confirmation prompt')
    
    args = parser.parse_args()
    
    # Determine project name and remote prefix
    if args.path:
        # Extract project from path
        project_name = extract_project_from_path(args.path)
        
        # Build remote prefix if not explicitly provided
        if not args.remote_prefix:
            args.remote_prefix = f"bomia-engine/data/{project_name}/raw-frames"
            logger.info(f"Derived remote prefix: {args.remote_prefix}")
    else:
        if not args.remote_prefix:
            # Default fallback
            args.remote_prefix = 'bomia-engine'
            logger.info("No path provided, using default remote prefix: bomia-engine")
        
        # Try to extract project name from remote prefix if possible
        try:
            project_name = extract_project_from_path(args.remote_prefix)
        except:
            logger.error("Could not determine project name. Please provide a path argument.")
            sys.exit(1)
    
    # Initialize config
    config = ConfigManager(project_name)
    
    # Build file extension with dot if needed
    file_extension = None
    if args.ext:
        file_extension = args.ext if args.ext.startswith('.') else f".{args.ext}"
    
    # Run deletion
    delete_files_from_s3(
        config=config,
        remote_prefix=args.remote_prefix,
        workers=args.workers,
        limit=args.limit,
        file_extension=file_extension,
        dry_run=args.dry_run,
        skip_confirmation=args.yes
    )


if __name__ == '__main__':
    main()