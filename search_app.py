from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, send_from_directory
from elasticsearch import Elasticsearch
from werkzeug.utils import secure_filename
from docx import Document
import os
import json
import tempfile
import uuid
import base64

app = Flask(__name__)

# Configuration
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()  # Use system temp directory
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['ALLOWED_EXTENSIONS'] = {'docx'}

# Create a static folder for assets if it doesn't exist
STATIC_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
if not os.path.exists(STATIC_FOLDER):
    os.makedirs(STATIC_FOLDER)
if not os.path.exists(os.path.join(STATIC_FOLDER, 'images')):
    os.makedirs(os.path.join(STATIC_FOLDER, 'images'))

# Elasticsearch connection details
ES_URL = "https://7f5e3429796d45748b57199b8b00f8d2.us-east-1.aws.found.io:443"
ES_API_KEY = "OU9VcTg1VUJqeXlLQnlwZHdtdHE6ZUlqcHdodTVTWmFpTXh0cjNUVDg1UQ=="
ES_INDEX = "docstraining4"

# Initialize Elasticsearch client
es = Elasticsearch(ES_URL, api_key=ES_API_KEY, verify_certs=False)

# Create logo and save it to static folder
def create_logo():
    # Base64 encoded SVG logo for Mimiketech
    logo_svg = '''
    <svg xmlns="http://www.w3.org/2000/svg" width="200" height="60" viewBox="0 0 200 60">
        <rect width="200" height="60" fill="#2c3e50" rx="5" ry="5"/>
        <text x="20" y="38" font-family="Arial, sans-serif" font-size="24" font-weight="bold" fill="#ecf0f1">Mimiketech</text>
        <circle cx="170" cy="30" r="15" fill="#3498db"/>
        <path d="M165 30 L175 30 M170 25 L170 35" stroke="#ecf0f1" stroke-width="2"/>
    </svg>
    '''
    
    # Save the SVG logo
    with open(os.path.join(STATIC_FOLDER, 'images', 'logo.svg'), 'w') as f:
        f.write(logo_svg)
    
    return '/static/images/logo.svg'

# Generate logo path
logo_path = create_logo()

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

@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)

@app.route('/')
def index():
    # Check if Elasticsearch is connected
    if not es.ping():
        return render_template('es_error.html', logo_path=logo_path)
        
    return render_template('index.html', logo_path=logo_path)

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
    return render_template('upload.html', logo_path=logo_path)

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
    
    # Create CSS file for common styles
    css_content = '''
    :root {
        --primary-color: #2c3e50;
        --secondary-color: #3498db;
        --accent-color: #e74c3c;
        --light-color: #ecf0f1;
        --dark-color: #2c3e50;
        --success-color: #27ae60;
        --warning-color: #f39c12;
        --error-color: #c0392b;
    }
    
    body {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        margin: 0;
        padding: 0;
        background-color: #f5f7fa;
        background-image: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%233498db' fill-opacity='0.05'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
    }
    
    .container {
        max-width: 1000px;
        margin: 0 auto;
        padding: 20px;
    }
    
    .header {
        background-color: var(--primary-color);
        color: var(--light-color);
        padding: 15px 0;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    }
    
    .header-content {
        display: flex;
        justify-content: space-between;
        align-items: center;
        max-width: 1000px;
        margin: 0 auto;
        padding: 0 20px;
    }
    
    .logo-container {
        display: flex;
        align-items: center;
    }
    
    .logo {
        height: 40px;
        margin-right: 10px;
    }
    
    .nav-links {
        display: flex;
    }
    
    .nav-link {
        color: var(--light-color);
        text-decoration: none;
        padding: 10px 15px;
        margin-left: 5px;
        border-radius: 4px;
        transition: background-color 0.3s;
    }
    
    .nav-link:hover {
        background-color: rgba(255, 255, 255, 0.1);
    }
    
    .card {
        background-color: white;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.08);
        padding: 20px;
        margin-bottom: 20px;
    }
    
    .search-container {
        display: flex;
        margin-bottom: 20px;
    }
    
    .search-input {
        flex: 1;
        padding: 12px 15px;
        font-size: 16px;
        border: 2px solid #ddd;
        border-radius: 6px 0 0 6px;
        transition: border-color 0.3s;
    }
    
    .search-input:focus {
        border-color: var(--secondary-color);
        outline: none;
    }
    
    .search-button {
        padding: 12px 20px;
        font-size: 16px;
        background-color: var(--secondary-color);
        color: white;
        border: none;
        border-radius: 0 6px 6px 0;
        cursor: pointer;
        transition: background-color 0.3s;
    }
    
    .search-button:hover {
        background-color: #2980b9;
    }
    
    .action-buttons {
        display: flex;
        justify-content: space-between;
        margin-bottom: 20px;
        gap: 10px;
    }
    
    .action-btn {
        flex: 1;
        padding: 12px 15px;
        font-size: 16px;
        color: white;
        text-decoration: none;
        border-radius: 6px;
        text-align: center;
        transition: transform 0.2s, box-shadow 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .action-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
    }
    
    .list-all-btn {
        background-color: var(--warning-color);
    }
    
    .list-all-btn:hover {
        background-color: #e67e22;
    }
    
    .upload-btn {
        background-color: var(--success-color);
    }
    
    .upload-btn:hover {
        background-color: #219653;
    }
    
    .result {
        background-color: white;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
        padding: 20px;
        margin-bottom: 20px;
        transition: transform 0.2s;
        border-left: 4px solid var(--secondary-color);
    }
    
    .result:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.08);
    }
    
    .result-title {
        font-size: 18px;
        font-weight: 600;
        margin-bottom: 10px;
        color: var(--dark-color);
    }
    
    .result-meta {
        color: #666;
        font-size: 14px;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
    }
    
    .result-meta i {
        margin-right: 5px;
    }
    
    .result-highlight {
        background-color: #fff8e1;
        padding: 10px;
        border-radius: 4px;
        margin: 10px 0;
        border-left: 2px solid #ffc107;
    }
    
    .highlight {
        background-color: rgba(255, 193, 7, 0.3);
        padding: 0 2px;
    }
    
    .result-actions {
        margin-top: 15px;
        display: flex;
    }
    
    .action-button {
        display: inline-flex;
        align-items: center;
        padding: 8px 12px;
        color: white;
        text-decoration: none;
        border-radius: 4px;
        font-size: 14px;
        margin-right: 10px;
        transition: background-color 0.2s;
    }
    
    .action-button i {
        margin-right: 5px;
    }
    
    .download-btn {
        background-color: var(--success-color);
    }
    
    .download-btn:hover {
        background-color: #219653;
    }
    
    .download-json-btn {
        background-color: var(--accent-color);
    }
    
    .download-json-btn:hover {
        background-color: #c0392b;
    }
    
    .loading {
        display: none;
        text-align: center;
        padding: 20px;
    }
    
    .loading-spinner {
        border: 4px solid rgba(0, 0, 0, 0.1);
        border-left: 4px solid var(--secondary-color);
        border-radius: 50%;
        width: 30px;
        height: 30px;
        animation: spin 1s linear infinite;
        margin: 0 auto;
    }
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    
    .footer {
        background-color: var(--primary-color);
        color: var(--light-color);
        text-align: center;
        padding: 20px;
        margin-top: 40px;
        font-size: 14px;
    }
    
    /* Upload page specific styles */
    .upload-form {
        max-width: 600px;
        margin: 0 auto;
    }
    
    .file-input-container {
        border: 2px dashed #ddd;
        padding: 30px;
        text-align: center;
        border-radius: 8px;
        margin-bottom: 20px;
        transition: border-color 0.3s;
    }
    
    .file-input-container:hover, .file-input-container.dragover {
        border-color: var(--secondary-color);
    }
    
    .file-input-label {
        display: block;
        cursor: pointer;
    }
    
    .file-input {
        opacity: 0;
        position: absolute;
        z-index: -1;
    }
    
    .file-input-icon {
        font-size: 48px;
        color: var(--secondary-color);
        margin-bottom: 10px;
    }
    
    .file-input-text {
        color: #666;
    }
    
    .file-name {
        margin-top: 10px;
        font-weight: 500;
        color: var(--dark-color);
    }
    
    .submit-btn {
        width: 100%;
        padding: 12px;
        background-color: var(--secondary-color);
        color: white;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-size: 16px;
        transition: background-color 0.3s;
    }
    
    .submit-btn:hover {
        background-color: #2980b9;
    }
    
    .submit-btn:disabled {
        background-color: #bdc3c7;
        cursor: not-allowed;
    }
    
    .result-message {
        margin-top: 20px;
        padding: 15px;
        border-radius: 6px;
        display: none;
    }
    
    .success-message {
        background-color: #d4edda;
        color: #155724;
        border: 1px solid #c3e6cb;
    }
    
    .error-message {
        background-color: #f8d7da;
        color: #721c24;
        border: 1px solid #f5c6cb;
    }
    
    /* Responsive design */
    @media (max-width: 768px) {
        .search-container {
            flex-direction: column;
        }
        
        .search-input {
            border-radius: 6px;
            margin-bottom: 10px;
        }
        
        .search-button {
            border-radius: 6px;
        }
        
        .action-buttons {
            flex-direction: column;
        }
        
        .header-content {
            flex-direction: column;
            text-align: center;
        }
        
        .nav-links {
            margin-top: 15px;
        }
    }
    '''
    
    # Create the CSS file
    os.makedirs(os.path.join(STATIC_FOLDER, 'css'), exist_ok=True)
    with open(os.path.join(STATIC_FOLDER, 'css', 'style.css'), 'w') as f:
        f.write(css_content)
    
    # Create the upload template
    upload_template = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mimiketech Search - Upload Document</title>
    <link rel="stylesheet" href="/static/css/style.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body>
    <header class="header">
        <div class="header-content">
            <div class="logo-container">
                <img src="{{ logo_path }}" alt="Mimiketech Logo" class="logo">
            </div>
            <nav class="nav-links">
                <a href="/" class="nav-link">Home</a>
                <a href="/upload" class="nav-link">Upload</a>
                <a href="/?listAll=true" class="nav-link">All Documents</a>
            </nav>
        </div>
    </header>

    <div class="container">
        <div class="card">
            <h1>Upload Document</h1>
            
            <div class="upload-form">
                <p>Select a Word document (.docx) to upload and index:</p>
                
                <div id="drop-area" class="file-input-container">
                    <label for="docfile" class="file-input-label">
                        <div class="file-input-icon">
                            <i class="fas fa-file-upload"></i>
                        </div>
                        <div class="file-input-text">
                            Drag & drop your file here or click to browse
                        </div>
                        <input type="file" name="docfile" id="docfile" class="file-input" accept=".docx" required>
                    </label>
                    <div id="file-name" class="file-name"></div>
                </div>
                
                <button type="button" id="upload-button" class="submit-btn" disabled>Upload & Index</button>
            </div>
            
            <div id="loading" class="loading">
                <div class="loading-spinner"></div>
                <p>Processing your document...</p>
            </div>
            
            <div id="result-message" class="result-message"></div>
            
            <div style="text-align: center; margin-top: 20px;">
                <a href="/" class="action-button download-btn">
                    <i class="fas fa-arrow-left"></i> Back to Search
                </a>
            </div>
        </div>
    </div>
    
    <footer class="footer">
        <div class="container">
            <p>&copy; 2025 Mimiketech Search. All rights reserved.</p>
        </div>
    </footer>
    
    <script>
        const dropArea = document.getElementById('drop-area');
        const fileInput = document.getElementById('docfile');
        const fileName = document.getElementById('file-name');
        const uploadButton = document.getElementById('upload-button');
        const loading = document.getElementById('loading');
        const resultMessage = document.getElementById('result-message');
        
        // Handle file selection
        fileInput.addEventListener('change', function() {
            if (this.files.length > 0) {
                fileName.textContent = this.files[0].name;
                uploadButton.disabled = false;
            } else {
                fileName.textContent = '';
                uploadButton.disabled = true;
            }
        });
        
        // Handle drag and drop events
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, preventDefaults, false);
        });
        
        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }
        
        ['dragenter', 'dragover'].forEach(eventName => {
            dropArea.addEventListener(eventName, highlight, false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, unhighlight, false);
        });
        
        function highlight() {
            dropArea.classList.add('dragover');
        }
        
        function unhighlight() {
            dropArea.classList.remove('dragover');
        }
        
        dropArea.addEventListener('drop', handleDrop, false);
        
        function handleDrop(e) {
            const dt = e.dataTransfer;
            const files = dt.files;
            
            if (files.length > 0) {
                fileInput.files = files;
                fileName.textContent = files[0].name;
                uploadButton.disabled = false;
            }
        }
        
        // Handle upload button click
        uploadButton.addEventListener('click', function() {
            const file = fileInput.files[0];
            
            if (!file) {
                showMessage('Please select a file to upload', 'error');
                return;
            }
            
            const formData = new FormData();
            formData.append('docfile', file);
            
            // Show loading
            loading.style.display = 'block';
            resultMessage.style.display = 'none';
            uploadButton.disabled = true;
            
            fetch('/upload', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                loading.style.display = 'none';
                
                if (data.error) {
                    showMessage(data.error, 'error');
                    uploadButton.disabled = false;
                } else {
                    showMessage(data.message, 'success');
                    // Reset the form
                    fileInput.value = '';
                    fileName.textContent = '';
                    uploadButton.disabled = true;
                }
            })
            .catch(error => {
                loading.style.display = 'none';
                showMessage('Error uploading file: ' + error.message, 'error');
                uploadButton.disabled = false;
            });
        });
        
        function showMessage(message, type) {
            resultMessage.textContent = message;
            resultMessage.className = type === 'success' 
                ? 'result-message success-message' 
                : 'result-message error-message';
            resultMessage.style.display = 'block';
        }
    </script>
</body>
</html>
    '''
    
    # Update the main HTML template to include upload link
    html_template = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mimiketech Search</title>
    <link rel="stylesheet" href="/static/css/style.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body>
    <header class="header">
        <div class="header-content">
            <div class="logo-container">
                <img src="{{ logo_path }}" alt="Mimiketech Logo" class="logo">
            </div>
            <nav class="nav-links">
                <a href="/" class="nav-link">Home</a>
                <a href="/upload" class="nav-link">Upload</a>
                <a href="/?listAll=true" class="nav-link">All Documents</a>
            </nav>
        </div>
    </header>

    <div class="container">
        <div class="card">
            <h1>Document Search</h1>
            <p>Search through your documents or upload new ones to expand your knowledge base.</p>
            
            <div class="search-container">
                <input type="text" id="search-input" class="search-input" placeholder="Search documents...">
                <button id="search-button" class="search-button">
                    <i class="fas fa-search"></i> Search
                </button>
            </div>
            
            <div class="action-buttons">
                <a href="/?listAll=true" class="action-btn list-all-btn">
                    <i class="fas fa-list-ul"></i>&nbsp; View All Documents
                </a>
<a href="/upload" class="action-btn upload-btn">
                    <i class="fas fa-file-upload"></i>&nbsp; Upload New Document
                </a>
            </div>
            
            <div id="loading" class="loading">
                <div class="loading-spinner"></div>
                <p>Searching documents...</p>
            </div>
            
            <div id="results"></div>
        </div>
    </div>
    
    <footer class="footer">
        <div class="container">
            <p>&copy; 2025 Mimiketech Search. All rights reserved.</p>
        </div>
    </footer>
    
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
                        results.innerHTML = `<div class="result error-message"><p>Error: ${data.error}</p></div>`;
                        return;
                    }
                    
                    if (data.hits.length === 0) {
                        results.innerHTML = '<div class="result"><p>No results found. Try different search terms or <a href="/upload">upload new documents</a>.</p></div>';
                        return;
                    }
                    
                    displayResults(data.hits);
                })
                .catch(error => {
                    loading.style.display = 'none';
                    results.innerHTML = `<div class="result error-message"><p>Error: ${error.message}</p></div>`;
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
                        <div class="result-meta">
                            <i class="fas fa-file-alt"></i> ${hit.filename} 
                            ${hit.score ? `<span style="margin-left: 10px;"><i class="fas fa-star"></i> Score: ${hit.score.toFixed(2)}</span>` : ''}
                        </div>
                        ${highlightHtml ? `<div class="result-highlight">${highlightHtml}</div>` : ''}
                        <div class="result-actions">
                            <a href="/download/${hit.id}" class="action-button download-btn">
                                <i class="fas fa-file-download"></i> Download Text
                            </a>
                            <a href="/download-json/${hit.id}" class="action-button download-json-btn">
                                <i class="fas fa-code"></i> Download JSON
                            </a>
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
                const loading = document.getElementById('loading');
                const results = document.getElementById('results');
                
                loading.style.display = 'block';
                
                fetch('/list-all')
                    .then(response => response.json())
                    .then(data => {
                        loading.style.display = 'none';
                        
                        if (data.error) {
                            results.innerHTML = `<div class="result error-message"><p>Error: ${data.error}</p></div>`;
                            return;
                        }
                        
                        if (data.hits.length === 0) {
                            results.innerHTML = '<div class="result"><p>No documents found in the index. <a href="/upload">Upload some documents</a> to get started.</p></div>';
                            return;
                        }
                        
                        displayResults(data.hits, true);
                    })
                    .catch(error => {
                        loading.style.display = 'none';
                        results.innerHTML = `<div class="result error-message"><p>Error: ${error.message}</p></div>`;
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
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mimiketech - Connection Error</title>
    <link rel="stylesheet" href="/static/css/style.css">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body>
    <header class="header">
        <div class="header-content">
            <div class="logo-container">
                <img src="{{ logo_path }}" alt="Mimiketech Logo" class="logo">
            </div>
        </div>
    </header>

    <div class="container">
        <div class="card">
            <h1><i class="fas fa-exclamation-triangle" style="color: #e74c3c;"></i> Connection Error</h1>
            
            <div class="result error-message">
                <p><strong>Cannot connect to Elasticsearch.</strong> Please check your configuration.</p>
            </div>
            
            <h2>Troubleshooting:</h2>
            
            <div class="result">
                <ol>
                    <li>Verify your Elasticsearch URL is correct</li>
                    <li>Check that your API key has proper permissions</li>
                    <li>Ensure the Elasticsearch service is running</li>
                    <li>Check network connectivity to the Elasticsearch server</li>
                </ol>
                
                <p>After addressing these issues, please restart the application.</p>
            </div>
        </div>
    </div>
    
    <footer class="footer">
        <div class="container">
            <p>&copy; 2025 Mimiketech Search. All rights reserved.</p>
        </div>
    </footer>
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