import time
import os
import json
from docx import Document
from elasticsearch import Elasticsearch
import logging
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("docx_uploader.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Elasticsearch connection details
ES_URL = "https://7f5e3429796d45748b57199b8b00f8d2.us-east-1.aws.found.io:443"
ES_API_KEY = "OU9VcTg1VUJqeXlLQnlwZHdtdHE6ZUlqcHdodTVTWmFpTXh0cjNUVDg1UQ=="
ES_INDEX = "docstraining4"

# Folder to watch
WATCH_FOLDER = r"C:\elasticsearch-upload\Mimiketech uploads"
PROCESSED_FOLDER = os.path.join(WATCH_FOLDER, "processed")

# Initialize Elasticsearch client
es = Elasticsearch(ES_URL, api_key=ES_API_KEY, verify_certs=False)

def ensure_folders_exist():
    """Ensure the watch folder and processed folder exist"""
    if not os.path.exists(WATCH_FOLDER):
        os.makedirs(WATCH_FOLDER)
        logger.info(f"Created watch folder: {WATCH_FOLDER}")
    
    if not os.path.exists(PROCESSED_FOLDER):
        os.makedirs(PROCESSED_FOLDER)
        logger.info(f"Created processed folder: {PROCESSED_FOLDER}")

def convert_docx_to_json(file_path, original_filename):
    """Convert a .docx file to JSON format"""
    try:
        # Open the document
        doc = Document(file_path)
        
        # Extract text from paragraphs
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        
        # Extract base name without extension
        base_name = os.path.splitext(original_filename)[0]
        
        # Create a JSON object with metadata and content
        document_data = {
            "title": base_name,
            "filename": original_filename,
            "content": "\n\n".join(paragraphs),
            "paragraphs": paragraphs,
            "upload_date": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        return document_data
        
    except Exception as e:
        logger.error(f"Error converting document {original_filename}: {str(e)}")
        raise

def index_to_elasticsearch(json_data):
    """Index JSON data to Elasticsearch"""
    try:
        if not es.ping():
            logger.error("Cannot connect to Elasticsearch")
            return False
            
        result = es.index(index=ES_INDEX, document=json_data)
        return result['_id']
        
    except Exception as e:
        logger.error(f"Error indexing to Elasticsearch: {str(e)}")
        return False

def process_file(file_path):
    """Process a single file - convert and index it"""
    filename = os.path.basename(file_path)
    
    if not filename.lower().endswith('.docx'):
        logger.info(f"Skipping non-docx file: {filename}")
        return False
    
    try:
        logger.info(f"Processing file: {filename}")
        
        # Convert to JSON
        json_data = convert_docx_to_json(file_path, filename)
        
        # Index to Elasticsearch
        doc_id = index_to_elasticsearch(json_data)
        
        if doc_id:
            # Move to processed folder
            processed_path = os.path.join(PROCESSED_FOLDER, filename)
            os.rename(file_path, processed_path)
            
            logger.info(f"Successfully processed {filename} (ID: {doc_id})")
            return True
        else:
            logger.error(f"Failed to index {filename} to Elasticsearch")
            return False
            
    except Exception as e:
        logger.error(f"Error processing {filename}: {str(e)}")
        return False

class DocxHandler(FileSystemEventHandler):
    """Watchdog handler to detect new files"""
    
    def on_created(self, event):
        """Called when a file or directory is created"""
        if event.is_directory:
            return
            
        file_path = event.src_path
        filename = os.path.basename(file_path)
        
        # Only process .docx files
        if filename.lower().endswith('.docx'):
            logger.info(f"New file detected: {filename}")
            
            # Wait a moment to ensure file is completely written
            time.sleep(1)
            
            # Process the file
            process_file(file_path)

def process_existing_files():
    """Process any existing files in the watch folder"""
    for filename in os.listdir(WATCH_FOLDER):
        file_path = os.path.join(WATCH_FOLDER, filename)
        if os.path.isfile(file_path) and filename.lower().endswith('.docx'):
            process_file(file_path)

def main():
    """Main entry point for the watcher service"""
    logger.info("Starting document uploader service")
    
    # Ensure folders exist
    ensure_folders_exist()
    
    # Test Elasticsearch connection
    try:
        if not es.ping():
            logger.error("Cannot connect to Elasticsearch. Please check your connection settings.")
            return
        logger.info("Successfully connected to Elasticsearch")
    except Exception as e:
        logger.error(f"Error connecting to Elasticsearch: {str(e)}")
        return
    
    # Process any existing files
    logger.info("Processing existing files...")
    process_existing_files()
    
    # Set up the file watcher
    event_handler = DocxHandler()
    observer = Observer()
    observer.schedule(event_handler, WATCH_FOLDER, recursive=False)
    observer.start()
    
    logger.info(f"Watching for new .docx files in {WATCH_FOLDER}")
    logger.info("Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    
    observer.join()
    logger.info("Document uploader service stopped")

if __name__ == "__main__":
    main()