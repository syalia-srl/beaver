from beaver.api import expose, local_only, EndpointMeta


def test_expose_attaches_endpoint_meta():
    @expose(path="/{key}", method="GET", cli_name="get", cli_help="Get a value.")
    def get(key: str): ...

    meta = get.__beaver_endpoint__
    assert isinstance(meta, EndpointMeta)
    assert meta.path == "/{key}"
    assert meta.method == "GET"
    assert meta.cli_name == "get"
    assert meta.cli_help == "Get a value."
    assert meta.body_param is None


def test_expose_with_body_param():
    @expose(
        path="/{key}", method="PUT", cli_name="set", cli_help="Set.", body_param="value"
    )
    def set(key, value, ttl_seconds=None): ...

    assert set.__beaver_endpoint__.body_param == "value"


def test_local_only_marks_method():
    @local_only("only available on local databases")
    def keys(): ...

    assert keys.__beaver_local_only__ == "only available on local databases"


def test_endpoint_meta_is_frozen():
    import dataclasses

    meta = EndpointMeta(path="/", method="GET", cli_name="x", cli_help="x")
    try:
        meta.path = "/changed"
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("EndpointMeta must be frozen")
