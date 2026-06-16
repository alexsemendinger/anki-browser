from backend import rendering


def test_basic_field_substitution():
    out = rendering.render({"Front": "Q", "Back": "A"}, "{{Front}}", "{{FrontSide}}<hr>{{Back}}")
    assert out["question"] == "Q"
    assert "Q" in out["answer"] and "A" in out["answer"]


def test_conditional_sections():
    qfmt = "{{Front}}{{#Extra}} [{{Extra}}]{{/Extra}}"
    assert rendering.fill_template(qfmt, {"Front": "x", "Extra": "y"}) == "x [y]"
    assert rendering.fill_template(qfmt, {"Front": "x", "Extra": ""}) == "x"


def test_negated_section():
    qfmt = "{{^Extra}}none{{/Extra}}"
    assert rendering.fill_template(qfmt, {"Extra": ""}) == "none"
    assert rendering.fill_template(qfmt, {"Extra": "z"}) == ""


def test_cloze_question_hides_active_shows_others():
    fields = {"Text": "{{c1::France}} / {{c2::Paris}}"}
    out = rendering.render(fields, "{{cloze:Text}}", "{{cloze:Text}}{{Back Extra}}")
    assert "[...]" in out["question"]
    assert "Paris" in out["question"]  # other ordinal shown
    assert "France" not in out["question"]


def test_cloze_answer_reveals():
    fields = {"Text": "{{c1::France}}"}
    out = rendering.render(fields, "{{cloze:Text}}", "{{cloze:Text}}")
    assert "France" in out["answer"]
    assert "cloze" in out["answer"]


def test_cloze_hint():
    out = rendering.fill_template("{{cloze:T}}", {"T": "{{c1::ans::myhint}}"}, ordinal=1, reveal=False)
    assert "[myhint]" in out


def test_latex_conversion():
    assert rendering.convert_latex("[$]x^2[$]") == r"\(x^2\)"
    assert rendering.convert_latex("[$$]y[$$]") == r"\[y\]"
    assert rendering.convert_latex("[latex]z[/latex]") == r"\[z\]"


def test_basic_templates_fallback():
    q, a = rendering.basic_templates(["Front", "Back", "Extra"])
    assert q == "{{Front}}"
    assert "{{FrontSide}}" in a and "{{Back}}" in a and "{{Extra}}" in a
