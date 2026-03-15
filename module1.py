import os
import io
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from pymongo import MongoClient
from googleapiclient.http import MediaIoBaseDownload
import streamlit as st

# --- Configuration (Updated for TOML) ---
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# 1. Pull the entire dictionary from secrets
# No more file paths!
SERVICE_ACCOUNT_FILE = st.secrets["gcp_service_account"]
FOLDER_ID = st.secrets["gfolder_id"]["folder_id"]
MONGO_URI = st.secrets["mongo"]["uri"]


def get_latest_unprocessed_file(service, tracker_collection):
    # (This function remains largely the same)
    query = f"'{FOLDER_ID}' in parents and mimeType = 'text/csv' and trashed = false"
    results = (
        service.files()
        .list(
            q=query, orderBy="modifiedTime desc", pageSize=100, fields="files(id, name)"
        )
        .execute()
    )

    files = results.get("files", [])
    if not files:
        st.warning("No CSV files found in folder.")
        return None, None

    for file in files:
        file_id = file["id"]
        file_name = file["name"]
        if tracker_collection.find_one({"drive_id": file_id}):
            continue
        return file_id, file_name

    return None, None


def download_and_sync():
    # --- CHANGE 1: Use 'from_service_account_info' instead of '_file' ---
    creds = service_account.Credentials.from_service_account_info(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build("drive", "v3", credentials=creds)

    client = MongoClient(MONGO_URI)
    db = client["my_database"]
    tracker = db["processed_files"]
    collection = db["latest_data"]

    file_id, file_name = get_latest_unprocessed_file(service, tracker)

    if file_id:
        st.info(f"Downloading: {file_name}...")
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while done is False:
            status, done = downloader.next_chunk()

        fh.seek(0)
        df = pd.read_csv(fh)
        df.columns = df.columns.str.strip()

        data_dict = df.to_dict("records")
        if data_dict:
            collection.insert_many(data_dict)
            tracker.insert_one(
                {
                    "drive_id": file_id,
                    "file_name": file_name,
                    "sync_date": pd.Timestamp.now(),
                }
            )
            st.success(f"Successfully synced {len(data_dict)} rows from {file_name}.")
    else:
        st.write("Everything is up to date!")

    client.close()


if __name__ == "__main__":
    download_and_sync()
