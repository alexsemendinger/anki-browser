"""Render a note to question/answer HTML the way Anki would.

A pragmatic subset of Anki templating: field substitution, {{FrontSide}},
{{#Field}}/{{^Field}} conditionals, and cloze. LaTeX delimiters are normalized
to MathJax form so the browser can typeset them. The goal is that a card looks
like the real thing for the common Basic and Cloze note types, not a byte-exact
reimplementation of Anki's renderer.
"""
import re

CLOZE_RE = re.compile(r"\{\{c(\d+)::(.*?)(?:::(.*?))?\}\}", re.S)
CLOZE_CONTENT_RE = re.compile(r"\{\{c\d+::")
SECTION_RE = re.compile(r"\{\{([#^])([^}]+)\}\}(.*?)\{\{/\2\}\}", re.S)
FIELD_RE = re.compile(r"\{\{([^#^/][^}]*)\}\}")


def render_cloze(text, ordinal, reveal):
    def repl(match):
        num = int(match.group(1))
        answer = match.group(2)
        hint = match.group(3)
        if num == ordinal:
            if reveal:
                return '<span class="cloze">%s</span>' % answer
            return "[%s]" % (hint if hint else "...")
        return answer

    return CLOZE_RE.sub(repl, text)


def _strip_sections(template, fields):
    prev = None
    out = template
    while prev != out:
        prev = out

        def repl(match):
            negate = match.group(1) == "^"
            name = match.group(2).strip()
            body = match.group(3)
            present = bool((fields.get(name) or "").strip())
            show = (not present) if negate else present
            return body if show else ""

        out = SECTION_RE.sub(repl, out)
    return out


def fill_template(template, fields, ordinal=1, reveal=False, front_side=None):
    out = template
    if front_side is not None:
        out = out.replace("{{FrontSide}}", front_side)
    out = _strip_sections(out, fields)

    def cloze_field(match):
        name = match.group(1).strip()
        return render_cloze(fields.get(name, ""), ordinal, reveal)

    out = re.sub(r"\{\{cloze:([^}]+)\}\}", cloze_field, out)

    def field_repl(match):
        inner = match.group(1).strip()
        name = inner.split(":")[-1].strip()
        return fields.get(name, "")

    out = FIELD_RE.sub(field_repl, out)
    return convert_latex(out)


def convert_latex(text):
    text = re.sub(r"\[\$\$\](.*?)\[\$\$\]", r"\\[\1\\]", text, flags=re.S)
    text = re.sub(r"\[\$\](.*?)\[\$\]", r"\\(\1\\)", text, flags=re.S)
    text = re.sub(r"\[latex\](.*?)\[/latex\]", r"\\[\1\\]", text, flags=re.S)
    return text


def is_cloze(fields, qfmt):
    return "{{cloze:" in (qfmt or "")


def render(fields, qfmt, afmt, ordinal=1):
    """Return {'question', 'answer'} HTML fragments (no CSS, no MathJax)."""
    cloze = is_cloze(fields, qfmt)
    question = fill_template(qfmt, fields, ordinal=ordinal, reveal=False)
    answer = fill_template(
        afmt, fields, ordinal=ordinal, reveal=cloze, front_side=question
    )
    return {"question": question, "answer": answer}


# --- fallbacks for cards with no template available (Anki closed) --------
def basic_templates(field_order):
    """Front = first field, Back = FrontSide + rest. Good enough to look at a
    provisional card when Anki is not running to supply the real template."""
    first = field_order[0] if field_order else "Front"
    rest = field_order[1:] if len(field_order) > 1 else []
    qfmt = "{{%s}}" % first
    afmt = "{{FrontSide}}<hr id=answer>" + "".join("{{%s}}" % f for f in rest)
    return qfmt, afmt


def cloze_field_name(fields):
    """Name of the first field holding cloze deletions, or None."""
    for name, value in fields.items():
        if CLOZE_CONTENT_RE.search(value or ""):
            return name
    return None


def cloze_ordinals(fields):
    """Sorted distinct cloze ordinals across all fields (a cloze note with c1
    and c2 -> [1, 2]). Each ordinal is a separate card Anki will generate.
    Always returns at least [1]."""
    nums = set()
    for value in fields.values():
        for m in re.finditer(r"\{\{c(\d+)::", value or ""):
            nums.add(int(m.group(1)))
    return sorted(nums) or [1]


def strip_tags(text):
    """Crude HTML tag strip, used only to test whether a rendered template
    front is non-empty (i.e. whether Anki would generate that card)."""
    return re.sub(r"<[^>]*>", "", text or "")


def cloze_templates(field_order, cloze_name):
    """Fallback templates for a cloze note when Anki is closed."""
    rest = [f for f in field_order if f != cloze_name]
    qfmt = "{{cloze:%s}}" % cloze_name
    afmt = "{{cloze:%s}}<hr id=answer>" % cloze_name + "".join("{{%s}}" % f for f in rest)
    return qfmt, afmt


DEFAULT_CSS = (
    ".card{font-family:arial;font-size:20px;text-align:center;"
    "color:#111;background:#fff;}"
    ".cloze{font-weight:bold;color:#0064c8;}"
    "#answer{margin:1em 0;}"
)
