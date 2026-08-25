package rulings_test

import data.rulings
import rego.v1

good := {"register": ["R33-feed-handoff-every-30-minutes", "R34-net-new-research-paradigm"], "docs": ["R34-net-new-research-paradigm.md"]}

test_clean_register_and_docs_permitted if {
	count(rulings.deny) == 0 with input as good
}

test_number_claimed_twice_refused if {
	count(rulings.deny) == 1 with input as {"register": ["R35-research-crew", "R35-rebuild-with-confidence"], "docs": []}
}

test_doc_without_register_entry_refused if {
	count(rulings.deny) == 1 with input as {"register": ["R33-feed-handoff-every-30-minutes"], "docs": ["R36-research-is-a-crew.md"]}
}

test_doc_number_matches_by_number_not_slug if {
	count(rulings.deny) == 0 with input as {"register": ["R35-research-crew-is-a-platform-layer"], "docs": ["R35-research-crew-is-a-platform-layer-for-every-product.md"]}
}
