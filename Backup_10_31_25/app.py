from flask import Flask, send_from_directory, jsonify
from pathlib import Path
import webbrowser
import threading

# -------------------------------------------------------
# Configuration
# -------------------------------------------------------
APP_ROOT = Path(__file__).parent
PORT = 5500

app = Flask(__name__)

# -------------------------------------------------------
# Routes
# -------------------------------------------------------

@app.route('/')
def index():
    """Serve the main dashboard HTML."""
    return send_from_directory(APP_ROOT, 'tp_rules_dashboard2.html')

@app.route('/<path:filename>')
def serve_file(filename):
    """Serve any static file (html, css, js, json)."""
    file_path = APP_ROOT / filename
    if file_path.exists() and file_path.is_file():
        return send_from_directory(APP_ROOT, filename)
    return jsonify({"error": "File not found"}), 404

# -------------------------------------------------------
# Auto-launch browser
# -------------------------------------------------------
def open_browser():
    """Open browser after server starts."""
    webbrowser.open_new(f'http://127.0.0.1:{PORT}/')

def run():
    """Run the Flask application."""
    print(f"Starting TP Dashboard server...")
    print(f"Dashboard will open at http://127.0.0.1:{PORT}")
    print(f"Press Ctrl+C to stop the server")
    print("-" * 50)
    
    # Launch browser after a short delay
    timer = threading.Timer(1.5, open_browser)
    timer.daemon = True
    timer.start()
    
    # Run Flask
    app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False)

# -------------------------------------------------------
if __name__ == '__main__':
    run()