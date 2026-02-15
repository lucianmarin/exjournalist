from django.db import models
from django.core.exceptions import ValidationError
import re


class User(models.Model):
    username = models.CharField(max_length=50, unique=True)
    password_hash = models.CharField(max_length=255)
    emoji = models.CharField(max_length=10)
    full_name = models.CharField(max_length=120)
    email = models.EmailField(unique=True)
    description_markdown = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users"
        ordering = ["username"]

    def __str__(self) -> str:
        return self.username


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "categories"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        normalized = (self.name or "").strip().lower()
        if not re.fullmatch(r"[a-z]+", normalized):
            raise ValidationError("Category name must contain letters only (a-z).")
        self.name = normalized
        return super().save(*args, **kwargs)


class Article(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="articles")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="articles")
    title = models.CharField(max_length=255)
    content_markdown = models.TextField()
    likes_count = models.IntegerField(default=0)
    dislikes_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "articles"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class ArticleVote(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="votes")
    voter = models.ForeignKey(User, on_delete=models.CASCADE, related_name="article_votes")
    value = models.SmallIntegerField()  # 1 = like, -1 = dislike
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "article_votes"
        unique_together = (("article", "voter"),)


class Comment(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey("self", on_delete=models.CASCADE, related_name="children", null=True, blank=True)
    content_markdown = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "comments"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Comment #{self.id}"
