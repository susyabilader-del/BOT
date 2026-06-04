import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import Config
from database import init_db
from scanner import GroupScanner
from verifier import VerificationEngine
from bot import VerifierBot
from pusher import TransactionPusher

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("data/verifier.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def scheduled_scan_and_verify(scanner: GroupScanner, verifier: VerificationEngine):
    """Zamanlı tarama ve doğrulama görevi."""
    try:
        logger.info("Otomatik tarama başlatıldı...")
        scan_results = await scanner.scan_all_groups()
        logger.info(f"Tarama sonucu: {scan_results}")

        logger.info("Otomatik doğrulama başlatıldı...")
        result = await verifier.run_verification()

        issues = result.get("issues", [])
        rule_results = result.get("rule_results", [])
        logger.info(
            f"Doğrulama sonucu: {len(issues)} tutarsızlık, "
            f"{len(rule_results)} kural eşleşmesi"
        )

        # Kritik tutarsızlıkları logla
        for issue in issues:
            if issue["severity"] == "critical":
                logger.warning(f"🔴 KRİTİK: {issue['message']}")
            else:
                logger.info(f"⚠️ {issue['type']}: {issue['message'][:100]}")

        # Tutarsız kural sonuçlarını logla
        for r in rule_results:
            if r["status"] == "inconsistent":
                logger.warning(f"🔴 TUTARSIZLIK: [{r['rule_name']}] {r['details'][:100]}")

    except Exception as e:
        logger.error(f"Zamanlı görev hatası: {e}", exc_info=True)


async def scheduled_push_delayed(pusher: TransactionPusher):
    """Geciken işlemleri kontrol edip bayi gruplarına bildirim gönderir."""
    try:
        if not Config.PAYMENT_API_KEY:
            return  # API yapılandırılmamış
        result = await pusher.check_and_push_delayed()
        if result.get("pushed", 0) > 0:
            logger.info(f"Push bildirim: {result['pushed']} mesaj gönderildi")
    except Exception as e:
        logger.error(f"Push görev hatası: {e}", exc_info=True)


async def main():
    # Config doğrulama
    errors = Config.validate()
    if errors:
        print("❌ Yapılandırma hataları:")
        for e in errors:
            print(f"   • {e}")
        print("\n.env dosyasını kontrol edin. Örnek: .env.example")
        return

    # Data klasörü oluştur
    import os
    os.makedirs("data", exist_ok=True)

    # Veritabanını başlat
    await init_db()
    logger.info("Veritabanı hazır")

    # Bileşenleri oluştur
    scanner = GroupScanner()
    verifier = VerificationEngine()
    bot = VerifierBot(scanner, verifier)

    # Pyrogram client'ı başlat
    await scanner.start()
    logger.info("Scanner başlatıldı")

    # Pusher oluştur (geciken işlem bildirimleri)
    pusher = TransactionPusher(scanner.client)

    # Zamanlayıcı
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_scan_and_verify,
        'interval',
        minutes=Config.SCAN_INTERVAL,
        args=[scanner, verifier],
        id='scan_verify_job',
        name='Otomatik Tarama & Doğrulama'
    )

    # Geciken işlem push kontrolü
    if Config.PAYMENT_API_KEY:
        scheduler.add_job(
            scheduled_push_delayed,
            'interval',
            minutes=Config.PUSH_INTERVAL,
            args=[pusher],
            id='push_delayed_job',
            name='Geciken İşlem Bildirimi'
        )
        logger.info(f"Push bildirimi aktif (aralık: {Config.PUSH_INTERVAL} dk, eşik: {Config.DELAY_THRESHOLD_MINUTES} dk)")

    scheduler.start()
    logger.info(f"Zamanlayıcı başlatıldı (tarama: {Config.SCAN_INTERVAL} dk)")

    # Bot'u başlat
    app = bot.build()
    logger.info("Bot başlatılıyor...")

    # Bot'u polling modunda çalıştır
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("✅ Bot çalışıyor! Durdurmak için Ctrl+C")

        # Sonsuz döngü - Ctrl+C ile durdurulana kadar çalışır
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Kapatılıyor...")
        finally:
            await app.updater.stop()
            await app.stop()
            scheduler.shutdown()
            await scanner.stop()
            logger.info("Bot kapatıldı")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
