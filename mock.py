import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.django_settings")
django.setup()

from django.contrib.auth.hashers import make_password
from django.utils import timezone

from app.models import Article, ArticleVote, Category, Comment, User

# Reset data for a clean mock dataset
Comment.objects.all().delete()
ArticleVote.objects.all().delete()
Article.objects.all().delete()
Category.objects.all().delete()
User.objects.all().delete()

PASSWORD = "password123"

users_data = [
    ("alice", "👩‍💻", "Alice Johnson", "alice@example.com", "Software engineer who loves **Python** and open source.\n\nWrites about backend systems."),
    ("bob", "🎨", "Bob Smith", "bob@example.com", "Designer and illustrator. Passionate about *typography* and color."),
    ("carol", "🔬", "Carol Lee", "carol@example.com", "Research scientist exploring **AI** and data visualization."),
    ("dave", "✈️", "Dave Brown", "dave@example.com", "Travel blogger visiting 40+ countries. Always chasing sunsets."),
    ("eve", "🍳", "Eve Davis", "eve@example.com", "Home cook and food writer. Recipes with a story."),
    ("frank", "📚", "Frank Miller", "frank@example.com", "Bookworm and literary critic. Reads 50 books a year."),
]

users = {}
for username, emoji, full_name, email, bio in users_data:
    users[username] = User.objects.create(
        username=username,
        password_hash=make_password(PASSWORD),
        emoji=emoji,
        full_name=full_name,
        email=email,
        description_markdown=bio,
    )

category_names = ["technology", "science", "travel", "food", "lifestyle", "programming", "books", "design"]
categories = {}
for name in category_names:
    categories[name] = Category.objects.create(name=name)

articles_data = [
    ("alice", "technology", "Why Django ORM Still Rocks in 2026",
     "# Why Django ORM Still Rocks\n\nDjango's ORM has been around for years, yet it remains one of the most productive ways to interact with relational databases.\n\n## Migrations\n\nAutomatic schema migrations save countless hours.\n\n## QuerySets\n\nLazy evaluation and chainable filters make complex queries readable."),
    ("alice", "programming", "Building a Falcon API from Scratch",
     "# Building a Falcon API\n\nFalcon is a minimalist WSGI framework. It stays out of your way.\n\n- Fast routing\n- Clean resource classes\n- Great for microservices"),
    ("bob", "design", "The Art of Whitespace",
     "# The Art of Whitespace\n\nWhitespace is not empty space; it's a design element.\n\n> Good design is as little design as possible.\n\nUse generous margins and let content breathe."),
    ("carol", "science", "Machine Learning in Everyday Life",
     "# Machine Learning in Everyday Life\n\nFrom recommendation engines to spam filters, ML is everywhere.\n\n## Examples\n\n- Email spam detection\n- Photo tagging\n- Voice assistants"),
    ("carol", "science", "Visualizing Climate Data",
     "# Visualizing Climate Data\n\nCharts can make complex climate trends understandable.\n\nUse color scales carefully and label axes clearly."),
    ("dave", "travel", "A Week in Kyoto",
     "# A Week in Kyoto\n\nCherry blossoms, temples, and ramen.\n\n## Highlights\n\n- Fushimi Inari shrine\n- Arashiyama bamboo grove\n- Nishiki market"),
    ("dave", "travel", "Packing Light for Long Trips",
     "# Packing Light\n\nOne carry-on is enough if you plan.\n\n**Tips:**\n\n1. Choose versatile clothing\n2. Use packing cubes\n3. Wear your bulkiest items"),
    ("eve", "food", "The Perfect Sourdough Loaf",
     "# The Perfect Sourdough\n\nPatience is the secret ingredient.\n\n## Steps\n\n- Feed your starter\n- Autolyse\n- Stretch and fold\n- Bake with steam"),
    ("eve", "food", "Five Quick Weeknight Dinners",
     "# Five Quick Weeknight Dinners\n\nDinner in 30 minutes or less.\n\n1. Pasta aglio e olio\n2. Stir-fry noodles\n3. Tacos\n4. Omelette\n5. Grain bowl"),
    ("frank", "books", "Top 10 Novels of the Decade",
     "# Top 10 Novels\n\nA personal list of favorites.\n\n- *The Overstory*\n- *Klara and the Sun*\n- *Piranesi*"),
    ("frank", "lifestyle", "Building a Reading Habit",
     "# Building a Reading Habit\n\nRead 20 pages a day. That's 30+ books a year.\n\nTrack progress and celebrate milestones."),
    ("alice", "technology", "PostgreSQL Full-Text Search Tips",
     "# PostgreSQL Full-Text Search\n\nUse `to_tsvector` and `to_tsquery` for powerful search.\n\nCombine with GIN indexes for speed."),
    ("bob", "design", "Color Theory Basics",
     "# Color Theory Basics\n\nPrimary, secondary, and tertiary colors.\n\nComplementary pairs create contrast; analogous schemes create harmony."),
    ("carol", "programming", "Python Type Hints in Practice",
     "# Python Type Hints\n\nType hints improve readability and catch bugs early.\n\nUse `mypy` in CI."),
    ("dave", "lifestyle", "Remote Work from Anywhere",
     "# Remote Work from Anywhere\n\nCoworking spaces, cafes, and libraries.\n\nAlways have a backup internet plan."),
]

articles = []
for author_name, cat_name, title, content in articles_data:
    art = Article.objects.create(
        author=users[author_name],
        category=categories[cat_name],
        title=title,
        content_markdown=content,
    )
    articles.append(art)

# Votes: each user votes on a subset
import random
random.seed(42)
for art in articles:
    voters = random.sample(list(users.values()), k=random.randint(2, 5))
    likes = 0
    dislikes = 0
    for voter in voters:
        if voter.id == art.author.id:
            continue
        value = 1 if random.random() > 0.3 else -1
        ArticleVote.objects.create(article=art, voter=voter, value=value)
        if value == 1:
            likes += 1
        else:
            dislikes += 1
    art.likes_count = likes
    art.dislikes_count = dislikes
    art.save(update_fields=["likes_count", "dislikes_count"])

# Comments (including nested)
comment_texts = [
    "Great post, thanks for sharing!",
    "I disagree with some points but overall interesting.",
    "Could you elaborate on the second section?",
    "This changed my perspective.",
    "Bookmarked for later reading.",
    "Nice examples, very clear.",
]

for art in articles:
    # top-level comments
    n = random.randint(1, 4)
    top_comments = []
    for _ in range(n):
        author = random.choice(list(users.values()))
        c = Comment.objects.create(
            article=art,
            author=author,
            content_markdown=random.choice(comment_texts),
        )
        top_comments.append(c)
    # nested replies
    for tc in top_comments:
        if random.random() > 0.5:
            reply_author = random.choice(list(users.values()))
            Comment.objects.create(
                article=art,
                author=reply_author,
                parent=tc,
                content_markdown="Thanks! I'll look into that.",
            )
    # deeper nesting
    for tc in top_comments:
        children = list(tc.children.all())
        for child in children:
            if random.random() > 0.7:
                Comment.objects.create(
                    article=art,
                    author=random.choice(list(users.values())),
                    parent=child,
                    content_markdown="Agreed, good point.",
                )

print("Seeded:")
print("  users:", User.objects.count())
print("  categories:", Category.objects.count())
print("  articles:", Article.objects.count())
print("  votes:", ArticleVote.objects.count())
print("  comments:", Comment.objects.count())
