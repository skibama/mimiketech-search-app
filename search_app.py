from flask import Flask, render_template, request, jsonify, Response, redirect, url_for
from elasticsearch import Elasticsearch
from werkzeug.utils import secure_filename
from docx import Document
import os
import json
import tempfile
import uuid

app = Flask(__name__)

# Configuration
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()  # Use system temp directory
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['ALLOWED_EXTENSIONS'] = {'docx'}

# Elasticsearch connection details
ES_URL = "https://7f5e3429796d45748b57199b8b00f8d2.us-east-1.aws.found.io:443"
ES_API_KEY = "OU9VcTg1VUJqeXlLQnlwZHdtdHE6ZUlqcHdodTVTWmFpTXh0cjNUVDg1UQ=="
ES_INDEX = "docstraining4"

# Initialize Elasticsearch client
es = Elasticsearch(ES_URL, api_key=ES_API_KEY, verify_certs=False)

def allowed_file(filename):
    """Check if the file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

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
            "paragraphs": paragraphs
        }
        
        return document_data
        
    except Exception as e:
        raise Exception(f"Error converting document: {str(e)}")

@app.route('/')
def index():
    # Check if Elasticsearch is connected
    if not es.ping():
        return render_template('es_error.html')
        
    return render_template('index.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'docfile' not in request.files:
            return jsonify({"error": "No file part"}), 400
            
        file = request.files['docfile']
        
        # If user does not select file, browser submits an empty file
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
            
        if file and allowed_file(file.filename):
            # Secure the filename and save temporarily
            filename = secure_filename(file.filename)
            temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4()}_{filename}")
            
            try:
                file.save(temp_filepath)
                
                # Convert to JSON
                json_data = convert_docx_to_json(temp_filepath, filename)
                
                # Index in Elasticsearch
                result = es.index(index=ES_INDEX, document=json_data)
                
                # Clean up the temp file
                os.remove(temp_filepath)
                
                # Return success with document ID
                return jsonify({
                    "success": True, 
                    "message": f"Document '{filename}' uploaded and indexed successfully!",
                    "id": result['_id']
                })
                
            except Exception as e:
                # Clean up on error if file exists
                if os.path.exists(temp_filepath):
                    os.remove(temp_filepath)
                return jsonify({"error": str(e)}), 500
        else:
            return jsonify({"error": "File type not allowed. Please upload a .docx file"}), 400
    
    # GET request returns the upload form
    return render_template('upload.html')

@app.route('/search')
def search():
    query = request.args.get('q', '')
    
    if not query:
        return jsonify({"hits": []})
    
    # Search query with highlighting
    search_query = {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["title^2", "content", "paragraphs"],
                "fuzziness": "AUTO"
            }
        },
        "highlight": {
            "fields": {
                "content": {"fragment_size": 200, "number_of_fragments": 3},
                "title": {}
            }
        }
    }
    
    try:
        response = es.search(index=ES_INDEX, body=search_query)
        
        # Format the results
        hits = []
        for hit in response['hits']['hits']:
            result = {
                "id": hit["_id"],
                "score": hit["_score"],
                "title": hit["_source"]["title"],
                "filename": hit["_source"]["filename"]
            }
            
            # Add highlighting if available
            if "highlight" in hit:
                result["highlights"] = hit["highlight"]
            
            hits.append(result)
            
        return jsonify({"hits": hits})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/list-all')
def list_all():
    try:
        # Query to fetch all documents without sorting
        list_query = {
            "query": {
                "match_all": {}
            },
            "size": 100  # Limit to 100 documents
        }
        
        response = es.search(index=ES_INDEX, body=list_query)
        
        # Format the results
        hits = []
        for hit in response['hits']['hits']:
            result = {
                "id": hit["_id"],
                "title": hit["_source"]["title"],
                "filename": hit["_source"]["filename"]
            }
            hits.append(result)
            
        return jsonify({"hits": hits})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download/<doc_id>')
def download_document(doc_id):
    try:
        # Get the document from Elasticsearch
        doc = es.get(index=ES_INDEX, id=doc_id)
        
        if not doc or not doc.get('_source'):
            return "Document not found", 404
        
        # Get the document source
        source = doc['_source']
        
        # Determine the filename
        filename = source.get('filename', f"document_{doc_id}.txt")
        
        # Get the content (could be in 'content' or 'paragraphs' field)
        if 'content' in source:
            content = source['content']
        elif 'paragraphs' in source:
            content = '\n\n'.join(source['paragraphs'])
        else:
            content = json.dumps(source, indent=2)  # Fallback to the entire source
        
        # Create a downloadable response
        response = Response(content)
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        
        return response
        
    except Exception as e:
        return f"Error retrieving document: {str(e)}", 500

@app.route('/download-json/<doc_id>')
def download_json(doc_id):
    try:
        # Get the document from Elasticsearch
        doc = es.get(index=ES_INDEX, id=doc_id)
        
        if not doc or not doc.get('_source'):
            return "Document not found", 404
        
        # Get the document source
        source = doc['_source']
        
        # Determine the filename
        base_filename = source.get('title', f"document_{doc_id}")
        filename = f"{base_filename}.json"
        
        # Create a downloadable response with the full JSON
        response = Response(json.dumps(source, indent=2))
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        
        return response
        
    except Exception as e:
        return f"Error retrieving document: {str(e)}", 500

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Create the upload template
    upload_template = '''
<!DOCTYPE html>
<html>
<head>
    <title>Mimiketech Search - Upload Document</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #e6f2ff;
        }
        .container {
            background-color: white;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        h1 {
            text-align: center;
            color: #333;
        }
        .upload-form {
            margin-top: 20px;
        }
        .file-input {
            margin-bottom: 15px;
        }
        .submit-btn {
            padding: 10px 15px;
            background-color: #4285f4;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
        }
        .back-btn {
            display: inline-block;
            margin-top: 20px;
            padding: 10px 15px;
            background-color: #34a853;
            color: white;
            text-decoration: none;
            border-radius: 4px;
        }
        .result-message {
            margin-top: 20px;
            padding: 10px;
            border-radius: 4px;
            display: none;
        }
        .success {
            background-color: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .error {
            background-color: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .loading {
            display: none;
            text-align: center;
            margin-top: 20px;
        }
        .loading::after {
            content: "Processing...";
            color: #666;
            font-style: italic;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Upload Document</h1>
        
        <div class="upload-form">
            <p>Select a Word document (.docx) to upload and index:</p>
            
            <form id="upload-form" enctype="multipart/form-data">
                <div class="file-input">
                    <input type="file" name="docfile" id="docfile" accept=".docx" required>
                </div>
                
                <button type="submit" class="submit-btn">Upload & Index</button>
            </form>
        </div>
        
        <div id="loading" class="loading"></div>
        
        <div id="result-message" class="result-message"></div>
        
        <a href="/" class="back-btn">Back to Search</a>
    </div>
    
    <script>
        document.getElementById('upload-form').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const fileInput = document.getElementById('docfile');
            const file = fileInput.files[0];
            
            if (!file) {
                showMessage('Please select a file to upload', 'error');
                return;
            }
            
            const formData = new FormData();
            formData.append('docfile', file);
            
            // Show loading
            document.getElementById('loading').style.display = 'block';
            
            // Reset message
            document.getElementById('result-message').style.display = 'none';
            
            fetch('/upload', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                document.getElementById('loading').style.display = 'none';
                
                if (data.error) {
                    showMessage(data.error, 'error');
                } else {
                    showMessage(data.message, 'success');
                    // Reset the form
                    document.getElementById('upload-form').reset();
                }
            })
            .catch(error => {
                document.getElementById('loading').style.display = 'none';
                showMessage('Error uploading file: ' + error.message, 'error');
            });
        });
        
        function showMessage(message, type) {
            const messageElement = document.getElementById('result-message');
            messageElement.textContent = message;
            messageElement.className = 'result-message ' + type;
            messageElement.style.display = 'block';
        }
    </script>
</body>
</html>
    '''
    
    # Update the main HTML template to include upload link
    html_template = '''
<!DOCTYPE html>
<html>
<head>
    <title>Mimiketech Search</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #e6f2ff;  /* Light blue background */
        }
        .search-container {
            margin-bottom: 20px;
        }
        input[type="text"] {
            width: 70%;
            padding: 10px;
            font-size: 16px;
        }
        button {
            padding: 10px 15px;
            font-size: 16px;
            background-color: #4285f4;
            color: white;
            border: none;
            cursor: pointer;
        }
        .result {
            margin-bottom: 20px;
            padding: 15px;
            border: 1px solid #ddd;
            border-radius: 4px;
            background-color: white;
        }
        .result-title {
            font-size: 18px;
            margin-bottom: 10px;
        }
        .highlight {
            background-color: #ffff99;
        }
        .result-meta {
            color: #666;
            font-size: 14px;
            margin-bottom: 10px;
        }
        .result-actions {
            margin-top: 10px;
        }
        .download-btn {
            display: inline-block;
            padding: 5px 10px;
            background-color: #34a853;
            color: white;
            text-decoration: none;
            border-radius: 3px;
            font-size: 14px;
            margin-right: 10px;
        }
        .download-json-btn {
            display: inline-block;
            padding: 5px 10px;
            background-color: #ea4335;
            color: white;
            text-decoration: none;
            border-radius: 3px;
            font-size: 14px;
        }
        .loading {
            display: none;
            margin: 20px 0;
        }
        .button-container {
            display: flex;
            justify-content: space-between;
            margin-bottom: 20px;
        }
        .action-btn {
            padding: 10px 15px;
            font-size: 16px;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            text-align: center;
        }
        .list-all-btn {
            background-color: #fbbc05;
        }
        .upload-btn {
            background-color: #34a853;
        }
        .header {
            margin-bottom: 30px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Mimiketech Search</h1>
    </div>
    
    <div class="search-container">
        <input type="text" id="search-input" placeholder="Search documents...">
        <button id="search-button">Search</button>
    </div>
    
    <div class="button-container">
        <a href="/list-all" class="action-btn list-all-btn">List All Documents</a>
        <a href="/upload" class="action-btn upload-btn">Upload New Document</a>
    </div>
    
    <div id="loading" class="loading">Searching...</div>
    
    <div id="results"></div>
    
    <script>
        document.getElementById('search-button').addEventListener('click', performSearch);
        document.getElementById('search-input').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                performSearch();
            }
        });
        
        function performSearch() {
            const query = document.getElementById('search-input').value.trim();
            if (!query) return;
            
            const loading = document.getElementById('loading');
            const results = document.getElementById('results');
            
            loading.style.display = 'block';
            results.innerHTML = '';
            
            fetch(`/search?q=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(data => {
                    loading.style.display = 'none';
                    
                    if (data.error) {
                        results.innerHTML = `<p>Error: ${data.error}</p>`;
                        return;
                    }
                    
                    if (data.hits.length === 0) {
                        results.innerHTML = '<p>No results found.</p>';
                        return;
                    }
                    
                    displayResults(data.hits);
                })
                .catch(error => {
                    loading.style.display = 'none';
                    results.innerHTML = `<p>Error: ${error.message}</p>`;
                });
        }
        
        function displayResults(hits, isListAll = false) {
            const results = document.getElementById('results');
            
            let resultsHtml = '';
            if (isListAll) {
                resultsHtml += `<h2>All Documents (${hits.length})</h2>`;
            }
            
            hits.forEach(hit => {
                let highlightHtml = '';
                
                if (hit.highlights) {
                    if (hit.highlights.content) {
                        highlightHtml = hit.highlights.content.join('... ');
                    } else if (hit.highlights.title) {
                        highlightHtml = hit.highlights.title.join(' ');
                    }
                }
                
                resultsHtml += `
                    <div class="result">
                        <div class="result-title">${hit.title}</div>
                        <div class="result-meta">File: ${hit.filename} ${hit.score ? `| Score: ${hit.score.toFixed(2)}` : ''}</div>
                        ${highlightHtml ? `<div class="result-highlight">${highlightHtml}</div>` : ''}
                        <div class="result-actions">
                            <a href="/download/${hit.id}" class="download-btn">Download Text</a>
                            <a href="/download-json/${hit.id}" class="download-json-btn">Download JSON</a>
                        </div>
                    </div>
                `;
            });
            
            results.innerHTML = resultsHtml;
        }
        
        // Check if we should list all documents on page load
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('listAll') === 'true') {
            document.addEventListener('DOMContentLoaded', function() {
                fetch('/list-all')
                    .then(response => response.json())
                    .then(data => {
                        if (data.error) {
                            document.getElementById('results').innerHTML = `<p>Error: ${data.error}</p>`;
                            return;
                        }
                        
                        if (data.hits.length === 0) {
                            document.getElementById('results').innerHTML = '<p>No documents found in the index.</p>';
                            return;
                        }
                        
                        displayResults(data.hits, true);
                    })
                    .catch(error => {
                        document.getElementById('results').innerHTML = `<p>Error: ${error.message}</p>`;
                    });
            });
        }
    </script>
</body>
</html>
    '''
    
    # Create error template
    es_error_template = '''
<!DOCTYPE html>
<html>
<head>
    <title>Elasticsearch Connection Error</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.6;
            background-color: #e6f2ff;  /* Light blue background */
        }
        .error-container {
            background-color: #fff0f0;
            border-left: 4px solid #ff3333;
            padding: 15px;
            margin-bottom: 20px;
        }
        h1 {
            color: #333;
            text-align: center;
        }
        code {
            background: #f4f4f4;
            padding: 2px 5px;
            border-radius: 3px;
            font-family: monospace;
        }
        pre {
            background: #f4f4f4;
            padding: 10px;
            border-radius: 3px;
            overflow-x: auto;
        }
    </style>
</head>
<body>
    <h1>Mimiketech Search - Connection Error</h1>
    
    <div class="error-container">
        <p><strong>Cannot connect to Elasticsearch.</strong> Please check your configuration.</p>
    </div>
    
    <h2>Troubleshooting:</h2>
    
    <ol>
        <li>Verify your Elasticsearch URL is correct</li>
        <li>Check that your API key has proper permissions</li>
        <li>Ensure the Elasticsearch service is running</li>
        <li>Check network connectivity to the Elasticsearch server</li>
    </ol>
    
    <p>After addressing these issues, please restart the application.</p>
</body>
</html>
    '''
    
    # Write the template files
    with open('templates/index.html', 'w') as f:
        f.write(html_template)
        
    with open('templates/es_error.html', 'w') as f:
        f.write(es_error_template)
        
    with open('templates/upload.html', 'w') as f:
        f.write(upload_template)
    
    # Start the Flask app
    app.run(debug=True, host='0.0.0.0', port=5000)