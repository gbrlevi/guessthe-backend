from __future__ import annotations

from scripts.seed_common import build_question, replace_category

CDN = "https://cdn.jsdelivr.net/gh/devicons/devicon@latest/icons"

ICONS: list[tuple[str, str, str, str | None]] = [
    ("JavaScript",  "javascript",  "original",  None),
    ("Python",      "python",      "original",  None),
    ("React",       "react",       "original",  None),
    ("TypeScript",  "typescript",  "original",  None),
    ("HTML5",       "html5",       "original",  None),
    ("CSS3",        "css3",        "original",  None),
    ("Node.js",     "nodejs",      "original",  "plain"),
    ("Git",         "git",         "original",  None),
    ("Docker",      "docker",      "original",  "plain"),
    ("Linux",       "linux",       "original",  None),
    ("Java",        "java",        "original",  None),
    ("C++",         "cplusplus",   "original",  None),
    ("C#",          "csharp",      "original",  None),
    ("PHP",         "php",         "original",  None),
    ("Ruby",        "ruby",        "original",  None),
    ("Swift",       "swift",       "original",  None),
    ("Kotlin",      "kotlin",      "original",  None),
    ("Go",          "go",          "original",  "plain"),
    ("Rust",        "rust",        "original",  "plain"),
    ("Vue.js",      "vuejs",       "original",  None),
    ("Angular",     "angular",     "original",  None),
    ("MongoDB",     "mongodb",     "original",  None),
    ("MySQL",       "mysql",       "original",  None),
    ("PostgreSQL",  "postgresql",  "original",  None),
    ("Redis",       "redis",       "original",  None),
    ("Figma",       "figma",       "original",  None),
    ("Flutter",     "flutter",     "original",  None),
    ("Dart",        "dart",        "original",  None),
    ("Bash",        "bash",        "original",  None),
    ("Vim",         "vim",         "original",  None),
    ("Django",      "django",      "plain",     None),
    ("Laravel",     "laravel",     "original",  None),
    ("Spring",      "spring",      "original",  None),
    ("AWS",         "amazonwebservices", "original", "plain"),
    ("Azure",       "azure",       "original",  None),
]


def icon_url(slug: str, variant: str) -> str:
    return f"{CDN}/{slug}/{slug}-{variant}.svg"


def main() -> None:
    rows: list[dict] = []

    for display_name, slug, variant, _fallback in ICONS:
        url = icon_url(slug, variant)
        aliases = [display_name]
        if "." in display_name or "-" in display_name:
            aliases.append(display_name.replace(".", "").replace("-", " "))
        if slug != display_name.lower():
            aliases.append(slug)

        rows.append(
            build_question(
                category="tech_logos",
                media_type="image",
                answer=display_name,
                media_url=url,
                ext_id=slug,
                popularity=80,
                aliases=aliases,
            )
        )
        print(f"  {display_name}")

    replace_category("tech_logos", rows)


if __name__ == "__main__":
    main()
