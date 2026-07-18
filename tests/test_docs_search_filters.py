import tempfile
from beaver import BeaverDB, q

def test_sync_search_with_where_and_limit():
    db = BeaverDB(tempfile.mktemp(suffix=".db"))
    col = db.docs("lugares")
    col.index(id="1", body={"norm_nombre": "calle 23", "tipo": "calle", "lat": 23.14, "lon": -82.38})
    col.index(id="2", body={"norm_nombre": "hotel nacional", "tipo": "poi", "lat": 23.145, "lon": -82.383})
    col.index(id="3", body={"norm_nombre": "calle 12", "tipo": "calle", "lat": 23.10, "lon": -82.42})

    # FTS + metadata filter, synchronously
    res = col.search(query="calle", on=["norm_nombre"], where=[q("tipo") == "calle"], limit=5)
    names = sorted(s.document.body["norm_nombre"] for s in res)
    assert names == ["calle 12", "calle 23"]

    # Pure range filter (reverse-geo bbox), no FTS
    res2 = col.search(where=[q("lat") >= 23.12, q("lat") <= 23.16,
                             q("lon") >= -82.40, q("lon") <= -82.36], limit=10)
    names2 = sorted(s.document.body["norm_nombre"] for s in res2)
    assert names2 == ["calle 23", "hotel nacional"]
    db.close()
