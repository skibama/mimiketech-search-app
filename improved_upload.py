import os
import json
import argparse
from elasticsearch import Elasticsearch

def upload_json_files(folder_path, es_url, username=None, password=None, api_key=None, index_name="documents"):
    # Connect to Elasticsearch
    es = None
    connection_successful = False
    error_message = ""
    
    # Try API key first if provided
    if api_key:
        try:
            print(f"Attempting to connect with API key...")
            es = Elasticsearch(es_url, api_key=api_key, verify_certs=False)
            if es.ping():
                print("✓ Connection successful with API key!")
                connection_successful = True
            else:
                error_message = "Could not ping server with API key"
        except Exception as e:
            error_message = f"API key connection error: {str(e)}"
            print(f"✗ {error_message}")
    
    # If API key failed and username/password provided, try basic auth
    if not connection_successful and username and password:
        try:
            print(f"Attempting to connect with username/password...")
            es = Elasticsearch(es_url, basic_auth=(username, password), verify_certs=False)
            if es.ping():
                print("✓ Connection successful with username/password!")
                connection_successful = True
            else:
                error_message += "\nCould not ping server with username/password"
        except Exception as e:
            error_message += f"\nBasic auth connection error: {str(e)}"
            print(f"✗ {error_message}")
    
    # If still not connected, exit
    if not connection_successful:
        print(f"Failed to connect to Elasticsearch: {error_message}")
        return
    
    print(f"Connected to Elasticsearch at {es_url}")
    
    # Create index if it doesn't exist
    try:
        if not es.indices.exists(index=index_name):
            print(f"Creating index '{index_name}'...")
            mapping = {
                "mappings": {
                    "properties": {
                        "title": {"type": "text"},
                        "filename": {"type": "keyword"},
                        "content": {"type": "text"},
                        "paragraphs": {"type": "text"}
                    }
                }
            }
            es.indices.create(index=index_name, body=mapping)
            print(f"Index '{index_name}' created successfully")
        else:
            print(f"Index '{index_name}' already exists")
    except Exception as e:
        print(f"Error creating/checking index: {str(e)}")
        return
    
    # Process all JSON files in the folder
    json_files = [f for f in os.listdir(folder_path) if f.endswith('.json')]
    
    if not json_files:
        print(f"No JSON files found in {folder_path}")
        return
    
    print(f"Found {len(json_files)} JSON files to process")
    
    success_count = 0
    for filename in json_files:
        file_path = os.path.join(folder_path, filename)
        
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                doc = json.load(file)
            
            # Index the document
            result = es.index(index=index_name, document=doc)
            print(f"Indexed {filename}: {result['result']}")
            success_count += 1
            
        except Exception as e:
            print(f"Error processing {filename}: {str(e)}")
    
    # Refresh index
    es.indices.refresh(index=index_name)
    print(f"Completed: {success_count} of {len(json_files)} files uploaded to '{index_name}'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload JSON files to Elasticsearch")
    parser.add_argument("--folder", required=True, help="Folder containing JSON files")
    parser.add_argument("--url", required=True, help="Elasticsearch URL")
    parser.add_argument("--username", help="Elasticsearch username")
    parser.add_argument("--password", help="Elasticsearch password")
    parser.add_argument("--api-key", help="Elasticsearch API key")
    parser.add_argument("--index", default="documents", help="Elasticsearch index name")
    
    args = parser.parse_args()
    
    # Make sure we have at least one authentication method
    if not (args.api_key or (args.username and args.password)):
        print("Error: You must provide either API key or username/password")
        exit(1)
    
    upload_json_files(
        args.folder,
        args.url,
        args.username,
        args.password,
        args.api_key,
        args.index
    )