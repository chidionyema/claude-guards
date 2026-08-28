package adapters_test

import rego.v1

import data.adapters

test_session_start_names_seven_adapters if {
	# seven since canonical-root-guard moved into session.rego (crew#603 CP5)
	count(adapters.session_start) == 7
}

test_no_session_start_adapter_lives_in_the_archive if {
	every row in array.concat(array.concat(array.concat(adapters.session_start, adapters.user_prompt_submit), adapters.stop), [r.run | some r in adapters.pre_tool_use]) {
		not contains(row[0], "archive/")
	}
}

test_every_adapter_is_a_bare_python_file_name if {
	every row in array.concat(array.concat(array.concat(adapters.session_start, adapters.user_prompt_submit), adapters.stop), [r.run | some r in adapters.pre_tool_use]) {
		endswith(row[0], ".py")
		not contains(row[0], "/")
	}
}

test_user_prompt_submit_names_five_adapters if {
	count(adapters.user_prompt_submit) == 5
}

test_pre_tool_use_names_seven_guards_each_with_a_tools_list if {
	# seven since scope-guard moved into hooks.rego (crew#603 CP5)
	count(adapters.pre_tool_use) == 7
	every r in adapters.pre_tool_use {
		is_array(r.tools)
		endswith(r.run[0], ".py")
	}
}

test_stop_names_fourteen_adapters if {
	count(adapters.stop) == 14
}

test_sync_guard_is_the_first_thing_a_session_runs if {
	adapters.session_start[0][0] == "sync-guard.py"
}
