import os
from dotenv import load_dotenv

load_dotenv()


def _parse_group_list(value):
    """Virgülle ayrılmış grup ID listesini parse eder."""
    if not value:
        return []
    return [g.strip() for g in value.split(",") if g.strip()]


class Config:
    # Telegram Bot
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")

    # Telegram Client API (Pyrogram)
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")

    # Admin
    ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

    # Gruplar (virgülle ayrılmış ID listesi)
    # SOURCE_GROUPS = Bayi/SAHA grupları (taleplerin geldiği yer)
    # VERIFY_GROUPS = Çekim Operasyon / Yatırım Destek (son teyid)
    SOURCE_GROUPS = _parse_group_list(os.getenv("SOURCE_GROUPS", ""))
    VERIFY_GROUPS = _parse_group_list(os.getenv("VERIFY_GROUPS", ""))
    REPORT_CHANNEL = os.getenv("REPORT_CHANNEL", "")

    # Eski tek grup desteği (geriye uyumluluk)
    SOURCE_GROUP = os.getenv("SOURCE_GROUP", "")
    VERIFY_GROUP = os.getenv("VERIFY_GROUP", "")

    # Payment API (russ-payment)
    PAYMENT_API_URL = os.getenv("PAYMENT_API_URL", "https://api.russ-payment.com/api/v1")
    PAYMENT_API_KEY = os.getenv("PAYMENT_API_KEY", "")
    PAYMENT_SECRET_KEY = os.getenv("PAYMENT_SECRET_KEY", "")

    # Ayarlar
    SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "5"))
    MATCH_THRESHOLD = int(os.getenv("MATCH_THRESHOLD", "75"))
    DELAY_THRESHOLD_MINUTES = int(os.getenv("DELAY_THRESHOLD_MINUTES", "15"))
    PUSH_INTERVAL = int(os.getenv("PUSH_INTERVAL", "3"))

    # Veritabanı
    DB_PATH = os.path.join(os.path.dirname(__file__), "data", "verifier.db")

    @classmethod
    def get_source_groups(cls):
        """Tüm kaynak grupları döner."""
        groups = list(cls.SOURCE_GROUPS)
        if cls.SOURCE_GROUP and cls.SOURCE_GROUP not in groups:
            groups.append(cls.SOURCE_GROUP)
        return groups

    @classmethod
    def get_verify_groups(cls):
        """Tüm doğrulama grupları döner."""
        groups = list(cls.VERIFY_GROUPS)
        if cls.VERIFY_GROUP and cls.VERIFY_GROUP not in groups:
            groups.append(cls.VERIFY_GROUP)
        return groups

    @classmethod
    def validate(cls):
        errors = []
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN eksik")
        if not cls.API_ID:
            errors.append("API_ID eksik")
        if not cls.API_HASH:
            errors.append("API_HASH eksik")
        if not cls.ADMIN_USER_ID:
            errors.append("ADMIN_USER_ID eksik")
        if not cls.get_source_groups():
            errors.append("SOURCE_GROUPS eksik")
        if not cls.get_verify_groups():
            errors.append("VERIFY_GROUPS eksik")
        return errors
