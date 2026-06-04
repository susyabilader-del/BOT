"""Geciken işlemler için bayi gruplarına push mesaj gönderme modülü."""

import logging
from datetime import datetime
from pyrogram import Client
from api_client import RussPaymentAPI
from config import Config

logger = logging.getLogger(__name__)


class TransactionPusher:
    """API'den geciken işlemleri tespit edip bayi gruplarına bildirim gönderir."""

    def __init__(self, pyrogram_client: Client):
        self.client = pyrogram_client
        self.api = RussPaymentAPI()
        self.delay_threshold = Config.DELAY_THRESHOLD_MINUTES
        # Son gönderilen bildirimleri takip et (tekrar göndermemek için)
        self._notified_transactions = set()

    async def check_and_push_delayed(self):
        """
        Geciken işlemleri kontrol et ve bayi gruplarına bildirim gönder.
        Bu metod zamanlayıcı tarafından periyodik olarak çağrılır.
        """
        try:
            delayed = await self.api.get_delayed_transactions(
                max_age_minutes=self.delay_threshold
            )

            if not delayed:
                logger.debug("Geciken işlem yok")
                return {"pushed": 0, "total_delayed": 0}

            pushed_count = 0
            for tx in delayed:
                tx_id = tx.get("transactionId") or tx.get("transaction_id") or tx.get("id", "?")

                # Daha önce bildirilmişse atla
                if tx_id in self._notified_transactions:
                    continue

                # Bildirim mesajı oluştur
                message = self._format_delay_message(tx)

                # Tüm bayi gruplarına gönder
                for group_id in Config.get_source_groups():
                    try:
                        chat_id = int(group_id) if group_id.lstrip("-").isdigit() else group_id
                        await self.client.send_message(chat_id, message)
                        pushed_count += 1
                    except Exception as e:
                        logger.error(f"Push mesaj hatası ({group_id}): {e}")

                self._notified_transactions.add(tx_id)

            logger.info(f"Push bildirim: {pushed_count} mesaj gönderildi ({len(delayed)} geciken işlem)")

            # Eski bildirimleri temizle (1000'den fazla birikmesin)
            if len(self._notified_transactions) > 1000:
                self._notified_transactions = set(list(self._notified_transactions)[-500:])

            return {"pushed": pushed_count, "total_delayed": len(delayed)}

        except Exception as e:
            logger.error(f"Push kontrol hatası: {e}", exc_info=True)
            return {"pushed": 0, "total_delayed": 0, "error": str(e)}

    async def push_to_specific_groups(self, message, group_ids=None):
        """Belirli gruplara mesaj gönder."""
        if group_ids is None:
            group_ids = Config.get_source_groups()

        sent = 0
        for group_id in group_ids:
            try:
                chat_id = int(group_id) if group_id.lstrip("-").isdigit() else group_id
                await self.client.send_message(chat_id, message)
                sent += 1
            except Exception as e:
                logger.error(f"Mesaj gönderme hatası ({group_id}): {e}")

        return sent

    def _format_delay_message(self, tx):
        """Geciken işlem için bildirim mesajı formatla."""
        tx_id = tx.get("transactionId") or tx.get("transaction_id") or tx.get("id", "?")
        amount = tx.get("amount", "?")
        player_name = tx.get("playerFullName") or tx.get("player_full_name") or "?"
        player_id = tx.get("playerPlayerId") or tx.get("player_player_id") or "?"
        status = tx.get("status", "PENDING")
        age_minutes = tx.get("_age_minutes", "?")
        tx_type = "Çekim" if "wd_" in str(tx_id) or "withdraw" in str(tx.get("type", "")).lower() else "Yatırım"

        msg = (
            f"⚠️ GECİKEN İŞLEM UYARISI\n"
            f"{'━' * 30}\n"
            f"🔹 Tür: {tx_type}\n"
            f"🔹 İşlem ID: {tx_id}\n"
            f"🔹 Müşteri: {player_name}\n"
            f"🔹 Müşteri ID: {player_id}\n"
            f"🔹 Tutar: ₺{amount:,.2f}\n" if isinstance(amount, (int, float)) else
            f"⚠️ GECİKEN İŞLEM UYARISI\n"
            f"{'━' * 30}\n"
            f"🔹 Tür: {tx_type}\n"
            f"🔹 İşlem ID: {tx_id}\n"
            f"🔹 Müşteri: {player_name}\n"
            f"🔹 Müşteri ID: {player_id}\n"
            f"🔹 Tutar: {amount}\n"
        )
        msg += (
            f"🔹 Durum: {status}\n"
            f"🔹 Bekleme: {age_minutes} dk\n"
            f"{'━' * 30}\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
        )
        return msg

    def clear_notification_cache(self):
        """Bildirim önbelleğini temizle (gün sonu vb.)"""
        self._notified_transactions.clear()
        logger.info("Bildirim önbelleği temizlendi")
