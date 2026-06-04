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
    EDIT_ONAY = "edit_onay"  # Tutar editlenerek onaylanmış
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
    tutar_yonu: str = ""  # "cekim" veya "yatirim"
    para_birimi: str = "TL"
    platform: Optional[str] = None
    islem_hash: Optional[str] = None
    durum: Optional[str] = None
    iban: Optional[str] = None
    talep_tarihi: Optional[str] = None
    banka: Optional[str] = None
    tutar_edit_oncesi: Optional[float] = None  # Edit öncesi tutar
    reply_to: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    confidence: float = 0.0
    is_structured: bool = False  # Yapılandırılmış blok mu?


class MessageParser:
    """Telegram mesajlarını parse edip yapılandırılmış veri çıkarır."""

    # Müşteri ID pattern: uzun sayısal ID
    ID_PATTERN = re.compile(r'ID:\s*(\d{7,})', re.IGNORECASE)

    # Username pattern
    USERNAME_PATTERN = re.compile(r'@(\w+)')

    # Tutar patternleri (sıralama önemli - daha spesifik önce)
    TUTAR_PATTERNS = [
        re.compile(r'-₺\s*([\d.,]+)'),                         # -₺22.000,00 (çekim)
        re.compile(r'\+₺\s*([\d.,]+)'),                        # +₺22.000,00 (yatırım)
        re.compile(r'₺\s*([\d.,]+)'),                          # ₺22.000,00
        re.compile(r'([\d.,]+)\s*₺'),                          # 22.000,00₺
        re.compile(r'([\d.,]+)\s*(TL|tl|Tl)', re.IGNORECASE),  # 22000 TL
        re.compile(r'([\d.,]+)\s*(USD|EUR|GBP)', re.IGNORECASE),
    ]

    # İşlem hash pattern (SHA256 - 64 hex karakter)
    HASH_PATTERN = re.compile(r'^([a-f0-9]{64})$', re.IGNORECASE | re.MULTILINE)
    SHORT_HASH_PATTERN = re.compile(r'\b([a-f0-9]{8,16})\b', re.IGNORECASE)

    # IBAN pattern
    IBAN_PATTERN = re.compile(r'TR\d{2}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{2}')

    # Talep tarihi pattern
    TALEP_PATTERN = re.compile(r'Talep:\s*(\d{2}\.\d{2}\.\d{4}\s*\d{2}:\d{2})')

    # KT grubu formatı: "USERNAME  PLAYERID  AD  SOYAD"
    KT_FORMAT_PATTERN = re.compile(
        r'^([A-Za-z0-9_]+)\s+(\d{5,})\s+([A-ZÇĞIİÖŞÜa-zçğıöşü]+)\s+([A-ZÇĞIİÖŞÜa-zçğıöşü]+)',
        re.MULTILINE
    )

    # Platform patternleri
    PLATFORMS = ["ALLHAVALE", "PAPARA", "PAYFIX", "MEFETE", "HAVALE", "EFT", "FAST",
                 "ANINDA HAVALE", "ANINDA BANKA"]

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
            r'ödendi', r'ödeme\s*onay', r'ödeme\s*girelim',
            r'ödeme\s*kt'
        ],
        IslemTipi.ONAY: [
            r'^onay$', r'^onay\s*✅', r'onaylı', r'onaylandı', r'onay\s*ver',
            r'bende\s*onaylı', r'onaydır'
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
            r'^kt$', r'^kt\s', r'ödeme\s*kt', r'kt\s*lütfen',
            r'dekont.*kt'
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

        # Edit onay formatı (hash isim — banka ₺tutar PLATFORM — Durum)
        edit_msg = self._parse_edit_onay_format(text)
        if edit_msg:
            return edit_msg

        # Önce yapılandırılmış blok mu kontrol et
        structured = self._parse_structured_block(text)
        if structured:
            return structured

        # KT grubu formatı kontrol et
        kt_msg = self._parse_kt_format(text)
        if kt_msg:
            return kt_msg

        # Genel parsing
        msg.musteri_id = self._extract_id(text)
        msg.musteri_username = self._extract_username(text)
        msg.musteri_adi = self._extract_name(text)

        # Finansal bilgiler
        tutar_info = self._extract_tutar(text)
        if tutar_info:
            msg.tutar, msg.tutar_str, msg.para_birimi, msg.tutar_yonu = tutar_info

        # İşlem bilgileri
        msg.islem_hash = self._extract_hash(text)
        msg.iban = self._extract_iban(text)
        msg.platform = self._extract_platform(text)
        msg.talep_tarihi = self._extract_talep_tarihi(text)

        # İşlem tipi
        msg.islem_tipi, msg.confidence = self._detect_islem_tipi(text)

        # Durum
        msg.durum = self._detect_durum(text)

        # Keyword'ler
        msg.keywords = self._extract_keywords(text)

        # Reply/quote içeriği
        msg.reply_to = self._extract_reply(text)

        return msg

    def _parse_edit_onay_format(self, text: str) -> Optional[ParsedMessage]:
        """
        Edit onay formatını parse eder.
        Format:
            1e56aaef Hüseyin Çakmak — ING Bank - DNA ₺5.000,00 ALLHAVALE — Onaylı
            işlem 50.000₺ tutarından 5.000₺ tutarına editlenerek onaylanmıştır.
        Alternatif:
            SAHA 1 | #558200B9 id'li yatırım 5000₺ tutardan 4500₺ tutarına edit onaylanmıştır
        """
        lines = text.strip().split('\n')
        full_text = text.strip().lower()

        # "editlenerek onaylanmıştır" veya "edit onaylanmıştır" kontrolü
        if 'edit' not in full_text or 'onay' not in full_text:
            return None

        msg = ParsedMessage(raw_text=text, is_structured=True, islem_tipi=IslemTipi.EDIT_ONAY, confidence=0.95)

        # Format 1: "hash isim — banka - tip ₺tutar PLATFORM — Durum"
        header_pattern = re.compile(
            r'^([0-9a-fA-F]{6,10})\s+'  # short hash
            r'(.+?)\s*[—\-]\s*'          # isim
            r'(.+?)\s*[—\-]\s*'          # banka - tip
            r'[₺]?([\d.,]+)\s*'          # tutar
            r'(\w+)\s*[—\-]\s*'          # platform
            r'(\S+)',                      # durum
            re.UNICODE
        )

        # Format 2: "SAHA X | #hash id'li yatırım Xk₺ tutardan Y₺ tutarına edit"
        saha_pattern = re.compile(
            r'(?:SAHA|KILIC|GOLFO)\s*\d*\s*\|\s*#?([0-9a-fA-F]+)',
            re.IGNORECASE
        )

        # İlk satırı header olarak dene
        for line in lines:
            line_clean = line.strip()

            # Format 1 header
            h_match = re.match(
                r'^([0-9a-fA-F]{6,10})\s+(.+?)\s+[—–\-]+\s+(.+?)\s+[—–\-]+\s+(.+?)₺([\d.,]+)\s+(\w+)\s+[—–\-]+\s+(\S+)',
                line_clean
            )
            if not h_match:
                # Daha esnek: "hash isim — bank ₺amount PLATFORM — Status"
                h_match = re.match(
                    r'^([0-9a-fA-F]{6,10})\s+(.+?)\s*—\s*(.+?)\s+₺([\d.,]+)\s+(\w+)\s*—\s*(\S+)',
                    line_clean
                )
                if h_match:
                    msg.islem_hash = h_match.group(1)
                    msg.musteri_adi = h_match.group(2).strip()
                    msg.banka = h_match.group(3).strip().rstrip(' -')
                    tutar_str = h_match.group(4)
                    msg.tutar = self._parse_tutar_value(tutar_str)
                    msg.tutar_str = f"₺{tutar_str}"
                    msg.platform = h_match.group(5)
                    msg.durum = h_match.group(6).lower()
                    continue

            if h_match and len(h_match.groups()) >= 7:
                msg.islem_hash = h_match.group(1)
                msg.musteri_adi = h_match.group(2).strip()
                msg.banka = h_match.group(3).strip()
                tutar_str = h_match.group(5)
                msg.tutar = self._parse_tutar_value(tutar_str)
                msg.tutar_str = f"₺{tutar_str}"
                msg.platform = h_match.group(6)
                msg.durum = h_match.group(7).lower()
                continue

            # SAHA format
            s_match = saha_pattern.match(line_clean)
            if s_match:
                msg.islem_hash = s_match.group(1)

        # Edit tutarlarını çıkar: "X₺ tutarından/tutardan Y₺ tutarına"
        edit_pattern = re.compile(
            r'(\d[\d.,]*)\s*k?\s*₺?\s*tutar[ıi]?n?(?:d[ae]n|dan)?\s+'
            r'(\d[\d.,]*)\s*k?\s*₺?\s*tutar[ıi]na',
            re.IGNORECASE
        )
        edit_match = edit_pattern.search(text)
        if edit_match:
            onceki_str = edit_match.group(1)
            sonraki_str = edit_match.group(2)

            # "k" suffix (100k = 100.000)
            onceki_raw = text[edit_match.start(1):edit_match.end(1) + 5]
            sonraki_raw = text[edit_match.start(2):edit_match.end(2) + 5]

            msg.tutar_edit_oncesi = self._parse_tutar_value(onceki_str)
            if 'k' in onceki_raw.lower():
                msg.tutar_edit_oncesi = (msg.tutar_edit_oncesi or 0) * 1000

            edit_sonrasi = self._parse_tutar_value(sonraki_str)
            if 'k' in sonraki_raw.lower():
                edit_sonrasi = (edit_sonrasi or 0) * 1000

            # Güncel tutar = edit sonrası
            if edit_sonrasi:
                msg.tutar = edit_sonrasi
        elif not msg.tutar:
            # Sadece "Y₺ tutarına editlenerek" formatı
            single_edit = re.search(r'(\d[\d.,]*)\s*k?\s*₺\s*tutar[ıi]na', text)
            if single_edit:
                msg.tutar = self._parse_tutar_value(single_edit.group(1))

        # Hash bulunamadıysa metin içinden dene
        if not msg.islem_hash:
            hash_match = re.search(r'#?([0-9a-fA-F]{8})', text)
            if hash_match:
                msg.islem_hash = hash_match.group(1)

        msg.tutar_yonu = "yatirim"
        msg.keywords = ["edit", "onay"]

        return msg

    def _parse_tutar_value(self, tutar_str: str) -> Optional[float]:
        """Tutar string'ini float'a çevirir: '5.000,00' -> 5000.0, '50.000' -> 50000.0"""
        if not tutar_str:
            return None
        try:
            cleaned = tutar_str.replace(' ', '')
            if ',' in cleaned:
                # Türk formatı: 5.000,00
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                # 5.000 formatı (binlik ayracı)
                if cleaned.count('.') == 1 and len(cleaned.split('.')[-1]) == 3:
                    cleaned = cleaned.replace('.', '')
                elif cleaned.count('.') > 1:
                    cleaned = cleaned.replace('.', '')
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    def _parse_structured_block(self, text: str) -> Optional[ParsedMessage]:
        """
        Yapılandırılmış işlem bloğunu parse eder.
        Format:
            mediha tekgöz
            @tekmediha99
            ID: 2026035075909
            -
            mediha tekgöz
            TR890015700000000123516764
            -₺22.000,00
            Beklemede
            Talep: 02.06.2026 06:23
        """
        lines = [l.strip() for l in text.strip().split('\n') if l.strip()]

        # Yapılandırılmış blok tespiti: ID: ve ₺ ve en az 5 satır
        has_id = any(re.match(r'ID:\s*\d+', l, re.IGNORECASE) for l in lines)
        has_tutar = any('₺' in l for l in lines)

        if not has_id or not has_tutar or len(lines) < 4:
            return None

        msg = ParsedMessage(raw_text=text, is_structured=True)

        for i, line in enumerate(lines):
            # ID satırı
            id_match = re.match(r'ID:\s*(\d+)', line, re.IGNORECASE)
            if id_match:
                msg.musteri_id = id_match.group(1)
                # İlk satır isim olabilir
                if i > 0 and not lines[i-1].startswith('@') and not lines[i-1].startswith('-'):
                    # Bir önceki @username ise, ondan önceki isimdir
                    if i >= 2 and lines[i-1].startswith('@'):
                        msg.musteri_adi = lines[i-2]
                    elif not lines[i-1].startswith('@'):
                        msg.musteri_adi = lines[0]  # İlk satır genelde isim
                continue

            # Username satırı
            if line.startswith('@'):
                msg.musteri_username = line[1:]  # @ işaretini kaldır
                continue

            # IBAN satırı
            iban_match = self.IBAN_PATTERN.match(line)
            if iban_match:
                msg.iban = line.replace(' ', '')
                continue

            # Tutar satırı
            if '₺' in line:
                is_negative = line.strip().startswith('-')
                tutar_info = self._extract_tutar(line)
                if tutar_info:
                    msg.tutar, msg.tutar_str, msg.para_birimi, _ = tutar_info
                    msg.tutar_yonu = "cekim" if is_negative else "yatirim"
                continue

            # Talep tarihi
            talep_match = self.TALEP_PATTERN.match(line)
            if talep_match:
                msg.talep_tarihi = talep_match.group(1)
                continue

            # Durum satırı
            durum = self._detect_durum(line)
            if durum and line.strip() != '-':
                msg.durum = durum
                continue

        # İlk satırı isim olarak al (eğer henüz bulunamadıysa)
        if not msg.musteri_adi and lines:
            first = lines[0]
            if not first.startswith('@') and not first.startswith('ID:') and '₺' not in first:
                msg.musteri_adi = first

        # İşlem tipini belirle
        msg.islem_tipi, msg.confidence = self._detect_islem_tipi(text)

        # Yapılandırılmış blokta çekim/yatırım tespiti
        if msg.islem_tipi == IslemTipi.BILINMIYOR:
            if msg.tutar_yonu == "cekim":
                msg.islem_tipi = IslemTipi.CEKIM_TALEBI
                msg.confidence = 0.8
            elif msg.durum == "bekleyen":
                msg.islem_tipi = IslemTipi.BEKLEYEN
                msg.confidence = 0.8

        msg.keywords = self._extract_keywords(text)
        msg.platform = self._extract_platform(text)

        return msg

    def _parse_kt_format(self, text: str) -> Optional[ParsedMessage]:
        """
        KT grubu formatını parse eder.
        Format: FATOM5858  737266144  Sebahattin  Kılıç
                Anında Havale dekont iletildi kt lütfen
        """
        match = self.KT_FORMAT_PATTERN.search(text)
        if not match:
            return None

        msg = ParsedMessage(raw_text=text)
        msg.musteri_username = match.group(1)
        msg.musteri_id = match.group(2)
        msg.musteri_adi = f"{match.group(3)} {match.group(4)}"
        msg.platform = self._extract_platform(text)
        msg.islem_tipi, msg.confidence = self._detect_islem_tipi(text)

        # KT talebi mi?
        if msg.islem_tipi == IslemTipi.BILINMIYOR:
            text_lower = text.lower()
            if 'kt' in text_lower or 'dekont' in text_lower:
                msg.islem_tipi = IslemTipi.KT
                msg.confidence = 0.8

        msg.keywords = self._extract_keywords(text)
        msg.iban = self._extract_iban(text)
        tutar_info = self._extract_tutar(text)
        if tutar_info:
            msg.tutar, msg.tutar_str, msg.para_birimi, msg.tutar_yonu = tutar_info

        return msg

    def _extract_id(self, text: str) -> Optional[str]:
        match = self.ID_PATTERN.search(text)
        return match.group(1) if match else None

    def _extract_username(self, text: str) -> Optional[str]:
        match = self.USERNAME_PATTERN.search(text)
        return match.group(1) if match else None

    def _extract_name(self, text: str) -> Optional[str]:
        lines = text.strip().split('\n')

        # Format 1: İlk satır isim, ikinci satır @username
        if len(lines) >= 2 and lines[1].strip().startswith('@'):
            name = lines[0].strip()
            if name and not name.startswith('ID:') and '₺' not in name:
                return name

        # Format 2: "isim @username" aynı satırda
        pattern = re.compile(r'([a-zA-ZçğıöşüÇĞIİÖŞÜ]+\s+[a-zA-ZçğıöşüÇĞIİÖŞÜ]+)\s*@')
        match = pattern.search(text)
        if match:
            return match.group(1).strip()

        # Format 3: KT formatı "USERNAME ID AD SOYAD"
        kt_match = self.KT_FORMAT_PATTERN.search(text)
        if kt_match:
            return f"{kt_match.group(3)} {kt_match.group(4)}"

        return None

    def _extract_tutar(self, text: str):
        is_cekim = '-₺' in text or text.strip().startswith('-')
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
                    yonu = "cekim" if is_cekim else ""
                    return tutar, tutar_str, para, yonu
                except ValueError:
                    continue
        return None

    def _extract_talep_tarihi(self, text: str) -> Optional[str]:
        match = self.TALEP_PATTERN.search(text)
        return match.group(1) if match else None

    def _extract_hash(self, text: str) -> Optional[str]:
        # SHA256 hash (64 karakter)
        match = self.HASH_PATTERN.search(text)
        if match:
            return match.group(1)
        # Kısa hash
        match = self.SHORT_HASH_PATTERN.search(text)
        if match and len(match.group(1)) >= 8:
            # Hash'in mesajın ana içeriği olup olmadığını kontrol et
            if text.strip() == match.group(1):
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
