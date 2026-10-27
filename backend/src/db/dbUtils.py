from __future__ import annotations

from sqlalchemy.engine import URL


def parse_connection_string(connection_string):
    normalized_connection_string = connection_string.strip()
    lowercase_connection_string = normalized_connection_string.lower()
    if lowercase_connection_string.startswith(("sqlite", "postgresql")):
        return normalized_connection_string
    elif lowercase_connection_string.startswith(("server=", "data source=")):
        return parse_mssql(normalized_connection_string)
    else:
        raise ValueError("Unsupported connection string format")


def parse_mssql(conn_string: str) -> str:
    params = {}
    for item in conn_string.split(";"):
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        params[key.strip().lower()] = value.strip()

    server_value = params.get("server") or params.get("data source")
    if not server_value:
        raise ValueError("SQL Server connection string must include Server or Data Source.")

    server_value = server_value.removeprefix("tcp:")
    host, separator, port_value = server_value.rpartition(",")
    if not separator:
        host, port_value = server_value, ""

    trust_server_certificate = params.get("trustservercertificate", "no")
    if trust_server_certificate.lower() in {"true", "yes", "1"}:
        trust_server_certificate = "yes"
    else:
        trust_server_certificate = "no"

    encrypt = params.get("encrypt", "yes")
    if encrypt.lower() in {"true", "yes", "1"}:
        encrypt = "yes"
    else:
        encrypt = "no"

    url = URL.create(
        "mssql+pyodbc",
        username=params.get("user id") or params.get("uid"),
        password=params.get("password") or params.get("pwd"),
        host=host,
        port=int(port_value) if port_value else None,
        database=params.get("initial catalog") or params.get("database"),
        query={
            "driver": params.get("driver", "ODBC Driver 18 for SQL Server"),
            "Encrypt": encrypt,
            "TrustServerCertificate": trust_server_certificate,
            "charset": "utf8",
        },
    )
    return url.render_as_string(hide_password=False)
