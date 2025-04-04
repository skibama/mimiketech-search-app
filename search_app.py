from flask import Flask, render_template, request, jsonify, Response, redirect, url_for, send_from_directory
from elasticsearch import Elasticsearch
from werkzeug.utils import secure_filename
from docx import Document
import logging
from logging.handlers import RotatingFileHandler
import datetime
import time
import psutil  
import os
import json
import tempfile
import uuid
import socket
import base64

app = Flask(__name__)

# Configuration
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()  # Use system temp directory
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['ALLOWED_EXTENSIONS'] = {'docx'}

# Add metrics tracking attributes to app
app.start_time = time.time()
app.request_count = 0
app.active_requests = set()

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

# Add this right after initializing your Elasticsearch client
try:
    if not es.indices.exists(index='mimiketech-logs'):
        es.indices.create(index='mimiketech-logs')
    if not es.indices.exists(index='mimiketech-metrics'):
        es.indices.create(index='mimiketech-metrics')
except Exception as e:
    print(f"Error creating indices: {e}")

# Set up file logging
if not os.path.exists('logs'):
    os.mkdir('logs')
file_handler = RotatingFileHandler('logs/search_app.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)
app.logger.setLevel(logging.INFO)
app.logger.info('Search app startup')

# Set up application logging to Elasticsearch
class ElasticsearchLogHandler(logging.Handler):
# In your ElasticsearchLogHandler class, modify the index_name to include a date
def emit(self, record):
    try:
        # Use a daily index pattern
        actual_index = f"{self.index_name}-{datetime.datetime.utcnow().strftime('%Y.%m.%d')}"
        log_entry = {
            # ... your log entry data ...
        }
        self.es_client.index(index=actual_index, document=log_entry)
    except Exception as e:
        print(f"Failed to send log to Elasticsearch: {e}")
    def __init__(self, es_client, index_name):
        super().__init__()
        self.es_client = es_client
        self.index_name = index_name
        self.hostname = socket.gethostname()
        
    def emit(self, record):
        try:
            log_entry = {
                'timestamp': datetime.datetime.utcnow().isoformat(),
                'level': record.levelname,
                'message': self.format(record),
                'logger': record.name,
                'path': record.pathname,
                'function': record.funcName,
                'line_number': record.lineno,
                'host': self.hostname,
                'service': 'mimiketech-search',
                'request_id': getattr(record, 'request_id', str(uuid.uuid4()))
            }
            
            self.es_client.index(index=self.index_name, document=log_entry)
        except Exception as e:
            print(f"Failed to send log to Elasticsearch: {e}")

# Add Elasticsearch log handler to app logger
es_handler = ElasticsearchLogHandler(es, 'mimiketech-logs')
es_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
es_handler.setFormatter(formatter)
app.logger.addHandler(es_handler)

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

# Set up request middleware - fixed to prevent multiple handlers
@app.before_request
def before_request():
    # Generate request ID
    request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
    g.request_id = request_id
    # Store start time for performance tracking
    g.start_time = time.time()
    # Track request count
    app.request_count += 1
    app.active_requests.add(request_id)
    # Log request start
    app.logger.info(f"Request started: {request.method} {request.path}",
                  extra={'request_id': request_id})

@app.after_request
def after_request(response):
    # Calculate request duration
    duration = time.time() - g.start_time if hasattr(g, 'start_time') else 0
    request_id = getattr(g, 'request_id', None)
    
    # Log request completion with all details
    log_data = {
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'method': request.method,
        'path': request.path,
        'status_code': response.status_code,
        'duration_ms': round(duration * 1000, 2),
        'user_agent': request.user_agent.string,
        'ip': request.remote_addr,
        'request_id': request_id
    }
    
    # Send log to Elasticsearch
    try:
        es.index(index='mimiketech-logs', document=log_data)
    except Exception as e:
        print(f"Failed to log to Elasticsearch: {e}")
    
    # Also log to application logger
    app.logger.info(
        f"{request.remote_addr} - {request.method} {request.full_path} {response.status_code} in {duration:.3f}s",
        extra={'request_id': request_id}
    )
    
    # Remove from active requests
    if request_id in app.active_requests:
        app.active_requests.remove(request_id)
    
    # Add request ID header to response
    response.headers['X-Request-ID'] = request_id
    
    return response

@app.teardown_request
def teardown_request(exception):
    if exception:
        app.logger.error(f"Exception during request: {str(exception)}")

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
        app.logger.info("Upload request received")
        
        # Check if the post request has the file part
        if 'docfile' not in request.files:
            app.logger.warning("No file part in request")
            return jsonify({"error": "No file part"}), 400
            
        file = request.files['docfile']
        
        # If user does not select file, browser submits an empty file
        if file.filename == '':
            app.logger.warning("No file selected")
            return jsonify({"error": "No file selected"}), 400
            
        if file and allowed_file(file.filename):
            # Secure the filename and save temporarily
            filename = secure_filename(file.filename)
            temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4()}_{filename}")
            
            try:
                file.save(temp_filepath)
                app.logger.info(f"File saved temporarily: {filename}")
                
                # Convert to JSON
                json_data = convert_docx_to_json(temp_filepath, filename)
                app.logger.info(f"File converted to JSON: {filename}")
                
                # Index in Elasticsearch
                result = es.index(index=ES_INDEX, document=json_data)
                app.logger.info(f"File indexed in Elasticsearch: {filename} (ID: {result['_id']})")
                
                # Clean up the temp file
                os.remove(temp_filepath)
                
                # Return success with document ID
                return jsonify({
                    "success": True, 
                    "message": f"Document '{filename}' uploaded and indexed successfully!",
                    "id": result['_id']
                })
                
            except Exception as e:
                app.logger.error(f"Error processing file {filename}: {str(e)}")
                # Clean up on error if file exists
                if os.path.exists(temp_filepath):
                    os.remove(temp_filepath)
                return jsonify({"error": str(e)}), 500
        else:
            app.logger.warning(f"Invalid file type: {file.filename}")
            return jsonify({"error": "File type not allowed. Please upload a .docx file"}), 400
    
    # GET request returns the upload form
    return render_template('upload.html', logo_path=logo_path)

@app.route('/search')
def search():
    query = request.args.get('q', '')
    
    if not query:
        return jsonify({"hits": []})
    
    app.logger.info(f"Search query: {query}")
    
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
            
        app.logger.info(f"Search results: {len(hits)} hits for query '{query}'")
        return jsonify({"hits": hits})
        
    except Exception as e:
        app.logger.error(f"Search error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/list-all')
def list_all():
    try:
        app.logger.info("List all documents request")
        
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
            
        app.logger.info(f"Listed {len(hits)} documents")
        return jsonify({"hits": hits})
        
    except Exception as e:
        app.logger.error(f"List all error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/download/<doc_id>')
def download_document(doc_id):
    try:
        app.logger.info(f"Download request for document ID: {doc_id}")
        
        # Get the document from Elasticsearch
        doc = es.get(index=ES_INDEX, id=doc_id)
        
        if not doc or not doc.get('_source'):
            app.logger.warning(f"Document not found: {doc_id}")
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
        
        app.logger.info(f"Downloading document: {filename}")
        
        # Create a downloadable response
        response = Response(content)
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Type'] = 'text/plain; charset=utf-8'
        
        return response
        
    except Exception as e:
        app.logger.error(f"Download error: {str(e)}")
        return f"Error retrieving document: {str(e)}", 500

@app.route('/download-json/<doc_id>')
def download_json(doc_id):
    try:
        app.logger.info(f"Download JSON request for document ID: {doc_id}")
        
        # Get the document from Elasticsearch
        doc = es.get(index=ES_INDEX, id=doc_id)
        
        if not doc or not doc.get('_source'):
            app.logger.warning(f"Document not found: {doc_id}")
            return "Document not found", 404
        
        # Get the document source
        source = doc['_source']
        
        # Determine the filename
        base_filename = source.get('title', f"document_{doc_id}")
        filename = f"{base_filename}.json"
        
        app.logger.info(f"Downloading JSON: {filename}")
        
        # Create a downloadable response with the full JSON
        response = Response(json.dumps(source, indent=2))
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        
        return response
        
    except Exception as e:
        app.logger.error(f"Download JSON error: {str(e)}")
        return f"Error retrieving document: {str(e)}", 500

@app.route('/metrics')
def metrics():
    try:
        # Gather basic application metrics
        app_metrics = {
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'host': socket.gethostname(),
            'service': 'mimiketech-search',
            'uptime_seconds': time.time() - app.start_time,
            'memory_usage_mb': psutil.Process().memory_info().rss / 1024 / 1024,
            'cpu_percent': psutil.Process().cpu_percent(),
            'total_requests': app.request_count,
            'active_requests': len(app.active_requests)
        }
        
        # Send to Elasticsearch
        es.index(index='mimiketech-metrics', document=app_metrics)
        app.logger.info("Metrics collected and sent to Elasticsearch")
        
        return jsonify(app_metrics)
    except Exception as e:
        app.logger.error(f"Metrics error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/test-logging')
def test_logging():
    """Route to test different logging levels"""
    app.logger.debug("This is a debug message")
    app.logger.info("This is an info message")
    app.logger.warning("This is a warning message")
    app.logger.error("This is an error message")
    
    try:
        # Deliberately cause an error
        x = 1 / 0
    except Exception as e:
        app.logger.exception(f"This is an exception: {str(e)}")
    
    return "Logging test complete, check Elasticsearch and log files"

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Create CSS file for common styles
    css_content = '''
    /* CSS content here - same as before */
    '''
    
    # Create the CSS file
    os.makedirs(os.path.join(STATIC_FOLDER, 'css'), exist_ok=True)
    with open(os.path.join(STATIC_FOLDER, 'css', 'style.css'), 'w') as f:
        f.write(css_content)
    
    # Create the upload template
    upload_template = '''
    <!-- HTML content here - same as before -->
    '''
    
    # Update the main HTML template to include upload link
    html_template = '''
    <!-- HTML content here - same as before -->
    '''
    
    # Create error template
    es_error_template = '''
    <!-- HTML content here - same as before -->
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