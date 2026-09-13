import os
import io
import json
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "kunci_rahasia_bebas_diubah_123")

# Samakan scope dengan auth.py agar tidak error invalid_scope
SCOPES = ['https://www.googleapis.com/auth/drive']
TOKEN_FILE = 'token.json'

FOLDER_PRIBADI_ID = '1kuQoyg8odOQDftGIJOYrnuiHnHN6GzfI'
FOLDER_KELUARGA_ID = '1wlAgBsKD_VunAOq_WbDlDUcYLEjkc8tl'

FOLDERS = {
    'pribadi': {
        'name': 'Folder Pribadi',
        'id': FOLDER_PRIBADI_ID,
        'icon': 'fa-user-shield',
        'desc': 'Penyimpanan khusus dokumen dan berkas pribadi'
    },
    'keluarga': {
        'name': 'Folder Keluarga',
        'id': FOLDER_KELUARGA_ID,
        'icon': 'fa-users',
        'desc': 'Penyimpanan bersama foto, video, dan kenangan keluarga'
    }
}

def get_drive_service():
    creds = None
    
    # 1. Cek dari Environment Variable (Untuk Vercel)
    token_json_env = os.environ.get('GOOGLE_TOKEN_JSON')
    if token_json_env:
        try:
            token_info = json.loads(token_json_env)
            creds = Credentials.from_authorized_user_info(token_info, SCOPES)
        except Exception as e:
            print(f"Gagal memuat GOOGLE_TOKEN_JSON: {e}")

    # 2. Cek dari file lokal token.json (Untuk jalan di laptop)
    if not creds and os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            print(f"Gagal memuat token.json: {e}")

    if not creds:
        return None

    # Refresh token bila kedaluwarsa
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Simpan pembaruan hanya jika file lokal ada
            if os.path.exists(TOKEN_FILE):
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
        except Exception as e:
            print(f"Gagal refresh token: {e}")
            return None

    return build('drive', 'v3', credentials=creds)

@app.route('/')
def root():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    service = get_drive_service()
    images = []
    if service:
        try:
            query = f"'{FOLDER_KELUARGA_ID}' in parents and trashed = false and mimeType contains 'image/'"
            results = service.files().list(
                q=query,
                fields="files(id, name, mimeType, size, createdTime, thumbnailLink, webViewLink)",
                orderBy="createdTime desc",
                pageSize=50
            ).execute()
            images = results.get('files', [])
        except Exception as e:
            flash(f"Gagal memuat foto galeri: {str(e)}", "error")
    else:
        flash("Koneksi Google Drive belum terhubung. Pastikan token.json sudah dibuat!", "error")

    return render_template('dashboard.html', active_page='dashboard', images=images, folders=FOLDERS)

@app.route('/image/<file_id>')
def serve_image(file_id):
    service = get_drive_service()
    if not service:
        return "Unauthorized", 401
    try:
        req = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, req)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        fh.seek(0)
        
        meta = service.files().get(fileId=file_id, fields='mimeType').execute()
        return send_file(fh, mimetype=meta.get('mimeType', 'image/jpeg'))
    except Exception:
        return "Image not found", 404

@app.route('/rename/<file_id>', methods=['POST'])
def rename_file(file_id):
    new_name = request.form.get('new_name', '').strip()
    if not new_name:
        flash("Nama file tidak boleh kosong!", "error")
        return redirect(url_for('dashboard'))

    service = get_drive_service()
    if not service:
        flash("Otorisasi token tidak valid!", "error")
        return redirect(url_for('dashboard'))

    try:
        current_file = service.files().get(fileId=file_id, fields='name').execute()
        curr_name = current_file.get('name', '')
        if '.' in curr_name:
            ext = curr_name.rsplit('.', 1)[1]
            if not new_name.lower().endswith(f".{ext.lower()}"):
                new_name = f"{new_name}.{ext}"

        service.files().update(
            fileId=file_id,
            body={'name': new_name}
        ).execute()

        flash(f"Nama berkas berhasil diubah menjadi '{new_name}'.", "success")
    except Exception as e:
        flash(f"Gagal mengubah nama berkas: {str(e)}", "error")

    return redirect(url_for('dashboard'))

@app.route('/folder/<category>')
def folder_view(category):
    if category not in FOLDERS:
        return redirect(url_for('folder_view', category='keluarga'))
    return render_template('index.html', active_category=category, active_page='upload', folders=FOLDERS)

@app.route('/upload/<category>', methods=['POST'])
def upload_file(category):
    if category not in FOLDERS:
        flash("Kategori folder tidak valid!", "error")
        return redirect(url_for('root'))

    target_folder_id = FOLDERS[category]['id']

    if 'file' not in request.files:
        flash("Pilih berkas terlebih dahulu!", "error")
        return redirect(url_for('folder_view', category=category))
    
    file = request.files['file']
    if file.filename == '':
        flash("Nama berkas kosong!", "error")
        return redirect(url_for('folder_view', category=category))

    try:
        service = get_drive_service()
        if not service:
            flash("Kunci token.json tidak ditemukan atau tidak valid!", "error")
            return redirect(url_for('folder_view', category=category))

        file_metadata = {
            'name': file.filename,
            'parents': [target_folder_id]
        }

        media = MediaIoBaseUpload(
            file.stream, 
            mimetype=file.mimetype or 'application/octet-stream', 
            resumable=True
        )

        service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name'
        ).execute()

        flash(f"Berhasil! Berkas '{file.filename}' tersimpan di {FOLDERS[category]['name']}.", "success")
        if category == 'keluarga':
            return redirect(url_for('dashboard'))
    except Exception as e:
        flash(f"Gagal upload: {str(e)}", "error")

    return redirect(url_for('folder_view', category=category))

# Handler untuk runtime serverless Vercel
# Vercel mengekspos WSGI callable bernama 'app'
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)