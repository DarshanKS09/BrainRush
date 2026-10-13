"""Import smoke tests (no network, no DB)."""


def test_package_imports():
    import brainrush
    import brainrush.api.app
    import brainrush.api.auth
    import brainrush.api.deps
    import brainrush.api.routes
    import brainrush.bot.factory
    import brainrush.bot.handlers
    import brainrush.bot.middleware
    import brainrush.config
    import brainrush.db.base
    import brainrush.db.models
    import brainrush.db.repository
    import brainrush.db.session
    import brainrush.game.engine
    import brainrush.game.number_guessing
    import brainrush.game.progression
    import brainrush.game.store
    import brainrush.healthcheck
    import brainrush.services.games
    import brainrush.services.miniapp
    import brainrush.services.profiles
    import brainrush.services.users

    assert brainrush.__version__ == "0.1.0"


def test_dispatcher_builds_offline():
    from brainrush.bot.factory import create_dispatcher

    dp = create_dispatcher()
    assert dp is not None
