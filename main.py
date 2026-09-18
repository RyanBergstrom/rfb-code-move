from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
import os
import re

app = FastAPI()
UPLOAD_DIR = os.path.join(os.environ.get("TEMP", "/tmp"), "rfb-uploads")
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB

os.makedirs(UPLOAD_DIR, exist_ok=True)

# in-memory record of the last uploaded file
_last_file = {"path": None, "name": None}

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>File Push</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: system-ui, sans-serif; background: #111; color: #eee; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
        .container { background: #1a1a1a; padding: 2rem; border-radius: 12px; width: 420px; box-shadow: 0 4px 24px rgba(0,0,0,0.4); }
        h1 { font-size: 1.4rem; margin-bottom: 1.5rem; text-align: center; }
        .section { margin-bottom: 1.5rem; padding: 1rem; border: 1px solid #333; border-radius: 8px; }
        .section h2 { font-size: 0.9rem; color: #888; margin-bottom: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
        input[type=file] { width: 100%; margin-bottom: 0.75rem; color: #eee; }
        button { width: 100%; padding: 0.6rem; background: #2563eb; color: white; border: none; border-radius: 6px; font-size: 0.95rem; cursor: pointer; }
        button:hover { background: #1d4ed8; }
        button:disabled { background: #333; cursor: not-allowed; }
        .download-btn { background: #16a34a; margin-top: 0.75rem; }
        .download-btn:hover { background: #15803d; }
        .status { margin-top: 0.75rem; font-size: 0.85rem; color: #aaa; min-height: 1.2em; }
        .error { color: #ef4444; }
        .warning { background: #1c1917; border: 1px solid #78350f; border-radius: 6px; padding: 0.75rem; margin-bottom: 1.5rem; font-size: 0.8rem; color: #fbbf24; }
    </style>
</head>
<body>
    <div class="container">
        <h1>File Push</h1>
        <div class="warning">
            Files are temporary and lost on server restart. Download promptly after uploading.
        </div>
        <div class="section">
            <h2>Upload</h2>
            <input type="file" id="fileInput">
            <button id="uploadBtn" onclick="uploadFile()">Upload</button>
            <div class="status" id="uploadStatus"></div>
        </div>
        <div class="section">
            <h2>Download</h2>
            <button class="download-btn" id="downloadBtn" onclick="downloadFile()">Download Last File</button>
            <div class="status" id="downloadStatus"></div>
        </div>
    </div>
    <script>
        function uploadFile() {
            var file = document.getElementById('fileInput').files[0];
            if (!file) { document.getElementById('uploadStatus').textContent = 'Select a file first'; return; }
            var status = document.getElementById('uploadStatus');
            var btn = document.getElementById('uploadBtn');
            btn.disabled = true; status.textContent = 'Uploading...'; status.className = 'status';
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/upload?filename=' + encodeURIComponent(file.name));
            xhr.onload = function() {
                if (xhr.status === 200) {
                    var res = JSON.parse(xhr.responseText);
                    status.textContent = 'Uploaded: ' + res.filename + ' (' + res.size_bytes + ' bytes)';
                } else {
                    status.textContent = 'Upload failed: ' + xhr.statusText;
                    status.className = 'status error';
                }
                btn.disabled = false;
            };
            xhr.onerror = function() { status.textContent = 'Upload failed'; status.className = 'status error'; btn.disabled = false; };
            xhr.send(file);
        }
        function downloadFile() {
            var status = document.getElementById('downloadStatus');
            var btn = document.getElementById('downloadBtn');
            status.textContent = 'Downloading...'; status.className = 'status';
            btn.disabled = true;
            var xhr = new XMLHttpRequest();
            xhr.open('GET', '/download');
            xhr.responseType = 'blob';
            xhr.onload = function() {
                if (xhr.status === 200) {
                    var disposition = xhr.getResponseHeader('Content-Disposition');
                    var filename = 'download';
                    if (disposition) {
                        var match = disposition.match(/filename="?([^"]+)"?/);
                        if (match) filename = match[1];
                    }
                    var a = document.createElement('a');
                    a.href = URL.createObjectURL(xhr.response);
                    a.download = filename;
                    a.click();
                    URL.revokeObjectURL(a.href);
                    status.textContent = 'Downloaded: ' + filename;
                } else {
                    status.textContent = 'No file available to download';
                    status.className = 'status error';
                }
                btn.disabled = false;
            };
            xhr.onerror = function() { status.textContent = 'Download failed'; status.className = 'status error'; btn.disabled = false; };
            xhr.send();
        }
    </script>
</body>
</html>"""


@app.get("/")
async def index():
    return HTMLResponse(INDEX_HTML)


@app.post("/upload")
async def upload_code(request: Request, filename: str = "upload.bin"):
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
    dest = os.path.join(UPLOAD_DIR, filename)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 500 MB)")

    received = 0
    with open(dest, "wb") as f:
        async for chunk in request.stream():
            received += len(chunk)
            if received > MAX_UPLOAD_SIZE:
                os.remove(dest)
                raise HTTPException(status_code=413, detail="File too large (max 500 MB)")
            f.write(chunk)

    _last_file["path"] = dest
    _last_file["name"] = filename
    return {"status": "received", "filename": filename, "size_bytes": os.path.getsize(dest)}


@app.get("/download")
async def download_code():
    if not _last_file["path"] or not os.path.exists(_last_file["path"]):
        raise HTTPException(status_code=404, detail="No file available for download")
    return FileResponse(_last_file["path"], media_type="application/octet-stream", filename=_last_file["name"])