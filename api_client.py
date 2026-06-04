"""Russ-Payment API Client - Allhavale entegrasyonu."""

import hashlib
import httpx
import logging
from datetime import datetime, date
from config import Config

logger = logging.getLogger(__name__)


class RussPaymentAPI:
    """Russ-Payment Allhavale V3 API istemcisi."""

    def __init__(self):
        self.base_url = Config.PAYMENT_API_URL
        self.api_key = Config.PAYMENT_API_KEY
        self.secret_key = Config.PAYMENT_SECRET_KEY
        self.timeout = 30

    def _headers(self):
        return {
            "x-api-key": self.api_key,
            "x-secret-key": self.secret_key,
            "Content-Type": "application/json",
        }

    def _generate_hash(self, transaction_id, amount):
        """SHA256(apiKey + secretKey + transactionId + amount) hash hesapla."""
        raw = f"{self.api_key}{self.secret_key}{transaction_id}{amount}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get_transactions(self, target_date=None, page=1, limit=500):
        """
        Belirli bir güne ait işlemleri getirir.
        Returns: list of transaction dicts
        """
        if target_date is None:
            target_date = date.today().isoformat()
        elif isinstance(target_date, (date, datetime)):
            target_date = target_date.strftime("%Y-%m-%d")

        url = f"{self.base_url}/allhavale/transactions"
        params = {"date": target_date, "page": page, "limit": limit}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._headers(), params=params)
                response.raise_for_status()
                data = response.json()
                logger.info(f"API: {target_date} tarihli {len(data.get('data', []))} işlem çekildi")
                return data.get("data", data) if isinstance(data, dict) else data
        except httpx.HTTPStatusError as e:
            logger.error(f"API HTTP hatası: {e.response.status_code} - {e.response.text[:200]}")
            raise
        except Exception as e:
            logger.error(f"API bağlantı hatası: {e}")
            raise

    async def get_active_accounts(self):
        """Aktif banka hesaplarını getirir."""
        url = f"{self.base_url}/allhavale/active-accounts"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=self._headers())
                response.raise_for_status()
                data = response.json()
                return data.get("data", data) if isinstance(data, dict) else data
        except Exception as e:
            logger.error(f"API active-accounts hatası: {e}")
            raise

    async def cancel_withdraw(self, transaction_id):
        """Çekim işlemini iptal eder."""
        url = f"{self.base_url}/allhavale/cancel-withdraw-transaction"
        body = {"transactionId": transaction_id}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, headers=self._headers(), json=body)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"API cancel-withdraw hatası: {e}")
            raise

    async def get_pending_transactions(self, target_date=None):
        """
        Bekleyen (henüz onaylanmamış/reddedilmemiş) işlemleri filtreler.
        API'den gelen tüm işlemleri alıp status'a göre filtreler.
        """
        transactions = await self.get_transactions(target_date)
        pending = []
        for tx in transactions:
            status = tx.get("status", "").upper()
            if status in ("PENDING", "WAITING", "PROCESSING", ""):
                pending.append(tx)
        return pending

    async def get_delayed_transactions(self, max_age_minutes=15, target_date=None):
        """
        Geciken işlemleri tespit eder.
        max_age_minutes dakikadan fazla süredir bekleyen işlemler.
        """
        transactions = await self.get_transactions(target_date)
        now = datetime.now()
        delayed = []

        for tx in transactions:
            status = tx.get("status", "").upper()
            if status not in ("APPROVED", "REJECTED", "CANCELLED"):
                # İşlem hala bekliyor - ne kadar süredir?
                created_at = tx.get("createdAt") or tx.get("created_at") or tx.get("date")
                if created_at:
                    try:
                        if isinstance(created_at, str):
                            # ISO format veya diğer formatları dene
                            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                                       "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                                try:
                                    created = datetime.strptime(created_at, fmt)
                                    break
                                except ValueError:
                                    continue
                            else:
                                continue
                        else:
                            continue

                        age_minutes = (now - created).total_seconds() / 60
                        if age_minutes >= max_age_minutes:
                            tx["_age_minutes"] = int(age_minutes)
                            delayed.append(tx)
                    except Exception:
                        continue

        logger.info(f"Geciken işlemler: {len(delayed)} adet ({max_age_minutes}+ dk)")
        return delayed

    async def get_transaction_status(self, transaction_id, target_date=None):
        """Belirli bir işlemin durumunu sorgular."""
        transactions = await self.get_transactions(target_date)
        for tx in transactions:
            tx_id = tx.get("transactionId") or tx.get("transaction_id") or tx.get("id")
            if str(tx_id) == str(transaction_id):
                return tx
        return None

    async def verify_transaction_consistency(self, transaction_id, expected_status, target_date=None):
        """
        Bir işlemin API'deki durumunu beklenen durumla karşılaştırır.
        Returns: dict with 'consistent' bool and 'details'
        """
        tx = await self.get_transaction_status(transaction_id, target_date)
        if not tx:
            return {
                "consistent": False,
                "api_status": "NOT_FOUND",
                "expected_status": expected_status,
                "details": f"İşlem API'de bulunamadı: {transaction_id}"
            }

        api_status = (tx.get("status") or "").upper()
        expected_upper = expected_status.upper()

        # Durum eşleştirme
        consistent = api_status == expected_upper
        return {
            "consistent": consistent,
            "api_status": api_status,
            "expected_status": expected_upper,
            "transaction": tx,
            "details": f"API: {api_status} | Beklenen: {expected_upper} | {'✅ Tutarlı' if consistent else '🔴 TUTARSIZ'}"
        }
