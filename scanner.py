import asyncio
from datetime import datetime, timedelta
from pyrogram import Client
from pyrogram.enums import ChatType
from config import Config
from database import save_message, get_scan_state, update_scan_state
import logging

logger = logging.getLogger(__name__)


class GroupScanner:
    def __init__(self):
        self.client = Client(
            "verifier_session",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            workdir="data"
        )
        self._running = False

    async def start(self):
        await self.client.start()
        logger.info("Pyrogram client başlatıldı")

    async def stop(self):
        self._running = False
        await self.client.stop()
        logger.info("Pyrogram client durduruldu")

    def _parse_group_id(self, group_id_str):
        try:
            return int(group_id_str)
        except ValueError:
            return group_id_str

    async def scan_group(self, group_id, group_type, limit=100):
        """Bir grubu tarar ve yeni mesajları veritabanına kaydeder."""
        chat_id = self._parse_group_id(group_id)
        state = await get_scan_state(group_id)
        last_msg_id = state["last_message_id"] if state else 0

        count = 0
        max_msg_id = last_msg_id

        try:
            async for message in self.client.get_chat_history(chat_id, limit=limit):
                if message.id <= last_msg_id:
                    break

                text = message.text or message.caption or ""
                if not text.strip():
                    continue

                user_id = message.from_user.id if message.from_user else None
                username = message.from_user.username if message.from_user else None

                await save_message(
                    group_id=group_id,
                    group_type=group_type,
                    message_id=message.id,
                    user_id=user_id,
                    username=username,
                    text=text,
                    date=message.date.isoformat()
                )

                max_msg_id = max(max_msg_id, message.id)
                count += 1

        except Exception as e:
            logger.error(f"Grup tarama hatası ({group_id}): {e}")
            raise

        if max_msg_id > last_msg_id:
            await update_scan_state(group_id, max_msg_id)

        logger.info(f"Grup {group_id} ({group_type}): {count} yeni mesaj kaydedildi")
        return count

    async def scan_all_groups(self):
        """Tüm yapılandırılmış grupları tarar."""
        results = {"source": 0, "verify": 0, "source_groups": 0, "verify_groups": 0}

        for group_id in Config.get_source_groups():
            try:
                count = await self.scan_group(group_id, "source")
                results["source"] += count
                results["source_groups"] += 1
            except Exception as e:
                logger.error(f"Kaynak grup tarama hatası ({group_id}): {e}")

        for group_id in Config.get_verify_groups():
            try:
                count = await self.scan_group(group_id, "verify")
                results["verify"] += count
                results["verify_groups"] += 1
            except Exception as e:
                logger.error(f"Doğrulama grubu tarama hatası ({group_id}): {e}")

        return results

    async def search_messages(self, group_id, query, limit=50):
        """Bir grupta belirli bir metni arar."""
        chat_id = self._parse_group_id(group_id)
        results = []

        try:
            async for message in self.client.search_messages(chat_id, query=query, limit=limit):
                text = message.text or message.caption or ""
                results.append({
                    "message_id": message.id,
                    "user_id": message.from_user.id if message.from_user else None,
                    "username": message.from_user.username if message.from_user else None,
                    "text": text,
                    "date": message.date.isoformat()
                })
        except Exception as e:
            logger.error(f"Mesaj arama hatası ({group_id}, query='{query}'): {e}")

        return results

    async def get_user_messages(self, group_id, user_id, limit=50):
        """Belirli bir kullanıcının mesajlarını getirir."""
        chat_id = self._parse_group_id(group_id)
        results = []

        try:
            async for message in self.client.search_messages(chat_id, from_user=user_id, limit=limit):
                text = message.text or message.caption or ""
                if text.strip():
                    results.append({
                        "message_id": message.id,
                        "text": text,
                        "date": message.date.isoformat()
                    })
        except Exception as e:
            logger.error(f"Kullanıcı mesajları hatası ({group_id}, user={user_id}): {e}")

        return results

    async def get_group_info(self, group_id):
        """Grup bilgilerini getirir."""
        chat_id = self._parse_group_id(group_id)
        try:
            chat = await self.client.get_chat(chat_id)
            return {
                "id": chat.id,
                "title": chat.title,
                "type": str(chat.type),
                "members_count": chat.members_count
            }
        except Exception as e:
            logger.error(f"Grup bilgi hatası ({group_id}): {e}")
            return None
