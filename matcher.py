"""
Transaction Matcher — Telegram grup mesajları ile API verisini eşleştirir.

Akış:
1. Grup mesajlarından transaction ID/hash çıkar
2. API'den aynı günün işlemlerini çek
3. Hash bazlı eşleştir
4. Tutarsızlıkları raporla (tutar farkı, status farkı, isim farkı)
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from parser import MessageParser, ParsedMessage, IslemTipi
from api_client import RussPaymentAPI

logger = logging.getLogger(__name__)


class EslesmeDurumu(Enum):
    ESLESTI = "eslesti"              # Tam eşleşme (tutar + status OK)
    TUTAR_FARKI = "tutar_farki"      # Hash eşleşti ama tutar farklı
    STATUS_FARKI = "status_farki"    # Hash eşleşti ama durum farklı
    EDIT_YAPILMIS = "edit_yapilmis"  # Tutar editlenerek onaylanmış
    API_BULUNAMADI = "api_bulunamadi"  # Grupta var, API'de yok
    GRUP_BULUNAMADI = "grup_bulunamadi"  # API'de var, grupta yok


@dataclass
class GrupIslemi:
    """Telegram grubundan çıkarılan işlem."""
    transaction_id: str
    musteri_adi: Optional[str] = None
    tutar: Optional[float] = None
    tutar_edit_oncesi: Optional[float] = None
    banka: Optional[str] = None
    platform: Optional[str] = None
    durum: Optional[str] = None  # onayli, red, iptal, bekleyen
    islem_tipi: IslemTipi = IslemTipi.BILINMIYOR
    kaynak_grup: str = ""  # yatirim veya cekim
    mesaj_tarihi: Optional[str] = None
    raw_text: str = ""


@dataclass
class ApiIslemi:
    """API'den gelen işlem."""
    transaction_id: str
    amount: float = 0.0
    player_name: str = ""
    player_id: str = ""
    account_number: str = ""
    status: str = ""  # APPROVED, REJECTED, PENDING, CANCELLED
    created_at: str = ""
    tx_type: str = ""  # deposit veya withdraw


@dataclass
class EslesmeRaporu:
    """Bir eşleşme sonucu."""
    transaction_id: str
    durum: EslesmeDurumu
    grup_verisi: Optional[GrupIslemi] = None
    api_verisi: Optional[ApiIslemi] = None
    tutar_farki: float = 0.0
    aciklama: str = ""


class TransactionMatcher:
    """Grup mesajları ile API verilerini eşleştirir."""

    # Grup durum → API status eşleştirmesi
    DURUM_MAP = {
        "onayli": ["APPROVED"],
        "onaylı": ["APPROVED"],
        "onay": ["APPROVED"],
        "red": ["REJECTED"],
        "reddedildi": ["REJECTED"],
        "iptal": ["CANCELLED"],
        "bekleyen": ["PENDING", "WAITING", "PROCESSING"],
        "beklemede": ["PENDING", "WAITING", "PROCESSING"],
    }

    def __init__(self):
        self.parser = MessageParser()
        self.api = RussPaymentAPI()

    def extract_from_messages(self, messages: List[Dict], kaynak: str = "") -> List[GrupIslemi]:
        """
        Telegram mesaj listesinden transaction ID'li işlemleri çıkarır.
        messages: [{"text": "...", "date": "...", "group": "..."}]
        """
        islemler = []
        seen_ids = set()

        for m in messages:
            text = m.get("text", "")
            if not text:
                continue

            parsed = self.parser.parse(text)

            # Transaction ID/hash olmalı
            tx_id = parsed.islem_hash
            if not tx_id or len(tx_id) < 6:
                continue

            # Aynı ID'yi tekrar ekleme (en son halini tut)
            tx_id_lower = tx_id.lower()
            if tx_id_lower in seen_ids:
                continue
            seen_ids.add(tx_id_lower)

            islem = GrupIslemi(
                transaction_id=tx_id_lower,
                musteri_adi=parsed.musteri_adi,
                tutar=parsed.tutar,
                tutar_edit_oncesi=parsed.tutar_edit_oncesi,
                banka=parsed.banka,
                platform=parsed.platform,
                durum=parsed.durum,
                islem_tipi=parsed.islem_tipi,
                kaynak_grup=kaynak or m.get("group_type", ""),
                mesaj_tarihi=m.get("date", ""),
                raw_text=text[:200],
            )
            islemler.append(islem)

        logger.info(f"Gruptan {len(islemler)} transaction ID çıkarıldı (kaynak: {kaynak})")
        return islemler

    async def fetch_api_transactions(self, target_date=None, days_back=1) -> List[ApiIslemi]:
        """API'den işlemleri çeker ve normalize eder."""
        all_txs = []

        for day_offset in range(days_back):
            d = (date.today() - timedelta(days=day_offset)) if target_date is None else target_date
            if isinstance(d, str):
                d = date.fromisoformat(d)

            try:
                raw_txs = await self.api.get_transactions(target_date=d, limit=500)
                if not raw_txs:
                    continue

                for tx in raw_txs:
                    tx_id = str(tx.get("transactionId") or tx.get("transaction_id") or tx.get("id") or "")
                    if not tx_id:
                        continue

                    api_islem = ApiIslemi(
                        transaction_id=tx_id.lower(),
                        amount=float(tx.get("amount", 0)),
                        player_name=tx.get("playerFullName") or tx.get("player_name") or "",
                        player_id=str(tx.get("playerPlayerId") or tx.get("player_id") or ""),
                        account_number=tx.get("playerAccountNumber") or tx.get("account_number") or "",
                        status=(tx.get("status") or "").upper(),
                        created_at=str(tx.get("createdAt") or tx.get("created_at") or tx.get("date") or ""),
                        tx_type=tx.get("type", ""),
                    )
                    all_txs.append(api_islem)

            except Exception as e:
                logger.error(f"API sorgu hatası ({d}): {e}")

        logger.info(f"API'den {len(all_txs)} işlem çekildi")
        return all_txs

    def match(self, grup_islemleri: List[GrupIslemi], api_islemleri: List[ApiIslemi]) -> List[EslesmeRaporu]:
        """
        Grup ve API verilerini transaction ID bazında eşleştirir.
        Partial match destekler: grup hash'i (8 char) API tx_id'nin prefix'i olabilir.
        """
        raporlar = []

        # API index oluştur - tam ID ve prefix ile
        api_by_id = {}
        api_by_prefix = {}
        for api_tx in api_islemleri:
            api_by_id[api_tx.transaction_id] = api_tx
            # İlk 8 karakteri prefix olarak tut
            prefix = api_tx.transaction_id[:8]
            if prefix not in api_by_prefix:
                api_by_prefix[prefix] = []
            api_by_prefix[prefix].append(api_tx)

        matched_api_ids = set()

        # Grup → API eşleştirme
        for grup_tx in grup_islemleri:
            tx_id = grup_tx.transaction_id

            # Tam eşleşme dene
            api_tx = api_by_id.get(tx_id)

            # Partial: grup hash API ID'nin prefix'i mi?
            if not api_tx:
                candidates = api_by_prefix.get(tx_id[:8], [])
                if len(candidates) == 1:
                    api_tx = candidates[0]
                elif len(candidates) > 1:
                    # Birden fazla eşleşme - tutar bazlı filtrele
                    if grup_tx.tutar:
                        for c in candidates:
                            if abs(c.amount - grup_tx.tutar) < 0.01:
                                api_tx = c
                                break
                    if not api_tx:
                        api_tx = candidates[0]

            if not api_tx:
                # API'de bulunamadı
                raporlar.append(EslesmeRaporu(
                    transaction_id=tx_id,
                    durum=EslesmeDurumu.API_BULUNAMADI,
                    grup_verisi=grup_tx,
                    aciklama=f"Grupta var ama API'de bulunamadı: {tx_id}"
                ))
                continue

            matched_api_ids.add(api_tx.transaction_id)

            # Edit yapılmış mı?
            if grup_tx.islem_tipi == IslemTipi.EDIT_ONAY:
                rapor = self._check_edit(grup_tx, api_tx)
            else:
                rapor = self._compare(grup_tx, api_tx)

            raporlar.append(rapor)

        # API'de var ama grupta yok (opsiyonel)
        for api_tx in api_islemleri:
            if api_tx.transaction_id not in matched_api_ids:
                # Sadece önemli olanları flagle (onaylanmış ama grupta görünmeyen)
                if api_tx.status in ("APPROVED", "REJECTED"):
                    raporlar.append(EslesmeRaporu(
                        transaction_id=api_tx.transaction_id,
                        durum=EslesmeDurumu.GRUP_BULUNAMADI,
                        api_verisi=api_tx,
                        aciklama=f"API'de {api_tx.status} ama grupta mesaj yok"
                    ))

        return raporlar

    def _compare(self, grup: GrupIslemi, api: ApiIslemi) -> EslesmeRaporu:
        """Normal eşleşme karşılaştırması."""
        issues = []

        # Tutar karşılaştır
        tutar_farki = 0.0
        if grup.tutar and api.amount:
            tutar_farki = abs(grup.tutar - api.amount)
            if tutar_farki > 0.01:
                issues.append(f"tutar: grup ₺{grup.tutar:,.0f} vs API ₺{api.amount:,.0f}")

        # Status karşılaştır
        status_ok = True
        if grup.durum and api.status:
            expected_api_statuses = self.DURUM_MAP.get(grup.durum.lower(), [])
            if expected_api_statuses and api.status not in expected_api_statuses:
                status_ok = False
                issues.append(f"durum: grup '{grup.durum}' vs API '{api.status}'")

        # Sonuç belirle
        if not issues:
            durum = EslesmeDurumu.ESLESTI
            aciklama = "✅ Tam eşleşme"
        elif tutar_farki > 0.01 and not status_ok:
            durum = EslesmeDurumu.TUTAR_FARKI  # Öncelik: tutar
            aciklama = " | ".join(issues)
        elif tutar_farki > 0.01:
            durum = EslesmeDurumu.TUTAR_FARKI
            aciklama = issues[0]
        else:
            durum = EslesmeDurumu.STATUS_FARKI
            aciklama = issues[0]

        return EslesmeRaporu(
            transaction_id=grup.transaction_id,
            durum=durum,
            grup_verisi=grup,
            api_verisi=api,
            tutar_farki=tutar_farki,
            aciklama=aciklama,
        )

    def _check_edit(self, grup: GrupIslemi, api: ApiIslemi) -> EslesmeRaporu:
        """Edit yapılmış işlemlerin karşılaştırması."""
        issues = []

        # API'deki tutar ile edit SONRASI tutar karşılaştır
        tutar_farki = 0.0
        if grup.tutar and api.amount:
            tutar_farki = abs(grup.tutar - api.amount)
            if tutar_farki > 0.01:
                issues.append(f"edit sonrası ₺{grup.tutar:,.0f} ≠ API ₺{api.amount:,.0f}")

        aciklama_parts = [f"EDIT: "]
        if grup.tutar_edit_oncesi:
            aciklama_parts.append(f"₺{grup.tutar_edit_oncesi:,.0f} → ₺{grup.tutar:,.0f}")
            dusus = (1 - grup.tutar / grup.tutar_edit_oncesi) * 100
            if dusus >= 50:
                aciklama_parts.append(f"🔴 %{dusus:.0f} düşüş")
        else:
            aciklama_parts.append(f"→ ₺{grup.tutar:,.0f}")

        if issues:
            aciklama_parts.append(f" | {issues[0]}")

        return EslesmeRaporu(
            transaction_id=grup.transaction_id,
            durum=EslesmeDurumu.EDIT_YAPILMIS,
            grup_verisi=grup,
            api_verisi=api,
            tutar_farki=tutar_farki,
            aciklama="".join(aciklama_parts),
        )

    def generate_report(self, raporlar: List[EslesmeRaporu]) -> Dict:
        """Eşleşme raporunu özetler."""
        ozet = {
            "toplam": len(raporlar),
            "eslesen": 0,
            "tutar_farki": 0,
            "status_farki": 0,
            "edit_yapilmis": 0,
            "api_bulunamadi": 0,
            "grup_bulunamadi": 0,
            "kritik": [],  # Dikkat gerektiren işlemler
        }

        for r in raporlar:
            if r.durum == EslesmeDurumu.ESLESTI:
                ozet["eslesen"] += 1
            elif r.durum == EslesmeDurumu.TUTAR_FARKI:
                ozet["tutar_farki"] += 1
                ozet["kritik"].append(r)
            elif r.durum == EslesmeDurumu.STATUS_FARKI:
                ozet["status_farki"] += 1
                ozet["kritik"].append(r)
            elif r.durum == EslesmeDurumu.EDIT_YAPILMIS:
                ozet["edit_yapilmis"] += 1
                # Büyük düşüş varsa kritik
                if r.grup_verisi and r.grup_verisi.tutar_edit_oncesi and r.grup_verisi.tutar:
                    dusus = (1 - r.grup_verisi.tutar / r.grup_verisi.tutar_edit_oncesi) * 100
                    if dusus >= 50:
                        ozet["kritik"].append(r)
            elif r.durum == EslesmeDurumu.API_BULUNAMADI:
                ozet["api_bulunamadi"] += 1
            elif r.durum == EslesmeDurumu.GRUP_BULUNAMADI:
                ozet["grup_bulunamadi"] += 1

        return ozet

    def format_telegram_report(self, raporlar: List[EslesmeRaporu]) -> str:
        """Telegram'a gönderilecek formatlı rapor üretir."""
        ozet = self.generate_report(raporlar)

        text = "📊 **İşlem Eşleştirme Raporu**\n\n"
        text += f"🔢 Toplam: {ozet['toplam']} işlem\n"
        text += f"✅ Eşleşen: {ozet['eslesen']}\n"
        text += f"💰 Tutar farkı: {ozet['tutar_farki']}\n"
        text += f"⚡ Durum farkı: {ozet['status_farki']}\n"
        text += f"✏️ Edit yapılmış: {ozet['edit_yapilmis']}\n"
        text += f"❓ API'de yok: {ozet['api_bulunamadi']}\n"
        text += f"👻 Grupta yok: {ozet['grup_bulunamadi']}\n"

        kritikler = ozet["kritik"]
        if kritikler:
            text += f"\n🚨 **KRİTİK ({len(kritikler)}):**\n"
            for r in kritikler[:10]:
                isim = r.grup_verisi.musteri_adi if r.grup_verisi else "?"
                text += f"  🔴 `{r.transaction_id}` {isim}\n"
                text += f"     {r.aciklama}\n\n"
            if len(kritikler) > 10:
                text += f"  ... ve {len(kritikler) - 10} daha\n"

        if ozet["eslesen"] == ozet["toplam"]:
            text += "\n✅ Tüm işlemler tutarlı!"

        return text
