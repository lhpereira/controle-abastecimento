"""Cópia do banco SQLite para download, sem dados de sessão nem de tentativas de login."""

import sqlite3

from django.db import connection


# Tabelas esvaziadas na cópia. As chaves em django_session são os próprios cookies de
# login: quem tivesse o arquivo poderia assumir uma sessão ativa. As tabelas do axes
# guardam IPs e user agents de quem tentou entrar. O schema é preservado para que o
# arquivo continue restaurável com as mesmas migrações.
EXCLUDED_TABLES = (
    "django_session",
    "axes_accessattempt",
    "axes_accessattemptexpiration",
    "axes_accessfailurelog",
    "axes_accesslog",
)


def sanitized_sqlite_backup() -> bytes:
    connection.ensure_connection()
    # serialize() lê uma imagem consistente do banco sob um lock de leitura e funciona
    # também dentro de transações (a API backup() retornaria SQLITE_LOCKED nesse caso).
    image = connection.connection.serialize()
    target = sqlite3.connect(":memory:")
    try:
        target.deserialize(image)
        existing = {name for (name,) in target.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table in EXCLUDED_TABLES:
            if table in existing:
                target.execute(f'DELETE FROM "{table}"')
        target.commit()
        target.execute("VACUUM")  # remove do arquivo as páginas com os dados apagados
        return target.serialize()
    finally:
        target.close()
