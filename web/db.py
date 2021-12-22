import sqlite3

import click
from flask import current_app, g
from flask.cli import with_appcontext

import asyncio
from indexer.indexer import main

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row

    return g.db

def close_db(e=None):
    db = g.pop('db', None)

    if db is not None:
        db.close()

@click.command('run-indexer')
def run_indexer_command():
    asyncio.run(main())
    click.echo("Ran the indexer.")

def init_app(app):
    app.teardown_appcontext(close_db) # close db after response
    app.cli.add_command(run_indexer_command)
