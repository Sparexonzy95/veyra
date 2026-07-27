from config.settings import *  # noqa: F403


# Tests must never depend on permission to create a database beside the live
# PostgreSQL database. This isolated file is created and destroyed by Django.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "_django_test.sqlite3",  # noqa: F405
        "TEST": {
            "NAME": BASE_DIR / "_django_test.sqlite3",  # noqa: F405
        },
    },
}
