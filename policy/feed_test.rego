package feed_test

import rego.v1

import data.feed

good := ["🔴 Blocked: a", "🟡 Active: b", "🟢 Done: c", "⚪ Pending: d", "🔧 TOUCHES: none", "🔀 OVERLAP: none", "📍 State: e"]

# must permit: the seven-line form
test_permits_full_form if {
	count(feed.deny) == 0 with input as {"lines": good}
}

# must permit: the minimum form (three lines)
test_permits_minimum if {
	count(feed.deny) == 0 with input as {"lines": ["🔧 TOUCHES: x", "🔀 OVERLAP: none", "📍 State: y"]}
}

# must refuse: the old five-line form without TOUCHES/OVERLAP
test_refuses_old_form if {
	d := feed.deny with input as {"lines": ["🔴 a", "🟡 b", "🟢 c", "⚪ d", "📍 e"]}
	count(d) == 2
}

# must refuse: an empty TOUCHES
test_refuses_empty_touches if {
	d := feed.deny with input as {"lines": ["🔧 TOUCHES:", "🔀 OVERLAP: none", "📍 e"]}
	count(d) == 1
	some m in d
	contains(m, "TOUCHES")
}

# must refuse: a line without a mark, nine lines, zero lines
test_refuses_unmarked if {
	d := feed.deny with input as {"lines": array.concat(good, ["Done: x"])}
	some m in d
	contains(m, "refused: Done: x")
}

test_refuses_nine_lines if {
	d := feed.deny with input as {"lines": array.concat(good, ["🟢 x", "🟢 y"])}
	some m in d
	contains(m, "got 9")
}

test_refuses_empty if {
	d := feed.deny with input as {"lines": []}
	some m in d
	contains(m, "got 0")
}

# crew#331: must refuse a held lane whose holder OVERLAP does not name
test_refuses_held_lane if {
	count(feed.deny) == 1 with input as {"lines": good, "session": "bbbb", "lane": "idp", "holders": ["aaaa"]}
}

# crew#331: must permit when OVERLAP names the holder, and when nobody holds the lane
test_permits_named_holder if {
	named := array.concat(array.slice(good, 0, 5), ["🔀 OVERLAP: aaaa owns the drill", "📍 State: e"])
	count(feed.deny) == 0 with input as {"lines": named, "session": "bbbb", "lane": "idp", "holders": ["aaaa"]}
}

test_permits_free_lane if {
	count(feed.deny) == 0 with input as {"lines": good, "session": "bbbb", "lane": "idp", "holders": []}
}

# R49: a value after password= is refused; an env NAME is not a value
test_refuses_secret_value if {
	count(feed.deny) > 0 with input as {"lines": ["🔧 TOUCHES: x", "🔀 OVERLAP: none", concat("", ["📍 State: password=", "hunter", "2222", "wxyz"])]}
}

test_permits_secret_name if {
	count(feed.deny) == 0 with input as {"lines": ["🔧 TOUCHES: x", "🔀 OVERLAP: none", "📍 State: token=TELEGRAM_BOT_TOKEN in the vault"]}
}
