# src/bomia/collection/s3_uploader.py

import logging
import threading
import time
from pathlib import Path
from typing import Optional, List, Tuple
from queue import Queue, Empty
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Thread-local storage for S3 client instances
thread_local = threading.local()


class S3FrameUploader:
    """
    Handles uploading individual frames to S3 as they are captured.
    Reuses S3 configuration and client logic from the sync scripts.
    """
    
    def __init__(self, config):
        """
        Initialize S3 uploader with configuration.
        
        Args:
            config: ConfigManager instance with S3 settings
        """
        self.config = config
        self._validate_config()
        
        # Set bucket and prefix before testing connection
        self.bucket = config.get('s3.bucket')
        project_name = config.get('project.name')
        self.remote_prefix = f"bomia-engine/data/{project_name}/raw-frames"
        
        self._test_connection()
        
        logger.info(f"S3 uploader initialized. Bucket: {self.bucket}, Prefix: {self.remote_prefix}")
    
    def _validate_config(self):
        """Validate S3 configuration is complete."""
        required_keys = ['s3.bucket', 's3.endpoint', 's3.access_key', 's3.secret_key', 's3.region']
        missing_config = []
        
        for key in required_keys:
            value = self.config.get(key)
            if not value or str(value).strip() in ['', 'YOUR_DIGITALOCEAN_SPACES_ACCESS_KEY', 'YOUR_DIGITALOCEAN_SPACES_SECRET_KEY', 'your-bucket-name']:
                missing_config.append(key)
        
        if missing_config:
            raise ValueError(f"S3 configuration incomplete. Missing or invalid: {', '.join(missing_config)}")
    
    def _test_connection(self):
        """Test S3 connection."""
        try:
            import boto3  # noqa: F401
        except ImportError:
            raise ImportError("boto3 is required for S3 uploads. Install with: pip install boto3")
        
        try:
            s3_client = self._get_s3_client()
            # Try to check if our specific bucket exists instead of listing all buckets
            # This requires fewer permissions
            s3_client.head_bucket(Bucket=self.bucket)
            logger.info("S3 connection test successful")
        except Exception as e:
            # If head_bucket fails, try a more basic test
            try:
                # Try to list objects in our bucket (with limit to minimize impact)
                s3_client.list_objects_v2(Bucket=self.bucket, MaxKeys=1)
                logger.info("S3 connection test successful (via list_objects)")
            except Exception as e2:
                raise ConnectionError(f"S3 connection test failed: {e2}")
    
    def _get_s3_client(self):
        """Get or create an S3 client instance for the current thread."""
        if not hasattr(thread_local, 's3_client'):
            import boto3
            
            endpoint_url = f"https://{self.config.get('s3.endpoint')}"
            access_key = self.config.get('s3.access_key')
            secret_key = self.config.get('s3.secret_key')
            region = self.config.get('s3.region')
            
            thread_local.s3_client = boto3.client(
                's3',
                endpoint_url=endpoint_url,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
        
        return thread_local.s3_client
    
    def upload_frame(self, local_file_path: Path, relative_path: Optional[str] = None) -> bool:
        """
        Upload a single frame file to S3.
        
        Args:
            local_file_path: Path to the frame file to upload
            
        Returns:
            bool: True if upload succeeded, False otherwise
        """
        try:
            s3_client = self._get_s3_client()
            
            # Build S3 key: remote_prefix/relative_path or remote_prefix/filename
            if relative_path:
                s3_key = f"{self.remote_prefix}/{relative_path}"
            else:
                filename = local_file_path.name
                s3_key = f"{self.remote_prefix}/{filename}"
            
            # Upload file
            s3_client.upload_file(
                str(local_file_path),
                self.bucket,
                s3_key
            )
            
            logger.debug(f"Uploaded {filename} to s3://{self.bucket}/{s3_key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to upload {local_file_path.name} to S3: {e}")
            return False


class BatchS3Uploader:
    """
    Batch S3 uploader that collects frames and uploads them periodically.
    """
    
    def __init__(self, config, upload_interval_minutes: int = 60):
        """
        Initialize batch S3 uploader.
        
        Args:
            config: ConfigManager instance with S3 settings
            upload_interval_minutes: Minutes between batch uploads
        """
        self.base_uploader = S3FrameUploader(config)
        self.upload_interval = timedelta(minutes=upload_interval_minutes)
        self.upload_queue: Queue[Tuple[Path, Optional[str]]] = Queue()
        self.failed_uploads: List[Tuple[Path, str]] = []
        self.stop_event = threading.Event()
        self.upload_thread = None
        self.last_upload_time = datetime.now()
        
        logger.info(f"Batch S3 uploader initialized. Upload interval: {upload_interval_minutes} minutes")
    
    def start(self):
        """Start the background upload thread."""
        if self.upload_thread and self.upload_thread.is_alive():
            logger.warning("Upload thread already running")
            return
        
        self.stop_event.clear()
        self.upload_thread = threading.Thread(target=self._upload_worker, daemon=True)
        self.upload_thread.start()
        logger.info("Batch upload thread started")
    
    def stop(self):
        """Stop the background upload thread."""
        self.stop_event.set()
        if self.upload_thread:
            self.upload_thread.join(timeout=10)
            logger.info("Batch upload thread stopped")
    
    def queue_upload(self, local_file_path: Path, relative_path: Optional[str] = None):
        """Queue a file for batch upload."""
        self.upload_queue.put((local_file_path, relative_path))
    
    def _upload_worker(self):
        """Worker thread that performs batch uploads periodically."""
        while not self.stop_event.is_set():
            try:
                # Check if it's time to upload
                now = datetime.now()
                if now - self.last_upload_time >= self.upload_interval:
                    self._perform_batch_upload()
                    self.last_upload_time = now
                
                # Sleep for a short time before checking again
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in batch upload worker: {e}", exc_info=True)
                time.sleep(30)  # Wait longer on error
    
    def _perform_batch_upload(self):
        """Perform a batch upload of all queued files."""
        batch_size = self.upload_queue.qsize()
        if batch_size == 0:
            logger.debug("No files queued for batch upload")
            return
        
        logger.info(f"Starting batch upload of {batch_size} files")
        uploaded = 0
        failed = 0
        
        # Process all queued files
        for _ in range(batch_size):
            try:
                file_path, relative_path = self.upload_queue.get_nowait()
                
                # Skip if file doesn't exist
                if not file_path.exists():
                    logger.warning(f"File no longer exists: {file_path}")
                    continue
                
                # Try to upload with retry
                success = False
                for attempt in range(3):  # 3 attempts
                    if self.base_uploader.upload_frame(file_path, relative_path):
                        uploaded += 1
                        success = True
                        break
                    else:
                        if attempt < 2:
                            time.sleep(2 ** attempt)  # Exponential backoff
                
                if not success:
                    failed += 1
                    self.failed_uploads.append((file_path, relative_path or file_path.name))
                    
            except Empty:
                break
            except Exception as e:
                logger.error(f"Error processing batch upload item: {e}")
                failed += 1
        
        logger.info(f"Batch upload complete: {uploaded} succeeded, {failed} failed")
        
        # Retry failed uploads if any
        if self.failed_uploads:
            self._retry_failed_uploads()
    
    def _retry_failed_uploads(self):
        """Retry previously failed uploads."""
        if not self.failed_uploads:
            return
        
        retry_count = len(self.failed_uploads)
        logger.info(f"Retrying {retry_count} failed uploads")
        
        still_failed = []
        for file_path, relative_path in self.failed_uploads:
            if not file_path.exists():
                continue
            
            if not self.base_uploader.upload_frame(file_path, relative_path):
                still_failed.append((file_path, relative_path))
        
        self.failed_uploads = still_failed
        if still_failed:
            logger.warning(f"{len(still_failed)} uploads still failing after retry")


def create_s3_uploader(config) -> Optional[S3FrameUploader]:
    """
    Factory function to create S3 uploader with proper error handling.
    
    Args:
        config: ConfigManager instance
        
    Returns:
        S3FrameUploader instance or None if configuration/connection fails
    """
    try:
        return S3FrameUploader(config)
    except (ValueError, ImportError, ConnectionError) as e:
        logger.error(f"Failed to initialize S3 uploader: {e}")
        return None


def create_batch_s3_uploader(config, upload_interval_minutes: int = 60) -> Optional[BatchS3Uploader]:
    """
    Factory function to create batch S3 uploader.
    
    Args:
        config: ConfigManager instance
        upload_interval_minutes: Minutes between batch uploads
        
    Returns:
        BatchS3Uploader instance or None if configuration fails
    """
    try:
        uploader = BatchS3Uploader(config, upload_interval_minutes)
        uploader.start()
        return uploader
    except (ValueError, ImportError, ConnectionError) as e:
        logger.error(f"Failed to initialize batch S3 uploader: {e}")
        return None