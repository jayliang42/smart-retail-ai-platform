from smart_retail.repositories.postgres import normalize_database_url


def test_provider_postgresql_url_uses_installed_psycopg_driver() -> None:
    assert normalize_database_url("postgresql://user:secret@db/app") == (
        "postgresql+psycopg://user:secret@db/app"
    )


def test_explicit_sqlalchemy_driver_is_preserved() -> None:
    url = "postgresql+psycopg://user:secret@db/app"

    assert normalize_database_url(url) == url
