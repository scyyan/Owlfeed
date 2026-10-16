from owlfeed.text import clean_title, html_to_text, make_summary, strip_boilerplate, summary_text, truncate


def test_html_to_text_strips_tags_and_decodes_entities():
    assert html_to_text("<p>Hello&nbsp;<b>world</b> &amp; friends</p>") == "Hello world & friends"


def test_html_to_text_separates_blocks_and_skips_noise():
    html = "<h2>Heading</h2><p>Para one.</p><script>bad()</script><figure><figcaption>Fig 1</figcaption></figure><p>Para two.</p>"
    assert html_to_text(html) == "Heading Para one. Para two."


def test_html_to_text_handles_double_escaped_entities():
    assert html_to_text("Hackers&amp;#8217; tools") == "Hackers’ tools"


def test_html_to_text_keeps_plain_text_with_angle_brackets():
    assert html_to_text("a < b and c > d") == "a < b and c > d"


def test_html_to_text_ignores_non_strings():
    assert html_to_text(None) == ""
    assert html_to_text(42) == ""


def test_clean_title_collapses_markup():
    assert clean_title("<b>Bold</b>\n &amp;  brave") == "Bold & brave"


def test_strip_boilerplate_removes_wordpress_footer():
    text = "Real summary sentence here. The post Some Title appeared first on Example Blog."
    assert strip_boilerplate(text) == "Real summary sentence here."


def test_strip_boilerplate_removes_continue_reading_and_brackets():
    assert strip_boilerplate("Talks resume next week. Continue reading...") == "Talks resume next week."
    assert strip_boilerplate("Teaser text [...]") == "Teaser text…"
    assert strip_boilerplate("Teaser text […]") == "Teaser text…"


def test_strip_boilerplate_drops_repeated_title():
    title = "Big breach at ExampleCorp"
    text = "Big breach at ExampleCorp: attackers stole customer records over several weeks."
    assert strip_boilerplate(text, title) == "attackers stole customer records over several weeks."
    assert strip_boilerplate(title, title) == ""


def test_truncate_prefers_sentence_end():
    text = "First sentence is here and it is long enough. Second sentence is a bit longer than the first one."
    assert truncate(text, 60) == "First sentence is here and it is long enough."


def test_truncate_ignores_sentence_ends_in_the_first_half():
    text = "Short one. Then a much longer sentence that keeps going well past the limit we set here."
    result = truncate(text, 60)
    assert result.startswith("Short one. Then a much longer") and result.endswith("…")


def test_strip_boilerplate_only_drops_whole_title_phrase():
    text = "The description is long enough to be useful as a summary on its own."
    assert strip_boilerplate(text, "T") == text


def test_truncate_falls_back_to_word_boundary():
    text = "word " * 40
    result = truncate(text.strip(), 50)
    assert result.endswith("…")
    assert len(result) <= 51
    assert not result[:-1].endswith(" ")


def test_truncate_leaves_short_text_alone():
    assert truncate("Short.", 50) == "Short."


def test_make_summary_prefers_description_then_content():
    entry = {"summary": "Teaser […]", "content": [{"value": "<p>A full paragraph that explains the story in enough detail.</p>"}]}
    assert make_summary(entry, "auto", "Title", 320) == "A full paragraph that explains the story in enough detail."


def test_make_summary_respects_mode():
    entry = {
        "summary": "The description is long enough to be useful as a summary on its own.",
        "content": [{"value": "Content text that is also long enough to be used as a summary."}],
    }
    assert make_summary(entry, "description", "T", 320).startswith("The description")
    assert make_summary(entry, "content", "T", 320).startswith("Content text")


def test_summary_drops_newsletter_promos():
    html = (
        "<p>Sign up here to receive Bellingcat’s biggest investigations by email as soon as they are published.</p>"
        "<p>Satellite imagery obtained by Bellingcat lays bare the extent of tree-felling at a golf course.</p>"
    )
    assert summary_text(html) == "Satellite imagery obtained by Bellingcat lays bare the extent of tree-felling at a golf course."


def test_summary_joins_paragraphs_as_sentences():
    html = (
        "<p>Attack was the first on the palace in the latest fighting between the Houthis and Saudi Arabia</p>"
        "<ul><li>Sign up for the Breaking News US email</li></ul>"
        "<p>Missiles struck the presidential palace complex on Thursday.</p>"
    )
    assert summary_text(html) == (
        "Attack was the first on the palace in the latest fighting between the Houthis and Saudi Arabia. "
        "Missiles struck the presidential palace complex on Thursday."
    )


def test_summary_drops_headings_and_marketing():
    html = (
        "<h2>Key Takeaways</h2><h3>The DFIR Report Offerings</h3>"
        "<p>Check out our Products here and our Services here.</p><p>Get in Touch</p>"
        "<p>Contact us today for pricing or a demo!</p>"
        "<ul><li>Initial access came through a malicious search ad that delivered a trojanized installer.</li></ul>"
    )
    assert summary_text(html) == "Initial access came through a malicious search ad that delivered a trojanized installer."


def test_summary_handles_double_escaped_html_and_category_footers():
    escaped = (
        "&lt;p&gt;The activity is linked to a broader campaign that used a different delivery mechanism&lt;/p&gt; "
        "Categories: Threat Research Tags: clickfix, loader"
    )
    assert summary_text(escaped) == "The activity is linked to a broader campaign that used a different delivery mechanism"


def test_summary_drops_advisory_and_license_boilerplate():
    cisa = "<p><a href='x'>View CSAF</a></p><h2>Summary</h2><p>Successful exploitation could allow file reads.</p>"
    assert summary_text(cisa) == "Successful exploitation could allow file reads."
    sans = "(c) SANS Internet Storm Center. https://isc.sans.edu Creative Commons Attribution-Noncommercial 3.0 United States License."
    assert summary_text(sans) == ""


def test_summary_drops_bylines_and_inline_marketing():
    gti = "<p>Written by: Jane Doe, John Roe</p><p>On October 15, a vendor disclosed an actively exploited flaw.</p>"
    assert summary_text(gti) == "On October 15, a vendor disclosed an actively exploited flaw."
    dfir = (
        "Key Takeaways The DFIR Report Offerings Check out our Products here and our Services here. Want a demo? "
        "Get in Touch Contact us today for pricing or a demo! The intrusion began with a malicious search ad."
    )
    assert summary_text(dfir) == "The intrusion began with a malicious search ad."
    sandwiched = (
        "Key Takeaways The DFIR Report Offerings Check out our Products here. Contact us today for pricing "
        "or a demo! Case Summary In March 2026, our team identified an SEO poisoning campaign."
    )
    assert summary_text(sandwiched) == "In March 2026, our team identified an SEO poisoning campaign."


def test_clean_title_drops_sans_date_suffix():
    assert clean_title("Orphaned VBA Projects Inside DWG Files, (Wed, Oct 14th)") == "Orphaned VBA Projects Inside DWG Files"


def test_summary_removes_ellipsis_after_complete_sentence():
    assert summary_text("Threat actors are exploiting a critical flaw in Collabora Online.…") == (
        "Threat actors are exploiting a critical flaw in Collabora Online."
    )


def test_make_summary_returns_short_text_when_nothing_better():
    assert make_summary({"summary": "Short teaser."}, "auto", "Title", 320) == "Short teaser."
    assert make_summary({}, "auto", "Title", 320) == ""
