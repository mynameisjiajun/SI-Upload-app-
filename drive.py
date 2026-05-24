import json
import logging
import mimetypes
import os
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]
ROOT_FOLDER_NAME = "SI Archive"


class DriveService:
    def __init__(self):
        raw = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
        info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        self._svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        self._root_id: str | None = None

    # ── Folder helpers ────────────────────────────────────────────────────────

    def _find_or_create_folder(self, name: str, parent_id: str) -> str:
        safe_name = name.replace("'", "\\'")
        q = (
            f"name='{safe_name}' "
            f"and mimeType='application/vnd.google-apps.folder' "
            f"and '{parent_id}' in parents "
            f"and trashed=false"
        )
        results = self._svc.files().list(q=q, fields="files(id)").execute()
        files = results.get("files", [])
        if files:
            return files[0]["id"]

        body = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        folder = self._svc.files().create(body=body, fields="id").execute()
        logger.info("Created folder '%s' (id=%s)", name, folder["id"])
        return folder["id"]

    def _root_folder_id(self) -> str:
        if self._root_id:
            return self._root_id

        # Prefer an explicit folder ID from env so the bot writes into a
        # specific shared folder rather than the service-account's Drive root.
        env_id = os.getenv("DRIVE_ROOT_FOLDER_ID", "").strip()
        if env_id:
            self._root_id = env_id
            return self._root_id

        self._root_id = self._find_or_create_folder(ROOT_FOLDER_NAME, "root")
        return self._root_id

    def get_or_create_folder(self, date_str: str, sermon_title: str) -> str:
        """
        Returns the Drive folder ID for:
          SI Archive / 2026 / May / 24 May - Grace In Suffering
        Creates any missing folders along the way.
        """
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        year_name = dt.strftime("%Y")                         # "2026"
        month_name = dt.strftime("%B")                        # "May"
        day_name = f"{dt.strftime('%d %b')} - {sermon_title}"  # "24 May - Grace In Suffering"

        root = self._root_folder_id()
        year_id = self._find_or_create_folder(year_name, root)
        month_id = self._find_or_create_folder(month_name, year_id)
        sermon_id = self._find_or_create_folder(day_name, month_id)
        return sermon_id

    # ── Upload ────────────────────────────────────────────────────────────────

    def upload_file(self, local_path: str, drive_filename: str, folder_id: str) -> tuple[str, str]:
        """
        Uploads local_path to Google Drive using a resumable chunked upload.
        Returns (file_id, web_view_link).
        """
        mime_type, _ = mimetypes.guess_type(local_path)
        mime_type = mime_type or "application/octet-stream"

        metadata = {"name": drive_filename, "parents": [folder_id]}
        media = MediaFileUpload(
            local_path,
            mimetype=mime_type,
            resumable=True,
            chunksize=8 * 1024 * 1024,  # 8 MB chunks
        )

        request = self._svc.files().create(
            body=metadata,
            media_body=media,
            fields="id,webViewLink",
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info("Drive upload %.0f%%", status.progress() * 100)

        file_id: str = response["id"]
        web_link: str = response.get(
            "webViewLink", f"https://drive.google.com/file/d/{file_id}/view"
        )
        logger.info("Uploaded '%s' → %s", drive_filename, web_link)
        return file_id, web_link
