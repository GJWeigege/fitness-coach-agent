def test_all_tables_registered():
    from app.db import models

    names = {t.name for t in models.Base.metadata.tables.values()}
    assert "users" in names
    assert "user_profiles" in names
    assert "graph_entities" in names
    assert "benchmark_runs" in names
    assert "tickets" not in names
