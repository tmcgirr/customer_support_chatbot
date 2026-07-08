from app.core.config import Settings


def test_mongo_db_name_pathless_defaults() -> None:
    assert Settings(mongo_uri="mongodb://localhost:27017").mongo_db_name == "cadre_chatbot"


def test_mongo_db_name_with_path() -> None:
    assert Settings(mongo_uri="mongodb://mongo:27017/mydb").mongo_db_name == "mydb"


def test_mongo_db_name_srv_with_creds_and_query() -> None:
    uri = "mongodb+srv://user:pass@cluster.example.com/prod?retryWrites=true"
    assert Settings(mongo_uri=uri).mongo_db_name == "prod"


def test_mongo_db_name_srv_no_db_defaults() -> None:
    assert Settings(mongo_uri="mongodb+srv://user:pass@cluster.example.com/").mongo_db_name == (
        "cadre_chatbot"
    )


def test_key_ring_active_key_wins_over_extra() -> None:
    settings = Settings(
        session_key_id="k1",
        session_secret="active",
        session_extra_secrets="k1:stale,k0:old",
    )
    ring = settings.session_key_ring
    assert ring["k1"] == "active"  # active secret overrides an extra with the same kid
    assert ring["k0"] == "old"


def test_feature_flags_default_off() -> None:
    settings = Settings(_env_file=None, env="dev")
    assert settings.feature_flags == {"delivery": False, "citations": False}


def test_feature_flags_env_override() -> None:
    settings = Settings(_env_file=None, env="dev", enable_citations=True)
    assert settings.feature_flags["citations"] is True
