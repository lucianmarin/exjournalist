# Falcon Blog App (Django ORM)

A blogging app built with:
- Falcon (WSGI)
- Django ORM
- Jinja2 templates
- PostgreSQL
- Markdown content support

## Features

- Cookie authentication with encrypted user ID in the cookie value
- Create and view user profiles with:
  - Username
  - Password
  - Emoji
  - Full name
  - Email address
  - Markdown description
- Create and view articles by the authenticated user
- Edit your own articles
- Each article belongs to exactly one category (select existing or create new)
  - Category names are always stored in lowercase and allow letters only (`a-z`)
- User profile pages with all articles by that user
- Category pages with all articles in that category
- Like/Dislike voting per article (uses authenticated cookie user)
- Nested comments per article (uses authenticated cookie user)
- Markdown rendering for user descriptions, articles, and comments

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy environment file:

```bash
cp .env.example .env
```

4. Create and apply Django migrations:

```bash
python3 manage.py makemigrations app
python3 manage.py migrate
```

5. Run with Gunicorn:

```bash
gunicorn main:app --bind 127.0.0.1:8000 --workers 2
```

6. Open: http://127.0.0.1:8000

## Notes

- Database configuration comes from `DATABASE_URL` in `.env`.
- Set a strong `SECRET_KEY` in production; it is used to derive the encryption key for auth cookies.
- Votes are tracked per user (`ArticleVote.voter`) with one vote per user per article.
