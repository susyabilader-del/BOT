"""
Telegram mesajlarından yapılandırılmış veri çıkarma modülü.
Ödeme/çekim operasyonlarına özel parser.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class IslemTipi(Enum):
    CEKIM_TALEBI = "cekim_talebi"
    CEKIM_IPTAL = "cekim_iptal"
    ODEME = "odeme"
    ONAY = "onay"
    RED = "red"
    BEKLEYEN = "bekleyen"
    KT = "kt"  # Kabul/Tamam
    UYGUNDUR = "uygundur"
    IPTAL = "iptal"
    GONDERIM = "gonderim"
    BILINMIYOR = "bilinmiyor"


@dataclass
class ParsedMessage:
    raw_text: str
    islem_tipi: IslemTipi = IslemTipi.BILINMIYOR
    musteri_adi: Optional[str] = None
    musteri_id: Optional[str] = None
    musteri_username: Optional[str] = None
    tutar: Optional[float] = None
    tutar_str: Optional[str] = None
    para_birimi: str = "TL"
    platform: Optional[str] = None
    islem_hash: Optional[str] = None
    durum: Optional[str] = None
    iban: Optional[str] = None
    reply_to: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    confidence: float = 0.0


class MessageParser:
    """Telegram mesajlarını parse edip yapılandırılmış veri çıkarır."""

    # Müşteri ID pattern: uzun sayısal ID
    ID_PATTERN = re.compile(r'ID:\s*(\d{10,})', re.IGNORECASE)

    # Username pattern
    USERNAME_PATTERN = re.compile(r'@(\w+)')

    # Tutar patternleri
    TUTAR_PATTERNS = [
        re.compile(r'₺\s*([\d.,]+)'),                          # ₺22.000,00
        re.compile(r'([\d.,]+)\s*₺'),                          # 22.000,00₺
        re.compile(r'([\d.,]+)\s*(TL|tl|Tl)', re.IGNORECASE),  # 22000 TL
        re.compile(r'([\d.,]+)\s*(USD|EUR|GBP)', re.IGNORECASE),
    ]

    # İşlem hash pattern (kısa hex string)
    HASH_PATTERN = re.compile(r'\b([a-f0-9]{6,10}[a-f0-9]*)\b', re.IGNORECASE)

    # IBAN pattern
    IBAN_PATTERN = re.compile(r'TR\d{2}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{2}')

    # Platform patternleri
    PLATFORMS = ["ALLHAVALE", "PAPARA", "PAYFIX", "MEFETE", "HAVALE", "EFT", "FAST"]

    # İşlem tipi keyword'leri
    ISLEM_KEYWORDS = {
        IslemTipi.CEKIM_IPTAL: [
            r'çek(?:im)?\s*iptal', r'iptal\s*(?:et|edebilir|edelim|lütfen)',
            r'çekim(?:i)?\s*iptal', r'iptal\s*işlemi'
        ],
        IslemTipi.CEKIM_TALEBI: [
            r'çek(?:im)?\s*taleb', r'çekim\s*(?:yap|ist)', r'çek\s*kt',
            r'çekim\s*(?:alabilir|edebilir)'
        ],
        IslemTipi.ODEME: [
            r'ödeme\s*sağlan', r'ödeme\s*(?:yapıl|tamam|ok)',
            r'ödendi', r'ödeme\s*onay'
        ],
        IslemTipi.ONAY: [
            r'onaylı', r'onaylandı', r'onay\s*ver', r'bende\s*onaylı'
        ],
        IslemTipi.RED: [
            r'red(?:det|d)', r'reddedil', r'red\s*ver', r'red\s*geldi'
        ],
        IslemTipi.BEKLEYEN: [
            r'bekleyen', r'beklemede', r'pending'
        ],
        IslemTipi.UYGUNDUR: [
            r'uygundur', r'uygun(?:dur)?$'
        ],
        IslemTipi.KT: [
            r'^kt$', r'\bkt\b'
        ],
        IslemTipi.IPTAL: [
            r'^iptal$', r'iptal\s*edildi'
        ],
        IslemTipi.GONDERIM: [
            r'gönderim\s*sağlan', r'gönderildi', r'gönder(?:im|ilecek)'
        ],
    }

    # Durum keyword'leri (API/sistem durumları)
    DURUM_KEYWORDS = {
        "bekleyen": ["bekleyen", "pending", "beklemede"],
        "onaylı": ["onaylı", "onaylandı", "approved", "başarılı"],
        "reddedildi": ["red", "reddedildi", "rejected", "başarısız", "hatalı"],
        "iptal": ["iptal", "cancelled", "iptal edildi"],
        "ödendi": ["ödendi", "ödeme sağlandı", "paid"],
        "gönderildi": ["gönderildi", "sent", "gönderim sağlandı"],
    }

    def parse(self, text: str) -> ParsedMessage:
        """Mesaj metnini parse eder ve yapılandırılmış veri döner."""
        msg = ParsedMessage(raw_text=text)

        # Müşteri bilgileri
        msg.musteri_id = self._extract_id(text)
        msg.musteri_username = self._extract_username(text)
        msg.musteri_adi = self._extract_name(text)

        # Finansal bilgiler
        tutar_info = self._extract_tutar(text)
        if tutar_info:
            msg.tutar, msg.tutar_str, msg.para_birimi = tutar_info

        # İşlem bilgileri
        msg.islem_hash = self._extract_hash(text)
        msg.iban = self._extract_iban(text)
        msg.platform = self._extract_platform(text)

        # İşlem tipi
        msg.islem_tipi, msg.confidence = self._detect_islem_tipi(text)

        # Durum
        msg.durum = self._detect_durum(text)

        # Keyword'ler
        msg.keywords = self._extract_keywords(text)

        # Reply/quote içeriği
        msg.reply_to = self._extract_reply(text)

        return msg

    def _extract_id(self, text: str) -> Optional[str]:
        match = self.ID_PATTERN.search(text)
        return match.group(1) if match else None

    def _extract_username(self, text: str) -> Optional[str]:
        match = self.USERNAME_PATTERN.search(text)
        return match.group(1) if match else None

    def _extract_name(self, text: str) -> Optional[str]:
        # "mediha tekgöz @tekmediha99 ID: 2026..." formatından isim çıkar
        pattern = re.compile(r'([a-zA-ZçğıöşüÇĞIİÖŞÜ]+\s+[a-zA-ZçğıöşüÇĞIİÖŞÜ]+)\s*@')
        match = pattern.search(text)
        if match:
            return match.group(1).strip()

        # "e96b047a  mediha tekgöz — — ₺22.000,00" formatı
        pattern2 = re.compile(r'[a-f0-9]{6,}\s+([a-zA-ZçğıöşüÇĞIİÖŞÜ]+\s+[a-zA-ZçğıöşüÇĞIİÖŞÜ]+)\s*[—\-]')
        match2 = pattern2.search(text)
        if match2:
            return match2.group(1).strip()

        return None

    def _extract_tutar(self, text: str):
        for pattern in self.TUTAR_PATTERNS:
            match = pattern.search(text)
            if match:
                tutar_str = match.group(1)
                # Türk formatı: 22.000,00 → 22000.00
                tutar_clean = tutar_str.replace('.', '').replace(',', '.')
                try:
                    tutar = float(tutar_clean)
                    # Para birimi
                    para = "TL"
                    if len(match.groups()) > 1 and match.group(2):
                        para = match.group(2).upper()
                    return tutar, tutar_str, para
                except ValueError:
                    continue
        return None

    def _extract_hash(self, text: str) -> Optional[str]:
        # Satırın başındaki kısa hex hash (e96b047a gibi)
        match = re.match(r'^([a-f0-9]{6,10})\s', text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _extract_iban(self, text: str) -> Optional[str]:
        match = self.IBAN_PATTERN.search(text)
        return match.group(0).replace(' ', '') if match else None

    def _extract_platform(self, text: str) -> Optional[str]:
        text_upper = text.upper()
        for p in self.PLATFORMS:
            if p in text_upper:
                return p
        return None

    def _detect_islem_tipi(self, text: str):
        text_lower = text.lower().strip()
        best_type = IslemTipi.BILINMIYOR
        best_conf = 0.0

        for islem_tipi, patterns in self.ISLEM_KEYWORDS.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    # Daha spesifik pattern = daha yüksek güven
                    conf = 0.9 if len(pattern) > 10 else 0.7
                    if conf > best_conf:
                        best_conf = conf
                        best_type = islem_tipi

        return best_type, best_conf

    def _detect_durum(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        for durum, keywords in self.DURUM_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    return durum
        return None

    def _extract_keywords(self, text: str) -> List[str]:
        important_words = [
            "iptal", "onay", "red", "çekim", "ödeme", "gönderim",
            "uygundur", "bekleyen", "hatalı", "sistem", "kt",
            "pasif", "aktif", "tamamlandı", "reddedildi"
        ]
        found = []
        text_lower = text.lower()
        for word in important_words:
            if word in text_lower:
                found.append(word)
        return found

    def _extract_reply(self, text: str) -> Optional[str]:
        # Telegram'da quote edilen mesaj genellikle farklı formatlarda gelir
        # Pyrogram'da reply_to_message olarak gelecek, burada metin içinden deniyoruz
        return None


class TransactionTracker:
    """İşlemleri takip eden ve eşleştiren sınıf."""

    def __init__(self):
        self.transactions = {}  # key: müşteri_id veya isim, value: işlem geçmişi

    def add_event(self, parsed_msg: ParsedMessage, group_type: str, msg_id: int, timestamp: str):
        """Bir işlem olayını ekler."""
        # Müşteri anahtarı belirle
        key = parsed_msg.musteri_id or parsed_msg.musteri_adi or parsed_msg.islem_hash
        if not key:
            return None

        key = key.lower().strip()

        if key not in self.transactions:
            self.transactions[key] = {
                "musteri_id": parsed_msg.musteri_id,
                "musteri_adi": parsed_msg.musteri_adi,
                "events": []
            }

        event = {
            "msg_id": msg_id,
            "group_type": group_type,
            "islem_tipi": parsed_msg.islem_tipi.value,
            "durum": parsed_msg.durum,
            "tutar": parsed_msg.tutar,
            "platform": parsed_msg.platform,
            "timestamp": timestamp,
            "raw_text": parsed_msg.raw_text[:200],
            "keywords": parsed_msg.keywords
        }

        self.transactions[key]["events"].append(event)
        return key

    def check_inconsistencies(self, key: str) -> List[dict]:
        """Bir işlem için tutarsızlıkları kontrol eder."""
        if key not in self.transactions:
            return []

        events = self.transactions[key]["events"]
        issues = []

        source_events = [e for e in events if e["group_type"] == "source"]
        verify_events = [e for e in events if e["group_type"] == "verify"]

        # Kontrol 1: İptal talep edilmiş ama ödeme yapılmış
        has_iptal = any(e["islem_tipi"] in ("cekim_iptal", "iptal") for e in source_events)
        has_odeme = any(e["durum"] == "ödendi" or e["islem_tipi"] == "odeme" for e in verify_events)

        if has_iptal and has_odeme:
            issues.append({
                "type": "IPTAL_AMA_ODENMIS",
                "severity": "critical",
                "message": f"⚠️ İptal talep edilmiş ama ödeme yapılmış! Müşteri: {self.transactions[key]['musteri_adi']}",
                "key": key
            })

        # Kontrol 2: Onay verilmiş ama API'de red
        has_onay = any(e["islem_tipi"] in ("onay", "uygundur") or "uygundur" in e.get("keywords", [])
                      for e in source_events)
        has_red = any(e["durum"] == "reddedildi" or e["islem_tipi"] == "red" for e in verify_events)

        if has_onay and has_red:
            issues.append({
                "type": "ONAY_AMA_RED",
                "severity": "critical",
                "message": f"🔴 Personel onay vermiş ama API'de red! Müşteri: {self.transactions[key]['musteri_adi']}",
                "key": key
            })

        # Kontrol 3: Ödeme yapılmış ama red dönmüş (3. görsel senaryosu)
        has_odeme_src = any(e["durum"] == "ödendi" or "ödeme" in e.get("keywords", [])
                          for e in source_events + verify_events)
        has_red_api = any(e["durum"] == "reddedildi" for e in verify_events)

        if has_odeme_src and has_red_api:
            issues.append({
                "type": "ODENMIS_AMA_RED",
                "severity": "critical",
                "message": f"🔴 Ödeme sağlanmış ama API red veriyor! Manuel onay gerekli. Müşteri: {self.transactions[key]['musteri_adi']}",
                "key": key
            })

        # Kontrol 4: Tutar uyuşmazlığı
        tutarlar = set()
        for e in events:
            if e["tutar"]:
                tutarlar.add(e["tutar"])

        if len(tutarlar) > 1:
            issues.append({
                "type": "TUTAR_UYUSMAZLIGI",
                "severity": "warning",
                "message": f"⚠️ Farklı tutarlar tespit edildi: {tutarlar}. Müşteri: {self.transactions[key]['musteri_adi']}",
                "key": key
            })

        # Kontrol 5: Kaynak grupta işlem var ama doğrulama grubunda karşılığı yok
        if source_events and not verify_events:
            has_action = any(e["islem_tipi"] not in ("kt", "bilinmiyor") for e in source_events)
            if has_action:
                issues.append({
                    "type": "DOGRULAMA_YOK",
                    "severity": "warning",
                    "message": f"⏳ Kaynak grupta işlem var ama doğrulama grubunda karşılığı bulunamadı. Müşteri: {self.transactions[key]['musteri_adi']}",
                    "key": key
                })

        # Kontrol 6: Bekleyen işlem - uzun süredir bekliyor
        has_bekleyen = any(e["durum"] == "bekleyen" for e in verify_events)
        if has_bekleyen and not has_odeme:
            issues.append({
                "type": "UZUN_BEKLEME",
                "severity": "info",
                "message": f"⏳ İşlem hala beklemede. Müşteri: {self.transactions[key]['musteri_adi']}",
                "key": key
            })

        return issues

    def get_all_inconsistencies(self) -> List[dict]:
        """Tüm işlemlerdeki tutarsızlıkları döner."""
        all_issues = []
        for key in self.transactions:
            issues = self.check_inconsistencies(key)
            all_issues.extend(issues)
        return all_issues

    def get_transaction_summary(self, key: str) -> Optional[str]:
        """Bir işlemin özetini döner."""
        if key not in self.transactions:
            return None

        tx = self.transactions[key]
        events = tx["events"]

        summary = f"👤 **{tx['musteri_adi'] or 'Bilinmeyen'}**"
        if tx["musteri_id"]:
            summary += f" (ID: {tx['musteri_id']})"
        summary += "\n"

        for e in events:
            group_icon = "📤" if e["group_type"] == "source" else "📥"
            summary += f"  {group_icon} [{e['islem_tipi']}]"
            if e["tutar"]:
                summary += f" ₺{e['tutar']:,.2f}"
            if e["durum"]:
                summary += f" | Durum: {e['durum']}"
            summary += f" ({e['timestamp'][:16]})\n"

        return summary
