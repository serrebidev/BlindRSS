from core import utils


def test_ning_feed_story_title_is_preferred_over_generic_activity_title():
    html = """
    <span class="feed-string"><a href="https://example.ning.com/profile/User?xg_source=activity">User</a> posted a video</span>
    <div class="rich">
      <h3 class="feed-story-title">
        <a href="https://example.ning.com/xn/detail/1:Video:123?xg_source=activity">Actual Video Title</a>
      </h3>
      <div class="feed-more"><a href="https://example.ning.com/foo">1 more…</a></div>
    </div>
    """
    title = utils.enhance_activity_entry_title(
        "User posted a video",
        "https://example.ning.com/xn/detail/1:Video:123?xg_source=activity",
        html,
    )
    assert title == "Actual Video Title"


def test_ning_multi_item_picks_primary_story_not_last_more_link():
    html = """
    <div class="rich-detail"><ul class="links">
      <li><h3 class="feed-story-title"><a href="https://example.ning.com/xn/detail/1:BlogPost:100?xg_source=activity">First Story</a></h3></li>
      <li><h3 class="feed-story-title"><a href="https://example.ning.com/xn/detail/1:BlogPost:101?xg_source=activity">Second Story</a></h3></li>
      <li><h3 class="feed-story-title"><a href="https://example.ning.com/xn/detail/1:BlogPost:102?xg_source=activity">Third Story</a></h3></li>
    </ul></div>
    <div class="feed-more"><a href="https://example.ning.com/profiles/blog/list?user=abc&xg_source=activity">1 more…</a></div>
    """
    title = utils.enhance_activity_entry_title(
        "Someone posted blog posts",
        "https://example.ning.com/xn/detail/1:BlogPost:100?xg_source=activity",
        html,
    )
    assert title == "First Story"


def test_ning_reply_discussion_prefers_strong_discussion_title_over_reply_link():
    html = """
    <div>
      <a href="https://creators.ning.com/members/ScottBishop">Scott Bishop</a>
      <a href="https://creators.ning.com/forum/topics/foo?commentId=6651893%3AComment%3A2107942">replied</a>
      to <a href="https://creators.ning.com/members/RosasNegras">Alex</a>'s discussion
      <br/>
      <strong><a href="https://creators.ning.com/forum/topics/foo">HTML Browser Popup Window Generator</a></strong>
    </div>
    """
    title = utils.enhance_activity_entry_title(
        "Scott Bishop replied to Alex's discussion HTML Browser Popup Window Generator",
        "https://creators.ning.com/forum/topics/foo?commentId=6651893%3AComment%3A2107942",
        html,
    )
    assert title == "HTML Browser Popup Window Generator"


def test_ning_profile_update_keeps_original_title():
    html = """
    <div><a href="https://creators.ning.com/members/Kathleen_aka_SunKat">Kathleen (SunKat)</a>
    updated their <a href="https://creators.ning.com/members/Kathleen_aka_SunKat">profile</a></div>
    """
    title = utils.enhance_activity_entry_title(
        "Kathleen (SunKat) updated their profile",
        "https://creators.ning.com/members/Kathleen_aka_SunKat",
        html,
    )
    assert title == "Kathleen (SunKat) updated their profile"


def test_supercast_episode_title_not_replaced_by_manage_subscription_footer():
    # Supercast subscriber feeds append a "Share | Manage Subscription" footer of
    # <strong><a> links to every episode description. The real episode title must
    # win over those footer links (GitHub #20).
    html = """
    <p>In 1989, young Monica receives an unexpected treatment.</p>
    <p>
      <strong><a href="https://sixminutes.supercast.com/subscriber_v2/referrals/new?feed_item_id=1300198">📢 Share</a></strong> |
      <strong><a href="https://sixminutes.supercast.com/subscriber_v2/subscription">⚙️ Manage Subscription</a></strong>
    </p>
    """
    title = utils.enhance_activity_entry_title(
        "S5 EP33: A World Without Sad Country Mixtapes",
        "",
        html,
    )
    assert title == "S5 EP33: A World Without Sad Country Mixtapes"


def test_strong_anchor_footer_does_not_override_plain_article_title():
    html = """
    <p>Some article body text.</p>
    <p><strong><a href="https://example.com/newsletter/signup">Subscribe to our newsletter today</a></strong></p>
    """
    title = utils.enhance_activity_entry_title(
        "Breaking: Local Bakery Wins National Award",
        "https://example.com/articles/bakery",
        html,
    )
    assert title == "Breaking: Local Bakery Wins National Award"


def test_ning_posted_discussion_with_only_see_more_does_not_replace_title():
    html = """
    <div><a href="https://creators.ning.com/members/ScottBishop">Scott Bishop</a> posted a discussion</div>
    <div><div>Some discussion excerpt text here.</div></div>
    <div><a href="https://creators.ning.com/forum/topics/add-a-popup-banner-signup-or-sign-in-popup">See More</a></div>
    """
    title = utils.enhance_activity_entry_title(
        "Scott Bishop posted a discussion",
        "https://creators.ning.com/forum/topics/add-a-popup-banner-signup-or-sign-in-popup",
        html,
    )
    assert title == "Scott Bishop posted a discussion"
