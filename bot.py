import asyncio
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from config import Config
from database import add_rule, get_rules, get_recent_verifications, get_verification_stats
from verifier import VerificationEngine
from scanner import GroupScanner
import logging

logger = logging.getLogger(__name__)


class VerifierBot:
    def __init__(self, scanner: GroupScanner, verifier: VerificationEngine):
        self.scanner = scanner
        self.verifier = verifier
        self.app = None

    def _is_admin(self, user_id: int) -> bool:
        return user_id == Config.ADMIN_USER_ID

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Yetkiniz yok.")
            return

        await update.message.reply_text(
            "🔍 **Ödeme Doğrulama Botu**\n\n"
            "**Temel Komutlar:**\n"
            "/scan - Grupları tara\n"
            "/verify - Doğrulama çalıştır\n"
            "/report - Rapor göster\n\n"
            "**Sorgulama:**\n"
            "/musteri <isim/ID> - Müşteri işlem detayı\n"
            "/tutarsizlik - Tutarsızlık listesi\n"
            "/search <metin> - Gruplarda ara\n\n"
            "**Yönetim:**\n"
            "/rules - Aktif kuralları listele\n"
            "/addrule - Yeni kural ekle\n"
            "/status - Bot durumu\n"
            "/help - Yardım",
            parse_mode="Markdown"
        )

    async def cmd_scan(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        msg = await update.message.reply_text("🔄 Gruplar taranıyor...")

        try:
            results = await self.scanner.scan_all_groups()
            text = "✅ **Tarama Tamamlandı**\n\n"
            text += f"� Bayi grupları: {results.get('source', 0)} yeni mesaj ({results.get('source_groups', 0)} grup)\n"
            text += f"📥 Teyid grupları: {results.get('verify', 0)} yeni mesaj ({results.get('verify_groups', 0)} grup)"
            await msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            await msg.edit_text(f"❌ Tarama hatası: {e}")

    async def cmd_verify(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        msg = await update.message.reply_text("🔍 Doğrulama çalıştırılıyor...")

        try:
            result = await self.verifier.run_verification()
            issues = result.get("issues", [])
            rule_results = result.get("rule_results", [])
            total_src = result.get("total_source", 0)
            total_ver = result.get("total_verify", 0)

            text = f"✅ **Doğrulama Tamamlandı**\n"
            text += f"📤 Kaynak: {total_src} mesaj | 📥 Doğrulama: {total_ver} mesaj\n\n"

            # Kritik tutarsızlıklar
            if issues:
                text += f"🔴 **{len(issues)} TUTARSIZLIK TESPİT EDİLDİ:**\n"
                for issue in issues[:5]:
                    text += f"  • {issue['message'][:100]}\n"
                if len(issues) > 5:
                    text += f"  ... ve {len(issues) - 5} daha\n"
                text += "\n"

            # Kural eşleşmeleri
            if rule_results:
                text += f"📋 **{len(rule_results)} Kural Eşleşmesi:**\n"
                status_icons = {"confirmed": "✅", "partial": "⚠️", "inconsistent": "🔴", "pending": "⏳"}
                for r in rule_results[:5]:
                    icon = status_icons.get(r['status'], '❓')
                    text += f"  {icon} [{r['rule_name']}] {r['details'][:80]}\n"
                if len(rule_results) > 5:
                    text += f"  ... ve {len(rule_results) - 5} daha\n"

            if not issues and not rule_results:
                text += "ℹ️ Tutarsızlık veya eşleşme bulunamadı."

            await msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Doğrulama hatası: {e}", exc_info=True)
            await msg.edit_text(f"❌ Doğrulama hatası: {e}")

    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        try:
            report = await self.verifier.get_report()
            await update.message.reply_text(report, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Rapor hatası: {e}")

    async def cmd_rules(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        rules = await get_rules(active_only=False)
        if not rules:
            await update.message.reply_text("ℹ️ Henüz kural tanımlanmamış.\n/addrule ile ekleyebilirsiniz.")
            return

        text = "📋 **Doğrulama Kuralları:**\n\n"
        for r in rules:
            active = "✅" if r["is_active"] else "❌"
            text += f"{active} **{r['name']}** [{r['rule_type']}]\n"
            text += f"   Kaynak: `{r['source_pattern']}`\n"
            if r["verify_pattern"]:
                text += f"   Doğrulama: `{r['verify_pattern']}`\n"
            text += "\n"

        await update.message.reply_text(text, parse_mode="Markdown")

    async def cmd_addrule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        args = context.args
        if not args or len(args) < 3:
            await update.message.reply_text(
                "📝 **Kural Ekleme Formatı:**\n\n"
                "`/addrule <isim> <tip> <kaynak_pattern> [doğrulama_pattern]`\n\n"
                "**Tipler:**\n"
                "• `keyword` - Anahtar kelime eşleşmesi\n"
                "• `pattern` - Regex pattern eşleşmesi\n"
                "• `user_claim` - Kullanıcı iddia doğrulama\n"
                "• `amount` - Tutar/miktar doğrulama\n"
                "• `custom` - Fuzzy matching\n\n"
                "**Örnekler:**\n"
                "`/addrule odeme_kontrol user_claim ödeme|transfer|gönder`\n"
                "`/addrule fiyat_check amount \\d+\\s*(TL|USD|EUR)`\n"
                "`/addrule trade_verify keyword alım|satım|trade`",
                parse_mode="Markdown"
            )
            return

        name = args[0]
        rule_type = args[1]
        source_pattern = args[2]
        verify_pattern = args[3] if len(args) > 3 else None

        valid_types = ["keyword", "pattern", "user_claim", "amount", "custom"]
        if rule_type not in valid_types:
            await update.message.reply_text(f"❌ Geçersiz tip. Geçerli tipler: {', '.join(valid_types)}")
            return

        try:
            await add_rule(name, rule_type, source_pattern, verify_pattern)
            await update.message.reply_text(f"✅ Kural eklendi: **{name}** [{rule_type}]", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Kural ekleme hatası: {e}")

    async def cmd_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        query = " ".join(context.args) if context.args else ""
        if not query:
            await update.message.reply_text("Kullanım: `/search <aranacak metin>`", parse_mode="Markdown")
            return

        msg = await update.message.reply_text(f"🔍 '{query}' aranıyor...")

        try:
            source_results = []
            verify_results = []

            # Tüm kaynak gruplarda ara
            for gid in Config.get_source_groups():
                results = await self.scanner.search_messages(gid, query, limit=5)
                source_results.extend(results)

            # Tüm doğrulama gruplarda ara
            for gid in Config.get_verify_groups():
                results = await self.scanner.search_messages(gid, query, limit=5)
                verify_results.extend(results)

            text = f"🔍 **Arama Sonuçları:** '{query}'\n\n"

            if source_results:
                text += f"**📤 Bayi Grupları ({len(source_results)} sonuç):**\n"
                for r in source_results[:5]:
                    preview = r["text"][:80]
                    text += f"  • @{r['username'] or 'anonim'}: {preview}\n"
                text += "\n"

            if verify_results:
                text += f"**📥 Teyid Grupları ({len(verify_results)} sonuç):**\n"
                for r in verify_results[:5]:
                    preview = r["text"][:80]
                    text += f"  • @{r['username'] or 'anonim'}: {preview}\n"

            if not source_results and not verify_results:
                text = f"ℹ️ '{query}' için sonuç bulunamadı."

            await msg.edit_text(text, parse_mode="Markdown")
        except Exception as e:
            await msg.edit_text(f"❌ Arama hatası: {e}")

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        try:
            source_info = await self.scanner.get_group_info(Config.SOURCE_GROUP)
            verify_info = await self.scanner.get_group_info(Config.VERIFY_GROUP)
            stats = await get_verification_stats()

            text = "📡 **Bot Durumu**\n\n"
            text += "**Gruplar:**\n"
            if source_info:
                text += f"  📤 Kaynak: {source_info['title']} ({source_info['members_count']} üye)\n"
            if verify_info:
                text += f"  📥 Doğrulama: {verify_info['title']} ({verify_info['members_count']} üye)\n"

            text += f"\n**Tarama Aralığı:** {Config.SCAN_INTERVAL} dk\n"
            text += f"**Eşleşme Eşiği:** {Config.MATCH_THRESHOLD}%\n"

            total = sum(stats.values()) if stats else 0
            text += f"\n**Toplam Doğrulama:** {total}"

            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Durum hatası: {e}")

    async def cmd_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """API işlem durumu sorgulama."""
        if not self._is_admin(update.effective_user.id):
            return

        if not Config.PAYMENT_API_KEY:
            await update.message.reply_text("⚠️ Payment API yapılandırılmamış.")
            return

        from api_client import RussPaymentAPI
        api = RussPaymentAPI()

        sub_cmd = context.args[0] if context.args else "durum"

        if sub_cmd == "geciken":
            msg = await update.message.reply_text("🔍 Geciken işlemler kontrol ediliyor...")
            try:
                delayed = await api.get_delayed_transactions(max_age_minutes=Config.DELAY_THRESHOLD_MINUTES)
                if not delayed:
                    await msg.edit_text("✅ Geciken işlem yok.")
                    return
                text = f"⚠️ **{len(delayed)} Geciken İşlem ({Config.DELAY_THRESHOLD_MINUTES}+ dk):**\n\n"
                for tx in delayed[:10]:
                    tx_id = tx.get("transactionId") or tx.get("id", "?")
                    name = tx.get("playerFullName") or "?"
                    amount = tx.get("amount", "?")
                    age = tx.get("_age_minutes", "?")
                    text += f"  • `{tx_id}` | {name} | ₺{amount} | {age} dk\n"
                if len(delayed) > 10:
                    text += f"\n... ve {len(delayed) - 10} daha"
                await msg.edit_text(text, parse_mode="Markdown")
            except Exception as e:
                await msg.edit_text(f"❌ API hatası: {e}")

        elif sub_cmd == "islemler":
            msg = await update.message.reply_text("🔍 Bugünkü işlemler çekiliyor...")
            try:
                txs = await api.get_transactions()
                if not txs:
                    await msg.edit_text("ℹ️ Bugün işlem bulunamadı.")
                    return
                approved = sum(1 for t in txs if (t.get("status") or "").upper() == "APPROVED")
                rejected = sum(1 for t in txs if (t.get("status") or "").upper() == "REJECTED")
                pending = len(txs) - approved - rejected
                text = f"📊 **Bugünkü İşlemler ({len(txs)} toplam):**\n\n"
                text += f"  ✅ Onaylı: {approved}\n"
                text += f"  ❌ Red: {rejected}\n"
                text += f"  ⏳ Bekleyen: {pending}\n"
                await msg.edit_text(text, parse_mode="Markdown")
            except Exception as e:
                await msg.edit_text(f"❌ API hatası: {e}")

        else:
            await update.message.reply_text(
                "📡 **API Komutları:**\n\n"
                "`/api geciken` — Geciken işlemleri listele\n"
                "`/api islemler` — Bugünkü işlem özeti\n",
                parse_mode="Markdown"
            )

    async def cmd_musteri(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Müşteri bazlı işlem sorgulama."""
        if not self._is_admin(update.effective_user.id):
            return

        query = " ".join(context.args) if context.args else ""
        if not query:
            await update.message.reply_text(
                "Kullanım: `/musteri <isim veya ID>`\n"
                "Örnek: `/musteri mediha tekgöz`",
                parse_mode="Markdown"
            )
            return

        msg = await update.message.reply_text(f"🔍 '{query}' sorgulanıyor...")

        try:
            detail = await self.verifier.get_transaction_detail(query)
            await msg.edit_text(detail, parse_mode="Markdown")
        except Exception as e:
            await msg.edit_text(f"❌ Sorgulama hatası: {e}")

    async def cmd_tutarsizlik(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Tüm tutarsızlıkları listele."""
        if not self._is_admin(update.effective_user.id):
            return

        try:
            issues = self.verifier.tracker.get_all_inconsistencies()
            if not issues:
                await update.message.reply_text("✅ Aktif tutarsızlık bulunamadı.")
                return

            text = f"🔴 **{len(issues)} Tutarsızlık Tespit Edildi:**\n\n"
            severity_order = {"critical": 0, "warning": 1, "info": 2}
            sorted_issues = sorted(issues, key=lambda x: severity_order.get(x["severity"], 3))

            for i, issue in enumerate(sorted_issues[:10], 1):
                icon = {"critical": "�", "warning": "⚠️", "info": "ℹ️"}.get(issue["severity"], "❓")
                text += f"{i}. {icon} **{issue['type']}**\n"
                text += f"   {issue['message'][:120]}\n\n"

            if len(issues) > 10:
                text += f"... ve {len(issues) - 10} tutarsızlık daha"

            await update.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {e}")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            return

        text = (
            "📖 **Ödeme Doğrulama Botu - Yardım**\n\n"
            "Bu bot, operasyon grubundaki mesajları tarayarak "
            "ödeme/API grubundaki mesajlarla çapraz doğrulama yapar.\n\n"
            "**Temel Akış:**\n"
            "1. `/scan` ile grupları tarayın\n"
            "2. `/verify` ile doğrulamayı çalıştırın\n"
            "3. `/report` ile sonuçları görün\n\n"
            "**Otomatik Kontroller:**\n"
            "• Çekim iptal edilmiş ama ödeme yapılmış\n"
            "• Personel onay vermiş ama API red döndü\n"
            "• Ödeme sağlanmış ama sistem red veriyor\n"
            "• Tutar uyuşmazlığı\n"
            "• İşlem eşleşme (ID, isim, tutar, hash)\n\n"
            "**Sorgulama:**\n"
            "`/musteri <isim/ID>` - Müşteri detayı\n"
            "`/tutarsizlik` - Tüm tutarsızlıklar\n"
            "`/search <metin>` - Serbest arama\n\n"
            "**Durum Kodları:**\n"
            "✅ Doğrulanmış | ⚠️ Kısmi | 🔴 Tutarsız | ❌ Red | ⏳ Bekleyen"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    def build(self) -> Application:
        self.app = Application.builder().token(Config.BOT_TOKEN).build()

        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("scan", self.cmd_scan))
        self.app.add_handler(CommandHandler("verify", self.cmd_verify))
        self.app.add_handler(CommandHandler("report", self.cmd_report))
        self.app.add_handler(CommandHandler("rules", self.cmd_rules))
        self.app.add_handler(CommandHandler("addrule", self.cmd_addrule))
        self.app.add_handler(CommandHandler("search", self.cmd_search))
        self.app.add_handler(CommandHandler("api", self.cmd_api))
        self.app.add_handler(CommandHandler("musteri", self.cmd_musteri))
        self.app.add_handler(CommandHandler("tutarsizlik", self.cmd_tutarsizlik))
        self.app.add_handler(CommandHandler("status", self.cmd_status))
        self.app.add_handler(CommandHandler("help", self.cmd_help))

        return self.app
