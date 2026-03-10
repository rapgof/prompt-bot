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

HEADERS = ["Название", "Описание", "Промпт", "Фото", "Источник", "Дата добавления"]

# Colors
HEADER_BG    = {"red": 0.20, "green": 0.20, "blue": 0.20}  # dark
HEADER_FG    = {"red": 1.0,  "green": 1.0,  "blue": 1.0}
ROW_WHITE    = {"red": 1.0,  "green": 1.0,  "blue": 1.0}
ROW_GRAY     = {"red": 0.95, "green": 0.95, "blue": 0.95}


class SheetsClient:
    def __init__(self):
        self.spreadsheet_id = os.environ.get("GOOGLE_SPREADSHEET_ID")
        if not self.spreadsheet_id:
            raise ValueError("GOOGLE_SPREADSHEET_ID not set!")

        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if creds_json:
            creds_info = json.loads(creds_json)
        else:
            with open(os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")) as f:
                creds_info = json.load(f)

        self.creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        self.service = build("sheets", "v4", credentials=self.creds)
        self.sheet = self.service.spreadsheets()
        self._ensure_headers()

    def _ensure_headers(self):
        try:
            result = self.sheet.values().get(
                spreadsheetId=self.spreadsheet_id, range="A1:F1"
            ).execute()
            values = result.get("values", [])
            if not values or values[0] != HEADERS:
                self.sheet.values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range="A1:F1",
                    valueInputOption="RAW",
                    body={"values": [HEADERS]}
                ).execute()
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": [
                        {   # Header style
                            "repeatCell": {
                                "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
                                "cell": {"userEnteredFormat": {
                                    "backgroundColor": HEADER_BG,
                                    "textFormat": {"bold": True, "foregroundColor": HEADER_FG, "fontSize": 11},
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                }},
                                "fields": "userEnteredFormat"
                            }
                        },
                        {   # Freeze header
                            "updateSheetProperties": {
                                "properties": {"sheetId": 0, "gridProperties": {"frozenRowCount": 1}},
                                "fields": "gridProperties.frozenRowCount"
                            }
                        },
                        {   # Header row height
                            "updateDimensionProperties": {
                                "range": {"sheetId": 0, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                                "properties": {"pixelSize": 36},
                                "fields": "pixelSize"
                            }
                        }
                    ]}
                ).execute()
                logger.info("Headers written")
        except Exception as e:
            logger.error(f"Headers error: {e}")
            raise

    def _get_row_count(self):
        """Get current number of rows with data"""
        try:
            result = self.sheet.values().get(
                spreadsheetId=self.spreadsheet_id, range="A:A"
            ).execute()
            return len(result.get("values", []))
        except:
            return 1

    def append_row(self, row_data: list):
        """Append row and apply alternating color"""
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        full_row = row_data + [timestamp]
        full_row = [str(v) if v else "—" for v in full_row]

        # Append data
        result = self.sheet.values().append(
            spreadsheetId=self.spreadsheet_id,
            range="A:F",
            valueInputOption="USER_ENTERED",  # allows =HYPERLINK formula
            insertDataOption="INSERT_ROWS",
            body={"values": [full_row]}
        ).execute()

        # Get the row index that was just added
        updated_range = result.get("updates", {}).get("updatedRange", "")
        # Parse row number from range like "Лист1!A5:F5"
        try:
            row_num = int(updated_range.split("A")[1].split(":")[0]) - 1  # 0-indexed
        except:
            row_num = self._get_row_count() - 1

        # Alternating row color (row_num=1 is first data row → white)
        color = ROW_WHITE if row_num % 2 == 1 else ROW_GRAY

        self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id,
            body={"requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": 0,
                            "startRowIndex": row_num,
                            "endRowIndex": row_num + 1
                        },
                        "cell": {"userEnteredFormat": {
                            "backgroundColor": color,
                            "verticalAlignment": "MIDDLE",
                            "wrapStrategy": "WRAP",
                        }},
                        "fields": "userEnteredFormat(backgroundColor,verticalAlignment,wrapStrategy)"
                    }
                },
                {   # Row height
                    "updateDimensionProperties": {
                        "range": {"sheetId": 0, "dimension": "ROWS",
                                  "startIndex": row_num, "endIndex": row_num + 1},
                        "properties": {"pixelSize": 48},
                        "fields": "pixelSize"
                    }
                }
            ]}
        ).execute()

        logger.info(f"Row appended at index {row_num}")
        return result
