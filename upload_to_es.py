import os
import json
import argparse
from elasticsearch import Elasticsearch

def upload_json_files(folder_path, es_url, username, password, api_key, index_name):
    # Connect to Elasticsearch
    if api_key:
        es = Elasticsearch(es_url, api_key=api_key, verify_certs=False)
    else:
        es = Elasticsearch(es_url, basic_auth=(username, password), verify_certs=False)
    
    # Check connection
    if not es.ping():
        print("Failed to connect to Elasticsearch!")
        return
    
    print(f"Connected to Elasticsearch at {es_url}")
    
    # Create index if it doesn't exist
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
    
    # Process all JSON files in the folder
    file_count = 0
    success_count = 0
    
    for filename in os.listdir(folder_path):
        if filename.endswith('.json'):
            file_path = os.path.join(folder_path, filename)
            file_count += 1
            
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
    print(f"Completed: {success_count} of {file_count} files uploaded to '{index_name}'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload JSON files to Elasticsearch")
    parser.add_argument("--folder", required=True, help="Folder containing JSON files")
    parser.add_argument("--url", required=True, help="Elasticsearch URL")
    parser.add_argument("--username", help="Elasticsearch username")
    parser.add_argument("--password", help="Elasticsearch password")
    parser.add_argument("--api-key", help="Elasticsearch API key")
    parser.add_argument("--index", default="documents", help="Elasticsearch index name")
    
    args = parser.parse_args()
    
    # Validate auth params
    if not (args.api_key or (args.username and args.password)):
        print("Error: You must provide either API key or username and password")
        exit(1)
    
    upload_json_files(
        args.folder,
        args.url,
        args.username,
        args.password,
        args.api_key,
        args.index
    )