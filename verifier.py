import re
import asyncio
import json
from datetime import datetime, timedelta
from rapidfuzz import fuzz
from database import (
    get_messages_by_group, get_unverified_messages, save_verification,
    get_rules, get_recent_verifications, get_verification_stats
)
from parser import MessageParser, TransactionTracker, IslemTipi
from api_client import RussPaymentAPI
from config import Config
import logging

logger = logging.getLogger(__name__)

# Severity emojileri
SEVERITY_ICONS = {
    "critical": "🔴",
    "warning": "⚠️",
    "info": "ℹ️",
}

STATUS_ICONS = {
    "confirmed": "✅",
    "partial": "⚠️",
    "denied": "❌",
    "pending": "⏳",
    "inconsistent": "🔴",
}


class VerificationEngine:
    """Ödeme/çekim operasyonları için çapraz doğrulama motoru."""

    def __init__(self):
        self.threshold = Config.MATCH_THRESHOLD
        self.parser = MessageParser()
        self.tracker = TransactionTracker()
        self.api = RussPaymentAPI() if Config.PAYMENT_API_KEY else None

    async def run_verification(self):
        """
        Ana doğrulama döngüsü:
        1. Her iki grubun mesajlarını parse et
        2. Müşteri ID/isim bazlı işlemleri eşleştir
        3. Tutarsızlıkları tespit et
        """
        since = (datetime.now() - timedelta(days=7)).isoformat()
        source_messages = await get_messages_by_group("source", since_date=since, limit=3000)
        verify_messages = await get_messages_by_group("verify", since_date=since, limit=3000)

        if not source_messages and not verify_messages:
            logger.debug("İşlenecek mesaj yok")
            return {"issues": [], "matched": 0, "total_source": 0, "total_verify": 0}

        # Tracker'ı sıfırla
        self.tracker = TransactionTracker()

        # Tüm mesajları parse et ve tracker'a ekle
        for msg in source_messages:
            parsed = self.parser.parse(msg["text"])
            if parsed.islem_tipi != IslemTipi.BILINMIYOR or parsed.musteri_id or parsed.tutar:
                self.tracker.add_event(parsed, "source", msg["message_id"], msg["date"])

        for msg in verify_messages:
            parsed = self.parser.parse(msg["text"])
            if parsed.islem_tipi != IslemTipi.BILINMIYOR or parsed.musteri_id or parsed.tutar:
                self.tracker.add_event(parsed, "verify", msg["message_id"], msg["date"])

        # Tutarsızlıkları tespit et
        issues = self.tracker.get_all_inconsistencies()

        # Ek: Kural bazlı doğrulama
        rules = await get_rules(active_only=True)
        rule_results = await self._run_rule_checks(source_messages, verify_messages, rules)

        # API çapraz doğrulama
        api_issues = await self._run_api_verification(source_messages + verify_messages)
        issues.extend(api_issues)

        # Sonuçları kaydet
        for issue in issues:
            await save_verification(
                source_msg_id=None,
                verify_msg_id=None,
                source_text=issue["message"][:500],
                verify_text=json.dumps({"type": issue["type"], "key": issue["key"]}, ensure_ascii=False)[:500],
                match_score=0,
                status="inconsistent",
                rule_name=issue["type"],
                details=issue["message"]
            )

        for result in rule_results:
            await save_verification(
                source_msg_id=result.get("source_msg_id"),
                verify_msg_id=result.get("verify_msg_id"),
                source_text=result.get("source_text", "")[:500],
                verify_text=result.get("verify_text", "")[:500],
                match_score=result.get("score", 0),
                status=result.get("status", "pending"),
                rule_name=result.get("rule_name", "genel"),
                details=result.get("details", "")
            )

        logger.info(
            f"Doğrulama tamamlandı: {len(issues)} tutarsızlık, "
            f"{len(rule_results)} kural eşleşmesi, "
            f"{len(source_messages)} kaynak / {len(verify_messages)} doğrulama mesajı"
        )

        return {
            "issues": issues,
            "rule_results": rule_results,
            "matched": len(rule_results),
            "total_source": len(source_messages),
            "total_verify": len(verify_messages),
        }

    async def _run_rule_checks(self, source_messages, verify_messages, rules):
        """Kural bazlı çapraz doğrulama."""
        results = []

        # Tüm mesajları parse et
        parsed_sources = [(msg, self.parser.parse(msg["text"])) for msg in source_messages]
        parsed_verifies = [(msg, self.parser.parse(msg["text"])) for msg in verify_messages]

        # 1) Müşteri ID bazlı eşleştirme
        id_matches = self._match_by_customer_id(parsed_sources, parsed_verifies)
        results.extend(id_matches)

        # 2) Müşteri adı bazlı eşleştirme
        name_matches = self._match_by_customer_name(parsed_sources, parsed_verifies)
        results.extend(name_matches)

        # 3) Tutar bazlı eşleştirme
        amount_matches = self._match_by_amount(parsed_sources, parsed_verifies)
        results.extend(amount_matches)

        # 4) İşlem hash bazlı eşleştirme
        hash_matches = self._match_by_hash(parsed_sources, parsed_verifies)
        results.extend(hash_matches)

        # 5) Çekim iptal - ödeme çelişki kontrolü
        conflict_results = self._check_cancel_payment_conflicts(parsed_sources, parsed_verifies)
        results.extend(conflict_results)

        # 6) Onay/Red tutarsızlık kontrolü
        approval_results = self._check_approval_conflicts(parsed_sources, parsed_verifies)
        results.extend(approval_results)

        return results

    def _match_by_customer_id(self, parsed_sources, parsed_verifies):
        """Müşteri ID ile eşleştirme."""
        results = []
        source_by_id = {}
        for msg, parsed in parsed_sources:
            if parsed.musteri_id:
                source_by_id.setdefault(parsed.musteri_id, []).append((msg, parsed))

        for msg, parsed in parsed_verifies:
            if parsed.musteri_id and parsed.musteri_id in source_by_id:
                for src_msg, src_parsed in source_by_id[parsed.musteri_id]:
                    status = self._determine_status(src_parsed, parsed)
                    results.append({
                        "source_msg_id": src_msg["message_id"],
                        "verify_msg_id": msg["message_id"],
                        "source_text": src_msg["text"],
                        "verify_text": msg["text"],
                        "score": 95,
                        "status": status,
                        "rule_name": "musteri_id_eslesmesi",
                        "details": f"Müşteri ID eşleşmesi: {parsed.musteri_id} | "
                                   f"Kaynak: {src_parsed.islem_tipi.value} → Doğrulama: {parsed.islem_tipi.value}"
                    })
        return results

    def _match_by_customer_name(self, parsed_sources, parsed_verifies):
        """Müşteri adı ile fuzzy eşleştirme."""
        results = []
        source_by_name = {}
        for msg, parsed in parsed_sources:
            if parsed.musteri_adi:
                source_by_name.setdefault(parsed.musteri_adi.lower(), []).append((msg, parsed))

        for msg, parsed in parsed_verifies:
            if parsed.musteri_adi:
                name = parsed.musteri_adi.lower()
                # Exact match
                if name in source_by_name:
                    for src_msg, src_parsed in source_by_name[name]:
                        status = self._determine_status(src_parsed, parsed)
                        results.append({
                            "source_msg_id": src_msg["message_id"],
                            "verify_msg_id": msg["message_id"],
                            "source_text": src_msg["text"],
                            "verify_text": msg["text"],
                            "score": 90,
                            "status": status,
                            "rule_name": "musteri_adi_eslesmesi",
                            "details": f"Müşteri adı eşleşmesi: {parsed.musteri_adi} | "
                                       f"Kaynak: {src_parsed.islem_tipi.value} → Doğrulama: {parsed.islem_tipi.value}"
                        })
                else:
                    # Fuzzy match
                    for src_name, src_items in source_by_name.items():
                        score = fuzz.ratio(name, src_name)
                        if score >= self.threshold:
                            for src_msg, src_parsed in src_items:
                                status = self._determine_status(src_parsed, parsed)
                                results.append({
                                    "source_msg_id": src_msg["message_id"],
                                    "verify_msg_id": msg["message_id"],
                                    "source_text": src_msg["text"],
                                    "verify_text": msg["text"],
                                    "score": score,
                                    "status": status,
                                    "rule_name": "musteri_adi_fuzzy",
                                    "details": f"Fuzzy ad eşleşmesi ({score}%): '{parsed.musteri_adi}' ↔ '{src_parsed.musteri_adi}'"
                                })
        return results

    def _match_by_amount(self, parsed_sources, parsed_verifies):
        """Tutar bazlı eşleştirme."""
        results = []
        source_by_amount = {}
        for msg, parsed in parsed_sources:
            if parsed.tutar and parsed.tutar > 0:
                source_by_amount.setdefault(parsed.tutar, []).append((msg, parsed))

        for msg, parsed in parsed_verifies:
            if parsed.tutar and parsed.tutar in source_by_amount:
                for src_msg, src_parsed in source_by_amount[parsed.tutar]:
                    # Aynı müşteri mi kontrol et
                    same_customer = (
                        (src_parsed.musteri_id and parsed.musteri_id and src_parsed.musteri_id == parsed.musteri_id) or
                        (src_parsed.musteri_adi and parsed.musteri_adi and
                         fuzz.ratio(src_parsed.musteri_adi.lower(), parsed.musteri_adi.lower()) > 80)
                    )
                    if same_customer:
                        status = self._determine_status(src_parsed, parsed)
                        results.append({
                            "source_msg_id": src_msg["message_id"],
                            "verify_msg_id": msg["message_id"],
                            "source_text": src_msg["text"],
                            "verify_text": msg["text"],
                            "score": 85,
                            "status": status,
                            "rule_name": "tutar_eslesmesi",
                            "details": f"Tutar eşleşmesi: ₺{parsed.tutar:,.2f} | Müşteri: {parsed.musteri_adi or src_parsed.musteri_adi}"
                        })
        return results

    def _match_by_hash(self, parsed_sources, parsed_verifies):
        """İşlem hash bazlı eşleştirme."""
        results = []
        source_by_hash = {}
        for msg, parsed in parsed_sources:
            if parsed.islem_hash:
                source_by_hash[parsed.islem_hash.lower()] = (msg, parsed)

        for msg, parsed in parsed_verifies:
            if parsed.islem_hash and parsed.islem_hash.lower() in source_by_hash:
                src_msg, src_parsed = source_by_hash[parsed.islem_hash.lower()]
                status = self._determine_status(src_parsed, parsed)
                results.append({
                    "source_msg_id": src_msg["message_id"],
                    "verify_msg_id": msg["message_id"],
                    "source_text": src_msg["text"],
                    "verify_text": msg["text"],
                    "score": 98,
                    "status": status,
                    "rule_name": "islem_hash_eslesmesi",
                    "details": f"İşlem hash eşleşmesi: {parsed.islem_hash}"
                })
        return results

    def _check_cancel_payment_conflicts(self, parsed_sources, parsed_verifies):
        """
        Senaryo: Çekim iptal talep edilmiş ama ödeme grubunda ödeme yapılmış.
        (Görsel 1-2 ve 3 arası çelişki)
        """
        results = []

        # Kaynak grupta iptal talepleri
        cancel_requests = {}
        for msg, parsed in parsed_sources:
            if parsed.islem_tipi in (IslemTipi.CEKIM_IPTAL, IslemTipi.IPTAL):
                key = parsed.musteri_id or (parsed.musteri_adi.lower() if parsed.musteri_adi else None)
                if key:
                    cancel_requests[key] = (msg, parsed)

        # Doğrulama grubunda ödeme kayıtları
        for msg, parsed in parsed_verifies:
            if parsed.islem_tipi in (IslemTipi.ODEME, IslemTipi.ONAY, IslemTipi.GONDERIM) or parsed.durum in ("ödendi", "onaylı"):
                key = parsed.musteri_id or (parsed.musteri_adi.lower() if parsed.musteri_adi else None)
                if key and key in cancel_requests:
                    src_msg, src_parsed = cancel_requests[key]
                    results.append({
                        "source_msg_id": src_msg["message_id"],
                        "verify_msg_id": msg["message_id"],
                        "source_text": src_msg["text"],
                        "verify_text": msg["text"],
                        "score": 0,
                        "status": "inconsistent",
                        "rule_name": "IPTAL_AMA_ODENMIS",
                        "details": f"🔴 KRİTİK: İptal talep edilmiş ama ödeme sağlanmış! "
                                   f"Müşteri: {src_parsed.musteri_adi or key} | Tutar: ₺{parsed.tutar or '?'}"
                    })
        return results

    def _check_approval_conflicts(self, parsed_sources, parsed_verifies):
        """
        Senaryo: Personel onay vermiş ama API red dönmüş.
        (Görsel 3: Ödendi ama API red veriyor, manuel onay gerekiyor)
        """
        results = []

        # Kaynak grupta onay/uygundur mesajları
        approvals = {}
        for msg, parsed in parsed_sources:
            if parsed.islem_tipi in (IslemTipi.ONAY, IslemTipi.UYGUNDUR) or parsed.durum == "onaylı":
                key = parsed.musteri_id or (parsed.musteri_adi.lower() if parsed.musteri_adi else None)
                if key:
                    approvals[key] = (msg, parsed)

        # Doğrulama grubunda red kayıtları
        for msg, parsed in parsed_verifies:
            if parsed.islem_tipi == IslemTipi.RED or parsed.durum == "reddedildi":
                key = parsed.musteri_id or (parsed.musteri_adi.lower() if parsed.musteri_adi else None)
                if key and key in approvals:
                    src_msg, src_parsed = approvals[key]
                    results.append({
                        "source_msg_id": src_msg["message_id"],
                        "verify_msg_id": msg["message_id"],
                        "source_text": src_msg["text"],
                        "verify_text": msg["text"],
                        "score": 0,
                        "status": "inconsistent",
                        "rule_name": "ONAY_AMA_RED",
                        "details": f"🔴 KRİTİK: Personel onay vermiş ama API red döndü! "
                                   f"Manuel onay gerekli. Müşteri: {src_parsed.musteri_adi or key}"
                    })

        # Ek: Ödeme yapılmış ama sistem red veriyor (Görsel 3 senaryosu)
        payments = {}
        for msg, parsed in parsed_sources + parsed_verifies:
            if parsed.durum == "ödendi" or (parsed.islem_tipi == IslemTipi.ODEME and "evet" in msg["text"].lower()):
                key = parsed.musteri_id or (parsed.musteri_adi.lower() if parsed.musteri_adi else None)
                if key:
                    payments[key] = (msg, parsed)

        for msg, parsed in parsed_verifies:
            if parsed.durum == "reddedildi" or parsed.islem_tipi == IslemTipi.RED:
                key = parsed.musteri_id or (parsed.musteri_adi.lower() if parsed.musteri_adi else None)
                if key and key in payments:
                    pay_msg, pay_parsed = payments[key]
                    results.append({
                        "source_msg_id": pay_msg["message_id"],
                        "verify_msg_id": msg["message_id"],
                        "source_text": pay_msg["text"],
                        "verify_text": msg["text"],
                        "score": 0,
                        "status": "inconsistent",
                        "rule_name": "ODENMIS_AMA_RED",
                        "details": f"🔴 KRİTİK: Ödeme sağlanmış ama API red veriyor! "
                                   f"Manuel onay + gönderim gerekli. "
                                   f"Müşteri: {pay_parsed.musteri_adi or key} | Tutar: ₺{pay_parsed.tutar or '?'}"
                    })
        return results

    def _determine_status(self, src_parsed, verify_parsed):
        """İki parsed mesaj arasındaki durumu belirle."""
        # Çelişki kontrolleri
        cancel_types = {IslemTipi.CEKIM_IPTAL, IslemTipi.IPTAL}
        payment_types = {IslemTipi.ODEME, IslemTipi.GONDERIM, IslemTipi.ONAY}

        if src_parsed.islem_tipi in cancel_types and verify_parsed.islem_tipi in payment_types:
            return "inconsistent"
        if src_parsed.islem_tipi in payment_types and verify_parsed.islem_tipi == IslemTipi.RED:
            return "inconsistent"

        # Onay kontrolleri
        approval_types = {IslemTipi.UYGUNDUR, IslemTipi.ONAY, IslemTipi.KT}
        if src_parsed.islem_tipi in approval_types and verify_parsed.islem_tipi in approval_types:
            return "confirmed"
        if src_parsed.islem_tipi in approval_types and verify_parsed.durum in ("onaylı", "ödendi"):
            return "confirmed"

        # Bekleyen
        if verify_parsed.durum == "bekleyen":
            return "pending"

        return "partial"

    async def get_report(self):
        """Detaylı doğrulama raporu oluşturur."""
        stats = await get_verification_stats()
        recent = await get_recent_verifications(limit=10)

        report = "📊 **Doğrulama Raporu**\n\n"

        # İstatistikler
        report += "**İstatistikler:**\n"
        report += f"  ✅ Doğrulanmış: {stats.get('confirmed', 0)}\n"
        report += f"  ⚠️ Kısmi: {stats.get('partial', 0)}\n"
        report += f"  🔴 Tutarsız: {stats.get('inconsistent', 0)}\n"
        report += f"  ❌ Reddedilen: {stats.get('denied', 0)}\n"
        report += f"  ⏳ Bekleyen: {stats.get('pending', 0)}\n\n"

        # Kritik tutarsızlıklar önce
        critical = [v for v in recent if v["status"] == "inconsistent"]
        if critical:
            report += "🔴 **KRİTİK TUTARSIZLIKLAR:**\n"
            for v in critical:
                report += f"  • [{v['rule_name']}] {v['details'][:100]}\n"
            report += "\n"

        # Son doğrulamalar
        if recent:
            report += "**Son İşlemler:**\n"
            for v in recent:
                icon = STATUS_ICONS.get(v["status"], "❓")
                preview = (v["source_text"] or "")[:60]
                report += f"  {icon} [{v['rule_name']}] {preview}\n"

        return report

    async def _run_api_verification(self, all_messages):
        """API'den işlem durumlarını çekip grup mesajlarıyla karşılaştırır."""
        issues = []
        if not self.api:
            return issues

        try:
            api_transactions = await self.api.get_transactions()
            if not api_transactions:
                return issues

            # API işlemlerini indexle
            api_by_id = {}
            api_by_name = {}
            for tx in api_transactions:
                tx_id = tx.get("transactionId") or tx.get("transaction_id") or tx.get("id", "")
                name = (tx.get("playerFullName") or tx.get("player_full_name") or "").lower()
                if tx_id:
                    api_by_id[str(tx_id)] = tx
                if name:
                    api_by_name.setdefault(name, []).append(tx)

            # Grup mesajlarını API ile karşılaştır
            for msg in all_messages:
                parsed = self.parser.parse(msg["text"])
                if not parsed.musteri_id and not parsed.musteri_adi:
                    continue

                # Müşteri adıyla API'de ara
                if parsed.musteri_adi:
                    name_lower = parsed.musteri_adi.lower()
                    api_matches = api_by_name.get(name_lower, [])
                    if not api_matches:
                        # Fuzzy arama
                        for api_name, txs in api_by_name.items():
                            if fuzz.ratio(name_lower, api_name) >= 80:
                                api_matches = txs
                                break

                    for api_tx in api_matches:
                        api_status = (api_tx.get("status") or "").upper()

                        # Grupta onay/ödeme var ama API'de REJECTED
                        if parsed.islem_tipi in (IslemTipi.ONAY, IslemTipi.ODEME, IslemTipi.UYGUNDUR):
                            if api_status == "REJECTED":
                                issues.append({
                                    "type": "API_RED_GRUP_ONAY",
                                    "severity": "critical",
                                    "key": parsed.musteri_adi or parsed.musteri_id or "?",
                                    "message": f"Grupta onay/ödeme var ama API REJECTED! "
                                               f"Müşteri: {parsed.musteri_adi} | "
                                               f"Tutar: {api_tx.get('amount', '?')}"
                                })

                        # Grupta iptal var ama API'de APPROVED
                        if parsed.islem_tipi in (IslemTipi.CEKIM_IPTAL, IslemTipi.IPTAL):
                            if api_status == "APPROVED":
                                issues.append({
                                    "type": "API_ONAY_GRUP_IPTAL",
                                    "severity": "critical",
                                    "key": parsed.musteri_adi or parsed.musteri_id or "?",
                                    "message": f"Grupta iptal var ama API APPROVED! "
                                               f"Müşteri: {parsed.musteri_adi} | "
                                               f"Tutar: {api_tx.get('amount', '?')}"
                                })

            logger.info(f"API doğrulama: {len(api_transactions)} API işlemi kontrol edildi, {len(issues)} tutarsızlık")

        except Exception as e:
            logger.error(f"API doğrulama hatası: {e}", exc_info=True)

        return issues

    async def get_transaction_detail(self, search_term):
        """Belirli bir müşteri/işlem hakkında detaylı bilgi döner."""
        search_lower = search_term.lower()

        # Tracker'dan ara
        for key, tx in self.tracker.transactions.items():
            if search_lower in key or (tx["musteri_adi"] and search_lower in tx["musteri_adi"].lower()):
                summary = self.tracker.get_transaction_summary(key)
                issues = self.tracker.check_inconsistencies(key)
                result = summary + "\n"
                if issues:
                    result += "**Tutarsızlıklar:**\n"
                    for issue in issues:
                        result += f"  {SEVERITY_ICONS.get(issue['severity'], '❓')} {issue['message']}\n"
                else:
                    result += "✅ Tutarsızlık bulunamadı\n"

                # API'den de kontrol et
                if self.api:
                    try:
                        api_txs = await self.api.get_transactions()
                        for api_tx in (api_txs or []):
                            api_name = (api_tx.get("playerFullName") or "").lower()
                            if search_lower in api_name or fuzz.ratio(search_lower, api_name) >= 80:
                                api_status = api_tx.get("status", "?")
                                amount = api_tx.get("amount", "?")
                                tx_id = api_tx.get("transactionId") or api_tx.get("id", "?")
                                result += f"\n📡 **API Durumu:**\n"
                                result += f"  İşlem ID: {tx_id}\n"
                                result += f"  Durum: {api_status}\n"
                                result += f"  Tutar: {amount}\n"
                                break
                    except Exception as e:
                        result += f"\n⚠️ API sorgu hatası: {e}\n"

                return result

        return f"'{search_term}' ile eşleşen işlem bulunamadı."
