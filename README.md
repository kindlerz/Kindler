# 📚 Kindler  

[![Docker Pulls](https://img.shields.io/docker/pulls/kasramp/kindler.svg)](https://hub.docker.com/repository/docker/kasramp/kindler/general)
[![Build Status](https://img.shields.io/github/actions/workflow/status/kindlerz/kindler/build_and_deploy.yml?branch=master)](https://github.com/kindlerz/kindler/actions)
[![License](https://img.shields.io/github/license/kindlerz/kindler)](LICENSE)

> 🖋️ *Web surfing and reading reimagined for e-ink devices.*

Kindler is a lightweight, open-source web app built to make e-ink devices like Kindles actually useful on the modern web. Browse the internet, read news, or explore public-domain books, all through a clean, no JavaScript interface that works even on the most limited browsers.

Built with **Python (Flask + Jinja2)**, **Redis**, and **Calibre**, Kindler lets you instantly convert any webpage, news article, or Gemini capsule into **EPUB**, **MOBI**, or **AZW3**. The project is fully containerized and **Docker Swarm–ready**. It depends on a Java-based [Metasearch](https://github.com/kindlerz/metasearch) backend for federated search across public-domain libraries.

🐳 **Docker Hub:** [kasramp/kindler](https://hub.docker.com/repository/docker/kasramp/kindler/general)  
🌍 **Live Demo:** [kindler.ink](https://kindler.ink)  
💻 **Org:** [github.com/kindlerz](https://github.com/kindlerz)

## Development set up

### Virtual env

If it does not exist, create one:

```bash
$ python3 -m venv .venv
```

To activate:

```bash
$ source .venv/bin/activate
```

To deactivate:

```bash
$ deactivate
```

### Useful commands

Generate `requirement.txt` file:

```bash
$ pip3 freeze > requirements.txt
```

To install from the dependency file:

```bash
$ pip3 install -r requirements.txt
```

## Run the project

The project is dependent on Redis. Make sure to have it available.

### Local development

For local development, before running the project, bring up the Redis from `docker-compose.yml` file:

```bash
$ docker compose -f docker-compose.yml up
```

Then run:

```bash
$ python -m kindler.app
```

### Production (Gunicorn WSGI)

Make sure you also deploy [Metasearch](https://github.com/kindlerz/metasearch), without it, Kindler public-domain libraries do not work.

Ensure the Redis cluster is up and running. Then set the below env var:

```bash
$ export REDIS_URL=[YOUR_REDIS_URL]
```

```bash
$ gunicorn kindler.wsgi:app
```

## Calibre

To support generating epub, mobi, azw3 of pages on the fly, need to install calibre, or more specific `ebook-convert` as it's invoked as a sub process to generate ebooks.

## Building with Docker

Run:

```bash
$ docker build -t kindler-app .
```

To test:

```bash
$ docker run -p 8181:8181 kindler-app
```

Test an image from Docker Hub:

```bash
$ docker run -p 8181:8181 kasramp/kindler:v0.0.2
```

## Code formatting

Before committing or sending any PR to review, make sure the code is formatted correctly. You can run `black`:

```bash
$ black --check .
```

To fix:

```bash
$ black .
```
