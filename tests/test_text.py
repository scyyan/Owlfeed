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


def test_escaped_tag_names_in_text_are_kept():
    assert clean_title("How &lt;script&gt; tags hide malware in ads") == "How <script> tags hide malware in ads"
    assert summary_text("<p>Attackers inject &lt;iframe&gt; elements into checkout pages.</p>") == (
        "Attackers inject <iframe> elements into checkout pages."
    )


def test_call_to_action_patterns_do_not_eat_ordinary_words():
    for text in (
        "A new variant of the botnet worm can spread more quickly across networks.",
        "Analysts who read more than one report agreed on the attribution.",
        "Investigators continue reading through the leaked chat logs.",
    ):
        assert summary_text(text) == text


def test_junk_filters_keep_real_lead_paragraphs():
    lead = "Copyright lawsuits against AI companies are piling up as publishers seek damages."
    assert summary_text(f"<p>{lead}</p>") == lead
    assert summary_text("<p>Subscribers to the service were notified of the breach on Friday.</p>").startswith("Subscribers")


def test_truncate_does_not_cut_at_abbreviations():
    text = "Officials in the U.S. and allied governments said the campaign targeted defense contractors across several regions for months."
    result = truncate(text, 60)
    assert result.endswith("…") and "U.S." in result


def test_trailing_call_to_action_mid_sentence_is_removed():
    assert summary_text("Attackers backdoored dozens of exposed servers Read more") == "Attackers backdoored dozens of exposed servers"
    assert summary_text("Officials confirmed the breach. [Read more...]") == "Officials confirmed the breach."
    quoted = 'The minister said "we will respond." Continue reading'
    assert summary_text(quoted) == 'The minister said "we will respond."'


def test_sign_up_and_click_here_leads_are_kept_unless_they_are_calls_to_action():
    lead = "Sign up fraud surged as criminals automated account creation at scale across retailers."
    assert summary_text(f"<p>{lead}</p>") == lead
    assert summary_text("<p>Click here to subscribe to our newsletter.</p><p>The real story starts here and is long enough.</p>") == (
        "The real story starts here and is long enough."
    )


def test_truncate_handles_times_and_names():
    text = "The explosion happened shortly after 3 a.m. local time near the port, officials said in a statement on Monday."
    assert truncate(text, 60).endswith("…")
    text = "The outage hit customers of AT&T. Engineers restored most services within several hours of the incident."
    assert truncate(text, 60) == "The outage hit customers of AT&T."


def test_double_escaped_html_with_block_tags_and_tag_mentions():
    escaped = "&lt;section&gt;&lt;p&gt;The kit injects a &lt;script&gt; loader into checkout pages.&lt;/p&gt;&lt;/section&gt;"
    # The re-parse keeps every word; only the (double-escaped) tag itself disappears.
    assert summary_text(escaped) == "The kit injects a loader into checkout pages."


def test_double_escaped_captions_scripts_and_styles_are_skipped():
    lead = "Russian missiles struck the port of Odesa overnight, killing two people."
    for block in (
        "&lt;figure&gt;&lt;img src='x.jpg'&gt;&lt;figcaption&gt;Firefighters at the port after the strike "
        "(source: regional administration)&lt;/figcaption&gt;&lt;/figure&gt;",
        "&lt;script&gt;window.dataLayer.push({event: 'view'});&lt;/script&gt;",
        "&lt;style&gt;.wp-block-image{margin:0 auto;color:red}&lt;/style&gt;",
        "&lt;noscript&gt;Please enable JavaScript to view the interactive map of the strikes.&lt;/noscript&gt;",
    ):
        assert summary_text(f"{block}&lt;p&gt;{lead}&lt;/p&gt;") == lead
        assert summary_text(f"&lt;p&gt;{lead}&lt;/p&gt;{block}") == lead


def test_single_escaped_tag_and_comment_mentions_keep_their_words():
    for text in (
        "Attackers can inject a <pre> block into the signature field, and the server echoes it back.",
        "The update wraps the content in a <main> element and adds landmarks for screen readers.",
        "The phishing kit hides its configuration in an <!-- HTML comment --> near the end of the page.",
        "Attackers prepend <!-- to the payload, which disables the filter in older browsers.",
    ):
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        assert summary_text(f"<p>{escaped}</p>") == text
    assert clean_title("Bug lets a &lt;section&gt; element escape the sandbox") == "Bug lets a <section> element escape the sandbox"
    assert clean_title("Browsers now treat &lt;!-- inside scripts differently") == "Browsers now treat <!-- inside scripts differently"
    # A double-escaped comment in front of real markup is still removed.
    assert summary_text("&lt;!-- wp:paragraph --&gt;&lt;p&gt;Officials confirmed the outage on Friday.&lt;/p&gt;") == (
        "Officials confirmed the outage on Friday."
    )


def test_plain_titles_drop_stray_breaks_and_images():
    assert clean_title("Breaking:<br />Ransomware hits hospital chain", plain=True) == "Breaking: Ransomware hits hospital chain"
    assert clean_title('<img src="x.png" alt="">Patch now', plain=True) == "Patch now"
    assert clean_title("How <script> tags hide malware", plain=True) == "How <script> tags hide malware"


def test_truncate_keeps_initials_after_acronyms_and_cuts_before_product_names():
    text = (
        "The company confirmed the breach on Tuesday in a statement from its CEO J. Smith, who said customer "
        "data had been accessed by the intruders."
    )
    assert truncate(text, 100).endswith("…") and "J. Smith" in truncate(text, 100)
    text = "Apple has released emergency updates for two flaws. iOS 18.1 and macOS 15.1 address both of them in WebKit."
    assert truncate(text, 80) == "Apple has released emergency updates for two flaws."
    text = "Microsoft fixed a zero-day in its October Patch Tuesday release. npm packages were also hit this week."
    assert truncate(text, 90) == "Microsoft fixed a zero-day in its October Patch Tuesday release."
    text = "Researchers led by Smith et al. found that the malware spread through several hundred routers."
    assert "et al. found" in truncate(text, 70)
    text = "Clashes continued overnight in the west of the country. eSwatini and its neighbours closed borders."
    assert truncate(text, 60) == "Clashes continued overnight in the west of the country."
    text = "Officials described the attack in the west of the U.S. with the most recent waves"
    assert truncate(text, 58) == "Officials described the attack in the west of the U.S…"  # never ".…"
    assert truncate("The group known as APT X. Officials said the campaign targeted ministries across Europe.", 40) == (
        "The group known as APT X."
    )
