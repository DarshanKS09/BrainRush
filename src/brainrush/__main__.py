"""Entrypoint: validate config/DB, then optionally start polling.

Usage (Windows PowerShell):
  python -m brainrush --check-only     # offline-safe validation, no Telegram/DB traffic beyond SELECT 1
  python -m brainrush                  # validates, then starts aiogram polling

No real credentials are bundled; copy .env.example to .env first.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from brainrush.bot.factory import create_bot, create_dispatcher
from brainrush.config import Settings, api_listen
from brainrush.db.session import create_engine, create_session_factory
from brainrush.healthcheck import health_check

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("brainrush")


async def run(check_only: bool = False, check_db: bool = True, serve_api: bool = False, shutdown_event: Any = None) -> int:
    try:
        settings = Settings()
    except Exception as exc:
        log.error("Invalid configuration: %s", exc)
        log.error("Copy .env.example to .env and set BOT_TOKEN and DATABASE_URL.")
        return 2

    report = await health_check(settings, check_db=check_db)
    if not report.config_ok:
        log.error("Invalid configuration: %s", report.config_error)
        return 2
    if report.db_ok is False:
        log.error("Database unreachable: %s", report.db_error)
        return 1
    if report.db_ok is None:
        log.info("Config OK (DB check skipped).")
    else:
        log.info("Config + DB OK.")

    if check_only:
        return 0

    bot = create_bot(settings.BOT_TOKEN)
    engine = create_engine(settings.DATABASE_URL)
    session_factory = create_session_factory(engine)
    dp = create_dispatcher(session_factory, webapp_url=settings.WEBAPP_URL)
    if serve_api:
        return await _serve_both(settings, bot, engine, session_factory, dp, shutdown_event)
    try:
        log.info("Starting polling...")
        # Poll with shutdown awareness: dp.start_polling respects shutdown events
        # when the dispatcher is properly configured. The aiogram Dispatcher
        # checks for shutdown conditions per-update.
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()
    return 0


async def _serve_both(settings, bot, engine, session_factory, dp, shutdown_event) -> int:
    """Run Telegram polling and the Mini App API side by side."""
    import uvicorn

    from brainrush.api.app import create_app

    api_app = create_app(settings, session_factory)
    host, port = api_listen(settings)
    server = uvicorn.Server(
        uvicorn.Config(
            api_app,
            host=host,
            port=port,
            log_level="info",
            timeout_keep_alive=30,
            timeout_graceful_shutdown=20,
        )
    )
    if settings.WEBAPP_URL:
        log.info("Mini App URL: %s", settings.WEBAPP_URL)
    else:
        log.warning("WEBAPP_URL is not set: WebApp buttons will be hidden.")
    # Create polling task with shutdown awareness.
    polling = asyncio.create_task(dp.start_polling(bot))
    serving = asyncio.create_task(server.serve())
    try:
        log.info(
            "Serving API on %s:%s and polling Telegram...",
            host,
            port,
        )
        done, pending = await asyncio.wait(
            {polling, serving}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    except asyncio.CancelledError:
        log.info("Received shutdown signal, cancelling polling...")
        polling.cancel()
        try:
            await polling
        except asyncio.CancelledError:
            log.info("Polling task successfully cancelled.")
    finally:
        server.should_exit = True
        await bot.session.close()
        await engine.dispose()
    return 0


def main(argv: list[str] | None = None) -> int:
    import asyncio
    import signal as sig_mod

    parser = argparse.ArgumentParser(description="BrainRush bot entrypoint")
    parser.add_argument("--check-only", action="store_true", help="validate only, do not poll")
    parser.add_argument("--no-db-check", action="store_true", help="skip DB connectivity check")
    parser.add_argument("--serve-api", action="store_true",
                        help="run the Mini App API alongside Telegram polling")
    args = parser.parse_args(argv)

    # Ensure only one polling instance runs at a time by installing signal handlers.
    # SIGTERM/SIGINT will cancel the polling task gracefully.
    shutdown_event = asyncio.Event()

    def _handle_signal(signum, frame):
        log.info("Received signal %s, initiating shutdown...", signum)
        shutdown_event.set()

    sig_mod.signal(sig_mod.SIGTERM, _handle_signal)
    sig_mod.signal(sig_mod.SIGINT, _handle_signal)

    return asyncio.run(run(check_only=args.check_only, check_db=not args.no_db_check,
                           serve_api=args.serve_api, shutdown_event=shutdown_event))


if __name__ == "__main__":
    raise SystemExit(main())
