# parabolas-manpages

### Dependencies

- mandoc
- python3

### Usage

1. Install pip dependencies

```
pip install -r requirements.txt
```

2. Run the indexer

```
flask run-indexer
```

3. Run the web server

```
flask run
```

or

```
gunicorn web:create_app()
```
