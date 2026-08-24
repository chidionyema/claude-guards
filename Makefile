# One command per thing this repository has to prove, so that nobody has to
# remember four. `make test` is what the policy CI job runs.
#
# conftest ships OPA inside it, so `conftest verify` runs the Rego unit tests and
# there is no second binary to install.

.PHONY: help test guard

COMMAND_POLICY := policy/command.rego

help:
	@echo "make test              run every gate this repo has"
	@echo "make guard NAME=x      scaffold a new command refusal in $(COMMAND_POLICY)"

test:
	conftest verify --policy policy
	conftest test --policy policy policy/fixtures/must_allow.json
	python3 rule-guard.py --selftest

# Scaffold a rule. It lands with TODOs in `re`, `must_match` and `must_not_match`,
# so `conftest verify` fails until real examples replace them -- which is the
# point. A rule whose pattern has never been shown to match anything is a comment.
guard:
	@test -n "$(NAME)" || { echo "usage: make guard NAME=my_rule"; exit 2; }
	@grep -q '# make guard inserts here' $(COMMAND_POLICY) \
		|| { echo "$(COMMAND_POLICY) has lost its insertion marker"; exit 2; }
	@awk -v name="$(NAME)" ' \
		/# make guard inserts here/ { \
			lift = 0; \
			while ((getline line < "policy/template.rego") > 0) { \
				if (line ~ /^# <<< entry$$/) { lift = 0 } \
				else if (lift) { \
					sub(/^entry := /, "", line); \
					gsub(/RULE_NAME/, name, line); \
					if (line == "}") { line = "}," } \
					print (line == "" ? "" : "\t" line); \
				} \
				else if (line ~ /^# >>> entry$$/) { lift = 1 } \
			} \
		} { print } ' $(COMMAND_POLICY) > $(COMMAND_POLICY).new
	@mv $(COMMAND_POLICY).new $(COMMAND_POLICY)
	@conftest fmt $(COMMAND_POLICY)
	@echo "added rule '$(NAME)' to $(COMMAND_POLICY). Now:"
	@echo "  1. replace the three TODOs with a real pattern and two real examples"
	@echo "  2. add the refused command to policy/command_test.rego"
	@echo "  3. make test"
	@echo
	@conftest verify --policy policy || { \
		echo; \
		echo "^ expected: the new rule does not match its own example yet."; \
		exit 0; \
	}
