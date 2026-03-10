import os
import json
import logging
from datetime import datetime

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

HEADERS = ["Название", "Описание", "Промпт", "Медиа (file_id)", "Источник", "Дата добавления"]


class SheetsClient:
    def __init__(self):
        self.spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID")
        if not self.spreadsheet_id:
            raise ValueError("GOOGLE_SPREADSHEET_ID environment variable not set!")

        # Load credentials from env var (JSON string) or file
        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if creds_json:
            creds_info = json.loads(creds_json)
        else:
            creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
            with open(creds_file) as f:
                creds_info = json.load(f)

        self.creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        self.service = build("sheets", "v4", credentials=self.creds)
        self.sheet = self.service.spreadsheets()

        self._ensure_headers()

    def _ensure_headers(self):
        """Make sure the sheet has headers in first row"""
        try:
            result = self.sheet.values().get(
                spreadsheetId=self.spreadsheet_id,
                range="A1:F1"
            ).execute()
            values = result.get("values", [])

            if not values or values[0] != HEADERS:
                self.sheet.values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range="A1:F1",
                    valueInputOption="RAW",
                    body={"values": [HEADERS]}
                ).execute()
                logger.info("Headers written to sheet")

                # Format header row
                requests = [{
                    "repeatCell": {
                        "range": {
                            "sheetId": 0,
                            "startRowIndex": 0,
                            "endRowIndex": 1
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.9},
                                "textFormat": {
                                    "bold": True,
                                    "foregroundColor": {"red": 1, "green": 1, "blue": 1}
                                },
                                "horizontalAlignment": "CENTER"
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
                    }
                }, {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": 0,
                            "gridProperties": {"frozenRowCount": 1}
                        },
                        "fields": "gridProperties.frozenRowCount"
                    }
                }]

                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": requests}
                ).execute()

        except Exception as e:
            logger.error(f"Error ensuring headers: {e}")
            raise

    def append_row(self, row_data: list):
        """Append a new row to the sheet"""
        # row_data = [title, description, prompt, media, source]
        # Add timestamp
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        full_row = row_data + [timestamp]

        # Ensure all values are strings, replace empty with "—"
        full_row = [str(v) if v else "—" for v in full_row]

        result = self.sheet.values().append(
            spreadsheetId=self.spreadsheet_id,
            range="A:F",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [full_row]}
        ).execute()

        logger.info(f"Row appended: {result.get('updates', {}).get('updatedRange', 'unknown')}")
        return result
