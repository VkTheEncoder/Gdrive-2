from __future__ import annotations
import html
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from .db import pop_state, save_creds
from .drive import exchange_code_for_creds

app = FastAPI(title="GDrive Telegram Bot OAuth")

@app.get("/", response_class=PlainTextResponse)
def root():
    return "OK"

@app.get("/oauth/callback", response_class=HTMLResponse)
def oauth_callback(request: Request, state: str = "", code: str = "", error: str = ""):
    if error:
        return HTMLResponse(f"<h3>Google OAuth Error:</h3><pre>{html.escape(error)}</pre>", status_code=400)
    user_id = pop_state(state)
    if not user_id:
        return HTMLResponse("<h3>Invalid or expired OAuth state.</h3>", status_code=400)
    try:
        email, creds_json = exchange_code_for_creds(state, code)
        save_creds(user_id, email, creds_json)
        return HTMLResponse(f"""
            <h3>Connected as {html.escape(email)}</h3>
            <p>You can close this window and return to Telegram.</p>
        """)
    except Exception as e:
        return HTMLResponse(f"<h3>Token Exchange Failed:</h3><pre>{html.escape(str(e))}</pre>", status_code=500)
