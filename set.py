import asyncio
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import os
import logging
from datetime import datetime, timedelta
import mimetypes
import re


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()


api_id = '' #api ایدی خودتون از تلگرام
api_hash = '' # هش خودتون از تلگرام api
phone = '+98912345678' #شماره خودتون
client = TelegramClient('bot_session', api_id, api_hash)
SCOPES = ['https://www.googleapis.com/auth/drive.file']
SERVICE_ACCOUNT_FILE = 'service-account.json' #اینو تغییر ندید از همین اسم استفاده کنید
PARENT_FOLDER_ID = '' # ایدی فولدر از گوگل درایو
TEMP_DIR = os.path.join(os.path.dirname(__file__), 'temp')
MY_USER_ID = 1234567891 # ایدی عددی


if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)


file_cleanup_queue = {}
initial_confirmation_requests = {}
confirmation_requests = {}

def sanitize_filename(filename):
    return re.sub(r'[^\w\-\_\.]', '_', filename)


def get_drive_service():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


async def upload_to_drive(file_path, file_name, mime_type, event):
    if not os.path.exists(file_path):
        logger.error(f"File {file_path} does not exist.")
        await event.respond('خطا: فایل دانلودشده یافت نشد.')
        return None
    drive_service = get_drive_service()
    file_metadata = {
        'name': file_name,
        'parents': [PARENT_FOLDER_ID]
    }
    try:
        logger.info(f"Starting upload of {file_name} to Google Drive")
        with open(file_path, 'rb') as f:
            media = MediaIoBaseUpload(f, mimetype=mime_type, resumable=True)
            file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
            permission = {'type': 'anyone', 'role': 'reader'}
            drive_service.permissions().create(fileId=file['id'], body=permission).execute()
            file_id = file['id']
            cleanup_time = datetime.now() + timedelta(minutes=30)  # اینجا مشخص میکنید که چه موقع از گوگل درایو پاک شه الان روی نیم ساعته
            file_cleanup_queue[file_id] = cleanup_time
            asyncio.create_task(cleanup_file(file_id, cleanup_time))
            logger.info(f"Upload completed for {file_name}, link generated")
            return file.get('webViewLink')
    except Exception as e:
        logger.error(f"Error uploading to Google Drive: {str(e)}")
        await event.respond(f'خطا در آپلود به Google Drive: {str(e)}')
        return None
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Temporary file {file_path} removed.")


async def cleanup_file(file_id, cleanup_time):
    await asyncio.sleep((cleanup_time - datetime.now()).total_seconds())
    drive_service = get_drive_service()
    try:
        drive_service.files().delete(fileId=file_id).execute()
        logger.info(f"File {file_id} deleted from Google Drive.")
        if file_id in file_cleanup_queue:
            del file_cleanup_queue[file_id]
    except Exception as e:
        logger.error(f"Error deleting file {file_id}: {str(e)}")


async def handle_initial_confirmation(event):
    chat_id = event.chat_id
    if chat_id in initial_confirmation_requests:
        message_id, file_info, original_message = initial_confirmation_requests[chat_id]
        if event.text.lower() == 'بله':
            temp_path = os.path.join(TEMP_DIR, file_info['file_name'])
            try:
                logger.info(f"Starting download of {file_info['file_name']} to {temp_path}")
                await client.download_media(message=original_message, file=temp_path)
                if os.path.exists(temp_path):
                    logger.info(f"Download completed and file exists at {temp_path}, size: {os.path.getsize(temp_path)} bytes")
                else:
                    logger.error(f"Downloaded file {temp_path} not found after download")
                    await event.respond('خطا: فایل دانلودشده یافت نشد.')
                    return
                confirmation_requests[chat_id] = (message_id, file_info)
                await event.respond('آیا لینک این فایل را می‌خواهید؟ ("بله" یا "خیر" را ارسال کنید.)')
            except Exception as e:
                logger.error(f"Error downloading file: {str(e)}")
                await event.respond(f'خطا در دانلود فایل: {str(e)}')
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    logger.info(f"Temporary file {temp_path} removed due to error")
            del initial_confirmation_requests[chat_id]
        elif event.text.lower() == 'خیر':
            await event.respond('دانلود لغو شد.')
            del initial_confirmation_requests[chat_id]
        else:
            await event.respond('لطفاً "بله" یا "خیر" را ارسال کنید.')


async def handle_upload_confirmation(event):
    chat_id = event.chat_id
    if chat_id in confirmation_requests:
        message_id, file_info = confirmation_requests[chat_id]
        if event.text.lower() == 'بله':
            file_path = os.path.join(TEMP_DIR, file_info['file_name'])
            drive_link = await upload_to_drive(file_path, file_info['file_name'], file_info['mime_type'], event)
            if drive_link:
                await event.respond(f'لینک دانلود: {drive_link}')
            del confirmation_requests[chat_id]
        elif event.text.lower() == 'خیر':
            await event.respond('عملیات آپلود لغو شد.')
            file_path = os.path.join(TEMP_DIR, file_info['file_name'])
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Temporary file {file_path} removed.")
            del confirmation_requests[chat_id]
        else:
            await event.respond('لطفاً "بله" یا "خیر" را ارسال کنید.')


@client.on(events.NewMessage)
async def handle_message(event):
    chat_id = event.chat_id
    sender_id = event.sender_id
    logger.info(f"Received message from chat_id {chat_id} by sender_id {sender_id}: {event.to_dict()}")


    if abs(chat_id) != MY_USER_ID:
        logger.info(f"Ignoring message from non-Saved Messages chat {chat_id}")
        return

    if event.text == '/start':
        await event.respond('سلام! هر نوع فایلی (ویدئو، صوت، سند و ...) تا 2 گیگابایت ارسال کنید. ابتدا از شما تأیید دانلود و سپس تأیید آپلود خواسته می‌شود.')
    elif event.document:

        if chat_id in initial_confirmation_requests:
            logger.info(f"New file received, cancelling previous request for chat_id {chat_id}")
            del initial_confirmation_requests[chat_id]
        if chat_id in confirmation_requests:
            file_path = os.path.join(TEMP_DIR, confirmation_requests[chat_id][1]['file_name'])
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Temporary file {file_path} removed due to new file.")
            del confirmation_requests[chat_id]

        file = event.document
        file_name = None
        for attr in file.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                file_name = attr.file_name
                break
        if not file_name:
            extension = mimetypes.guess_extension(file.mime_type) or '.bin'
            file_name = f'file_{file.id}{extension}'
        file_name = sanitize_filename(file_name)
        mime_type = file.mime_type
        file_size = file.size
        logger.info(f"Detected document with id: {file.id}, name: {file_name}, mime_type: {mime_type}, size: {file_size} bytes")
        initial_confirmation_requests[chat_id] = (event.id, {'file_name': file_name, 'mime_type': mime_type}, event.message)
        await event.respond('آیا می‌خواهید این فایل دانلود شود؟ ("بله" یا "خیر" را ارسال کنید.)')
    elif chat_id in initial_confirmation_requests and event.text:
        await handle_initial_confirmation(event)
    elif chat_id in confirmation_requests and event.text:
        await handle_upload_confirmation(event)


async def main():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        logger.error(f"فایل {SERVICE_ACCOUNT_FILE} یافت نشد. لطفاً آن را آپلود کنید.")
        return
    await client.start(phone)
    logger.info("Bot started successfully.")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())