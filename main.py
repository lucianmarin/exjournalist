import os
from base64 import urlsafe_b64encode
from collections import defaultdict
import hashlib
from pathlib import Path
import re
from urllib.parse import parse_qs, quote

import django
import falcon
import markdown
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.django_settings")
django.setup()

from app.models import Article, ArticleVote, Category, Comment, User

app = falcon.App()
app.add_static_route("/static", Path("static").absolute())
AUTH_COOKIE_NAME = "auth"
AUTH_MAX_AGE_SECONDS = 60 * 60 * 24 * 365  # 1 year


def _build_fernet() -> Fernet:
    key_bytes = settings.SECRET_KEY.encode("utf-8")
    digest = hashlib.sha256(key_bytes).digest()
    return Fernet(urlsafe_b64encode(digest))


FERNET = _build_fernet()


templates = Environment(
    loader=FileSystemLoader("templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


class NormalizeHeadingsTreeprocessor(Treeprocessor):
    def run(self, root):
        for element in root.iter():
            if element.tag in {"h1", "h2", "h4", "h5", "h6"}:
                element.tag = "h3"
        return root


class NormalizeHeadingsExtension(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(NormalizeHeadingsTreeprocessor(md), "normalize_headings_to_h3", 15)


def markdown_filter(text: str) -> Markup:
    html = markdown.markdown(
        text or "",
        extensions=["extra", "sane_lists", "nl2br", NormalizeHeadingsExtension()],
    )
    return Markup(html)


def time_ago_filter(value) -> str:
    if value is None:
        return ""

    now = timezone.now()
    delta_seconds = int((now - value).total_seconds())
    if delta_seconds <= 0:
        return "just now"

    if delta_seconds < 60:
        return "just now"

    minutes = delta_seconds // 60
    if minutes < 60:
        unit = "minute" if minutes == 1 else "minutes"
        return f"{minutes} {unit} ago"

    hours = minutes // 60
    if hours < 24:
        unit = "hour" if hours == 1 else "hours"
        return f"{hours} {unit} ago"

    days = hours // 24
    if days < 7:
        unit = "day" if days == 1 else "days"
        return f"{days} {unit} ago"

    weeks = days // 7
    if days < 30:
        unit = "week" if weeks == 1 else "weeks"
        return f"{weeks} {unit} ago"

    months = days // 30
    if days < 365:
        unit = "month" if months == 1 else "months"
        return f"{months} {unit} ago"

    years = days // 365
    unit = "year" if years == 1 else "years"
    return f"{years} {unit} ago"


templates.filters["markdown"] = markdown_filter
templates.filters["time_ago"] = time_ago_filter


def render_html(req: falcon.Request, resp: falcon.Response, template_name: str, context: dict) -> None:
    template = templates.get_template(template_name)
    resp.content_type = falcon.MEDIA_HTML
    current_user = get_current_user(req)
    view_context = {
        "current_user": current_user,
        "current_user_karma": get_user_karma(current_user),
    }
    view_context.update(context)
    resp.text = template.render(**view_context)


def encrypt_user_id(user_id: int) -> str:
    return FERNET.encrypt(str(user_id).encode("utf-8")).decode("utf-8")


def decrypt_user_id(token: str) -> int | None:
    try:
        raw = FERNET.decrypt(token.encode("utf-8"))
        return int(raw.decode("utf-8"))
    except (InvalidToken, ValueError, TypeError):
        return None


def set_auth_cookie(resp: falcon.Response, user_id: int) -> None:
    resp.set_cookie(
        AUTH_COOKIE_NAME,
        encrypt_user_id(user_id),
        max_age=AUTH_MAX_AGE_SECONDS,
        http_only=True,
        secure=False,
        same_site="Lax",
        path="/",
    )


def clear_auth_cookie(resp: falcon.Response) -> None:
    resp.unset_cookie(AUTH_COOKIE_NAME, path="/")


def get_current_user(req: falcon.Request) -> User | None:
    if hasattr(req.context, "_current_user_loaded"):
        return req.context.current_user

    token = req.cookies.get(AUTH_COOKIE_NAME)
    current_user = None
    if token:
        user_id = decrypt_user_id(token)
        if user_id is not None:
            current_user = User.objects.filter(id=user_id).first()

    req.context.current_user = current_user
    req.context._current_user_loaded = True
    return current_user


def get_user_karma(user: User | None) -> int:
    if user is None:
        return 0
    result = ArticleVote.objects.filter(article__author=user).aggregate(total=Sum("value"))
    return result.get("total") or 0


def get_form_data(req: falcon.Request) -> dict:
    try:
        media = req.get_media()
        if isinstance(media, dict):
            return media
    except Exception:
        pass

    raw = req.bounded_stream.read()
    if not raw:
        return {}

    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def get_comment_tree(article_id: int):
    comments = list(
        Comment.objects.filter(article_id=article_id)
        .select_related("author")
        .order_by("created_at")
    )

    grouped: dict[int, list[Comment]] = defaultdict(list)
    for comment in comments:
        comment.nested_children = []
        if comment.parent_id is None:
            grouped[0].append(comment)
        else:
            grouped[comment.parent_id].append(comment)

    def attach_children(node: Comment) -> None:
        node.nested_children = grouped.get(node.id, [])
        for child in node.nested_children:
            attach_children(child)

    roots = grouped.get(0, [])
    for root in roots:
        attach_children(root)

    return roots


def normalize_category_name(raw_name: str) -> str:
    normalized = (raw_name or "").strip().lower()
    if not re.fullmatch(r"[a-z]+", normalized):
        raise falcon.HTTPBadRequest(description="Category name must contain letters only (a-z).")
    return normalized


def _is_emoji_base(cp: int) -> bool:
    return (
        0x1F300 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x1F1E6 <= cp <= 0x1F1FF
    )


def validate_single_emoji(raw_emoji: str) -> str:
    emoji = (raw_emoji or "").strip()
    if not emoji:
        raise falcon.HTTPBadRequest(description="Emoji is required")

    codepoints = [ord(ch) for ch in emoji]
    regional_indicators = [cp for cp in codepoints if 0x1F1E6 <= cp <= 0x1F1FF]
    if regional_indicators:
        if len(codepoints) == 2 and len(regional_indicators) == 2:
            return emoji
        raise falcon.HTTPBadRequest(description="Emoji must be exactly one emoji character")

    emoji_bases = 0
    expect_base_after_zwj = False

    for cp in codepoints:
        if cp == 0x200D:  # zero-width joiner
            if expect_base_after_zwj:
                raise falcon.HTTPBadRequest(description="Emoji must be exactly one emoji character")
            expect_base_after_zwj = True
            continue

        if cp == 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF:  # variation selector / skin tone
            continue

        if _is_emoji_base(cp):
            if emoji_bases > 0 and not expect_base_after_zwj:
                raise falcon.HTTPBadRequest(description="Emoji must be exactly one emoji character")
            emoji_bases += 1
            expect_base_after_zwj = False
            continue

        raise falcon.HTTPBadRequest(description="Emoji must be exactly one emoji character")

    if emoji_bases == 0 or expect_base_after_zwj:
        raise falcon.HTTPBadRequest(description="Emoji must be exactly one emoji character")

    return emoji


class IndexResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        articles = list(
            Article.objects.select_related("author")
            .select_related("category")
            .annotate(comment_count=Count("comments"))
            .order_by("-comment_count", "-created_at")
        )

        render_html(
            req,
            resp,
            "index.html",
            {
                "articles": articles,
            },
        )


class SearchResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        query = (req.get_param("q") or "").strip()
        if query:
            articles = list(
                Article.objects.filter(
                    Q(title__icontains=query) | Q(content_markdown__icontains=query)
                )
                .select_related("author")
                .select_related("category")
                .annotate(comment_count=Count("comments"))
                .order_by("-created_at")
            )
        else:
            latest_article_id_per_author = (
                Article.objects.filter(author_id=OuterRef("author_id"))
                .order_by("-created_at", "-id")
                .values("id")[:1]
            )

            articles = list(
                Article.objects.filter(id=Subquery(latest_article_id_per_author))
                .select_related("author")
                .select_related("category")
                .annotate(comment_count=Count("comments"))
                .order_by("-created_at", "-id")
            )

        render_html(
            req,
            resp,
            "search.html",
            {
                "query": query,
                "articles": articles,
            },
        )


class UserDetailResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response, username: str) -> None:
        user = User.objects.filter(username=username).first()
        if user is None:
            raise falcon.HTTPNotFound(description="User not found")

        articles = list(
            Article.objects.filter(author_id=user.id)
            .select_related("author")
            .select_related("category")
            .annotate(comment_count=Count("comments"))
            .order_by("-created_at")
        )
        render_html(
            req,
            resp,
            "user_detail.html",
            {
                "profile_user": user,
                "profile_user_karma": get_user_karma(user),
                "articles": articles,
            },
        )


class CategoryDetailResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response, name: str) -> None:
        category = Category.objects.filter(name=name.lower()).first()
        if category is None:
            raise falcon.HTTPNotFound(description="Category not found")

        articles = list(
            Article.objects.filter(category_id=category.id)
            .select_related("author")
            .select_related("category")
            .annotate(comment_count=Count("comments"))
            .order_by("-created_at")
        )
        render_html(
            req,
            resp,
            "category_detail.html",
            {
                "category": category,
                "articles": articles,
            },
        )


class LoginResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        next_url = req.get_param("next") or "/"
        render_html(req, resp, "login.html", {"next_url": next_url})

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        data = get_form_data(req)
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        next_url = (data.get("next") or "/").strip()

        user = User.objects.filter(username=username).first()
        if user is None or not check_password(password, user.password_hash):
            raise falcon.HTTPBadRequest(description="Invalid username or password")

        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"

        set_auth_cookie(resp, user.id)
        raise falcon.HTTPSeeOther(location=next_url)


class LogoutResource:
    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        clear_auth_cookie(resp)
        raise falcon.HTTPSeeOther(location="/")


class UserNewResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        render_html(req, resp, "user_new.html", {"form": {}})

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        data = get_form_data(req)
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        password_confirm = data.get("password_confirm") or ""
        full_name = (data.get("full_name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        description_markdown = (data.get("description_markdown") or "").strip()

        form = {
            "username": username,
            "emoji": (data.get("emoji") or "").strip(),
            "full_name": full_name,
            "email": email,
            "description_markdown": description_markdown,
        }

        try:
            emoji = validate_single_emoji(form["emoji"])

            if not username or not password or not emoji or not full_name or not email:
                raise falcon.HTTPBadRequest(description="All user fields are required")
            if password != password_confirm:
                raise falcon.HTTPBadRequest(description="Password and confirmation must match")
            if len(password) < 8:
                raise falcon.HTTPBadRequest(description="Password must be at least 8 characters")

            if User.objects.filter(username=username).exists():
                raise falcon.HTTPBadRequest(description="Username already exists")
            if User.objects.filter(email=email).exists():
                raise falcon.HTTPBadRequest(description="Email already exists")

            user = User.objects.create(
                username=username,
                password_hash=make_password(password),
                emoji=emoji,
                full_name=full_name,
                email=email,
                description_markdown=description_markdown,
            )
            set_auth_cookie(resp, user.id)
            raise falcon.HTTPSeeOther(location="/")
        except falcon.HTTPBadRequest as exc:
            resp.status = falcon.HTTP_400
            render_html(req, resp, "user_new.html", {"error": exc.description, "form": form})


class SettingsResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        current_user = get_current_user(req)
        if current_user is None:
            raise falcon.HTTPSeeOther(location="/login?next=/settings")

        form = {
            "username": current_user.username,
            "emoji": current_user.emoji,
            "full_name": current_user.full_name,
            "description_markdown": current_user.description_markdown or "",
        }
        render_html(req, resp, "settings.html", {"form": form})

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        current_user = get_current_user(req)
        if current_user is None:
            raise falcon.HTTPSeeOther(location="/login?next=/settings")

        data = get_form_data(req)
        username = (data.get("username") or "").strip()
        emoji_raw = (data.get("emoji") or "").strip()
        full_name = (data.get("full_name") or "").strip()
        description_markdown = (data.get("description_markdown") or "").strip()
        password = data.get("password") or ""
        password_confirm = data.get("password_confirm") or ""

        form = {
            "username": username,
            "emoji": emoji_raw,
            "full_name": full_name,
            "description_markdown": description_markdown,
        }

        try:
            emoji = validate_single_emoji(emoji_raw)
            if not username or not full_name:
                raise falcon.HTTPBadRequest(description="Username, full name, and emoji are required")

            username_taken = (
                User.objects.filter(username=username)
                .exclude(id=current_user.id)
                .exists()
            )
            if username_taken:
                raise falcon.HTTPBadRequest(description="Username already exists")

            if password or password_confirm:
                if password != password_confirm:
                    raise falcon.HTTPBadRequest(description="Password and confirmation must match")
                if len(password) < 8:
                    raise falcon.HTTPBadRequest(description="Password must be at least 8 characters")

            update_fields = ["username", "emoji", "full_name", "description_markdown"]
            current_user.username = username
            current_user.emoji = emoji
            current_user.full_name = full_name
            current_user.description_markdown = description_markdown
            if password:
                current_user.password_hash = make_password(password)
                update_fields.append("password_hash")
            current_user.save(update_fields=update_fields)

            raise falcon.HTTPSeeOther(location=f"/users/{current_user.username}")
        except falcon.HTTPBadRequest as exc:
            resp.status = falcon.HTTP_400
            render_html(req, resp, "settings.html", {"error": exc.description, "form": form})


class ArticleNewResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        current_user = get_current_user(req)
        if current_user is None:
            raise falcon.HTTPSeeOther(location="/login?next=/articles/new")

        render_html(req, resp, "article_new.html", {"form": {}})

    def on_post(self, req: falcon.Request, resp: falcon.Response) -> None:
        current_user = get_current_user(req)
        if current_user is None:
            raise falcon.HTTPSeeOther(location="/login?next=/articles/new")

        data = get_form_data(req)
        title = (data.get("title") or "").strip()
        content_markdown = (data.get("content_markdown") or "").strip()
        category_name = (data.get("category_name") or "").strip()

        form = {
            "title": title,
            "category_name": category_name,
            "content_markdown": content_markdown,
        }

        try:
            if not title or not content_markdown:
                raise falcon.HTTPBadRequest(description="Title and content are required")

            if not category_name:
                raise falcon.HTTPBadRequest(description="Category is required")

            category, _ = Category.objects.get_or_create(name=normalize_category_name(category_name))

            article = Article.objects.create(
                author=current_user,
                category=category,
                title=title,
                content_markdown=content_markdown,
            )
            raise falcon.HTTPSeeOther(location=f"/articles/{article.id}")
        except falcon.HTTPBadRequest as exc:
            resp.status = falcon.HTTP_400
            render_html(req, resp, "article_new.html", {"error": exc.description, "form": form})


class ArticleDetailResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response, article_id: int) -> None:
        article = (
            Article.objects.select_related("author")
            .select_related("category")
            .annotate(comment_count=Count("comments"))
            .filter(id=article_id)
            .first()
        )
        if article is None:
            raise falcon.HTTPNotFound(description="Article not found")

        current_user = get_current_user(req)
        comments = get_comment_tree(article_id)
        vote = (
            ArticleVote.objects.filter(article_id=article_id, voter=current_user).first()
            if current_user is not None
            else None
        )

        render_html(
            req,
            resp,
            "article_detail.html",
            {
                "article": article,
                "comments": comments,
                "user_vote": vote.value if vote else 0,
            },
        )


class ArticleEditResource:
    def on_get(self, req: falcon.Request, resp: falcon.Response, article_id: int) -> None:
        current_user = get_current_user(req)
        if current_user is None:
            raise falcon.HTTPSeeOther(location=f"/login?next={quote(f'/articles/{article_id}/edit', safe='/?=&')}")

        article = (
            Article.objects.select_related("author")
            .select_related("category")
            .filter(id=article_id)
            .first()
        )
        if article is None:
            raise falcon.HTTPNotFound(description="Article not found")
        if article.author_id != current_user.id:
            raise falcon.HTTPForbidden(description="Only the article author can edit this article")

        render_html(
            req,
            resp,
            "article_edit.html",
            {
                "article": article,
            },
        )

    def on_post(self, req: falcon.Request, resp: falcon.Response, article_id: int) -> None:
        current_user = get_current_user(req)
        if current_user is None:
            raise falcon.HTTPSeeOther(location=f"/login?next={quote(f'/articles/{article_id}/edit', safe='/?=&')}")

        article = Article.objects.filter(id=article_id).first()
        if article is None:
            raise falcon.HTTPNotFound(description="Article not found")
        if article.author_id != current_user.id:
            raise falcon.HTTPForbidden(description="Only the article author can edit this article")

        data = get_form_data(req)
        title = (data.get("title") or "").strip()
        content_markdown = (data.get("content_markdown") or "").strip()
        category_name = (data.get("category_name") or "").strip()

        if not title or not content_markdown:
            raise falcon.HTTPBadRequest(description="Title and content are required")

        if not category_name:
            raise falcon.HTTPBadRequest(description="Category is required")

        category, _ = Category.objects.get_or_create(name=normalize_category_name(category_name))

        article.title = title
        article.content_markdown = content_markdown
        article.category = category
        article.save(update_fields=["title", "content_markdown", "category", "updated_at"])

        raise falcon.HTTPSeeOther(location=f"/articles/{article_id}")


class ArticleVoteResource:
    def on_post(self, req: falcon.Request, resp: falcon.Response, article_id: int) -> None:
        current_user = get_current_user(req)
        if current_user is None:
            raise falcon.HTTPSeeOther(location=f"/login?next={quote(f'/articles/{article_id}', safe='/?=&')}")

        data = get_form_data(req)
        vote_value = data.get("vote")
        if vote_value not in {"like", "dislike"}:
            raise falcon.HTTPBadRequest(description="Invalid vote type")

        article = Article.objects.filter(id=article_id).first()
        if article is None:
            raise falcon.HTTPNotFound(description="Article not found")

        desired_value = 1 if vote_value == "like" else -1
        existing_vote = ArticleVote.objects.filter(article_id=article_id, voter=current_user).first()

        if existing_vote is None:
            ArticleVote.objects.create(article=article, voter=current_user, value=desired_value)
            if desired_value == 1:
                article.likes_count += 1
            else:
                article.dislikes_count += 1
        elif existing_vote.value == desired_value:
            existing_vote.delete()
            if desired_value == 1 and article.likes_count > 0:
                article.likes_count -= 1
            if desired_value == -1 and article.dislikes_count > 0:
                article.dislikes_count -= 1
        else:
            if existing_vote.value == 1 and article.likes_count > 0:
                article.likes_count -= 1
            if existing_vote.value == -1 and article.dislikes_count > 0:
                article.dislikes_count -= 1
            existing_vote.value = desired_value
            existing_vote.save()
            if desired_value == 1:
                article.likes_count += 1
            else:
                article.dislikes_count += 1

        article.save()
        raise falcon.HTTPSeeOther(location=f"/articles/{article_id}")


class ArticleCommentResource:
    def on_post(self, req: falcon.Request, resp: falcon.Response, article_id: int) -> None:
        current_user = get_current_user(req)
        if current_user is None:
            raise falcon.HTTPSeeOther(location=f"/login?next={quote(f'/articles/{article_id}', safe='/?=&')}")

        data = get_form_data(req)
        parent_id = data.get("parent_id")
        content_markdown = (data.get("content_markdown") or "").strip()

        if not content_markdown:
            raise falcon.HTTPBadRequest(description="Content is required")

        article = Article.objects.filter(id=article_id).first()
        if article is None:
            raise falcon.HTTPNotFound(description="Article not found")

        parent_comment = None
        if parent_id:
            parent_comment = Comment.objects.filter(id=parent_id, article_id=article_id).first()
            if parent_comment is None:
                raise falcon.HTTPBadRequest(description="Invalid parent comment")

        Comment.objects.create(
            article=article,
            author=current_user,
            parent=parent_comment,
            content_markdown=content_markdown,
        )

        raise falcon.HTTPSeeOther(location=f"/articles/{article_id}#comments")


app.add_route("/", IndexResource())
app.add_route("/search", SearchResource())
app.add_route("/settings", SettingsResource())
app.add_route("/users/{username}", UserDetailResource())
app.add_route("/categories/{name}", CategoryDetailResource())
app.add_route("/login", LoginResource())
app.add_route("/logout", LogoutResource())
app.add_route("/users/new", UserNewResource())
app.add_route("/articles/new", ArticleNewResource())
app.add_route("/articles/{article_id:int}", ArticleDetailResource())
app.add_route("/articles/{article_id:int}/edit", ArticleEditResource())
app.add_route("/articles/{article_id:int}/vote", ArticleVoteResource())
app.add_route("/articles/{article_id:int}/comments", ArticleCommentResource())
