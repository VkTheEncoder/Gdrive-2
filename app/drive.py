from __future__ import annotations
import json
import time
from typing import Callable, Optional, Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import Flow

from .config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, OAUTH_REDIRECT_URI, CHUNK_SIZE
from .db import save_creds, load_creds, get_folder, set_folder
from .utils import fmt_progress

SCOPES = ["https://www.googleapis.com/auth/drive.file", "openid", "email", "profile"]

def _client_config():
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "project_id": "gdrive-telegram-bot",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uris": [OAUTH_REDIRECT_URI],
        }
    }

def build_flow(state: str) -> Flow:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = OAUTH_REDIRECT_URI
    flow.params["access_type"] = "offline"
    flow.params["include_granted_scopes"] = "true"
    flow.params["state"] = state
    return flow

def exchange_code_for_creds(state: str, code: str) -> Tuple[str, str]:
    flow = build_flow(state)
    flow.fetch_token(code=code)
    creds = flow.credentials
    # Fetch email
    email = creds.id_token.get("email") if creds.id_token else "unknown"
    return email, creds.to_json()

def get_service_for_user(user_id: int):
    data = load_creds(user_id)
    if not data:
        return None
    _, creds_json = data
    creds = Credentials.from_authorized_user_info(json.loads(creds_json), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh_request = None  # googleapiclient handles refresh automatically
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return service, creds

def ensure_default_folder(service, user_id: int) -> str:
    folder_id = get_folder(user_id)
    if folder_id:
        return folder_id
    # Create default folder
    meta = {"name": "Telegram Bot Uploads", "mimeType": "application/vnd.google-apps.folder"}
    folder = service.files().create(body=meta, fields="id").execute()
    folder_id = folder["id"]
    set_folder(user_id, folder_id)
    return folder_id

def upload_with_progress(
    service, user_id: int, file_path: str, file_name: str, mime: Optional[str],
    status_updater: Callable[[str], None]
) -> str:
    folder_id = ensure_default_folder(service, user_id)
    media = MediaFileUpload(file_path, mimetype=mime, chunksize=CHUNK_SIZE, resumable=True)
    body = {"name": file_name, "parents": [folder_id]}
    req = service.files().create(body=body, media_body=media, fields="id, webViewLink, webContentLink")

    start = time.time()
    last_bytes = 0
    uploaded = 0
    total = media.size() or 0

    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            uploaded = int(status.resumable_progress)
            elapsed = time.time() - start
            speed = (uploaded - last_bytes) / (elapsed if elapsed > 0 else 1)
            last_bytes = uploaded
            eta = (total - uploaded) / (speed if speed > 0 else 1)
            status_updater(fmt_progress("⏫ Uploading", uploaded, total, speed, eta))

    file_id = resp["id"]
    link = resp.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
    return link
