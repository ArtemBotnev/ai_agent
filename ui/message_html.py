import html

from ui import colors


AGENT_AUTHOR = "Агент"
USER_AUTHOR = "Вы"
ERROR_AUTHOR = "Ошибка"


def render_message_html(author: str, text: str, meta: str = "") -> str:
    author_html = html.escape(author)
    text_html = html.escape(text).replace("\n", "<br>")
    author_color = get_author_color(author)
    text_color = colors.ERROR_TEXT_COLOR if author == ERROR_AUTHOR else colors.TEXT_PRIMARY
    meta_html = render_meta_html(meta)

    return f"""
    <div style="margin:12px 0;">
      <div style="color:{author_color};font-size:12px;font-weight:700;">{author_html}</div>
      <div style="color:{text_color};font-size:15px;line-height:1.45;margin-top:4px;">{text_html}</div>
      {meta_html}
    </div>
    """


def get_author_color(author: str) -> str:
    if author == USER_AUTHOR:
        return colors.USER_AUTHOR_COLOR

    if author == ERROR_AUTHOR:
        return colors.ERROR_AUTHOR_COLOR

    return colors.AGENT_AUTHOR_COLOR


def render_meta_html(meta: str) -> str:
    if not meta:
        return ""

    meta_html = html.escape(meta)
    return f'<div style="color:{colors.TEXT_SUBTLE};font-size:12px;margin-top:6px;">{meta_html}</div>'
